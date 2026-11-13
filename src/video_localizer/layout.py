"""Measured native type placement, bounded to the reviewed source text region."""
from __future__ import annotations

from pathlib import Path
import os
import sys
import math

from .common import CODE_ROOT, require, require_number


def overlaps(a, b):
    x, y, w, h = a
    bx, by, bw, bh = b
    return max(x, bx) < min(x+w, bx+bw) and max(y, by) < min(y+h, by+bh)


def validate(item, meta):
    x, y, w, h = item['bbox']
    for box in item.get('protected_regions', []):
        require(len(box) == 4 and all(isinstance(v, (int, float)) and v >= 0 for v in box), 'Invalid protected region')
        require(box[2] > 0 and box[3] > 0 and box[0]+box[2] <= meta['width'] and box[1]+box[3] <= meta['height'], 'Protected region exceeds frame')
        require(not overlaps(item['bbox'], box), f"Text {item['id']} overlaps a protected region")
    require(item.get('align', 'center') in ('left', 'center', 'right'), 'Invalid text alignment')
    require(supported_family(item.get('font_family', default_family(item['target_text']))), 'Unsupported font family')
    require_number(item.get('padding', 2), 'Text padding', maximum=min(w, h)/2)


FONT_FILES = {'Microsoft YaHei': ('msyh.ttc', 'msyhbd.ttc'), 'SimSun': ('simsun.ttc', 'simsun.ttc'),
              'KaiTi': ('simkai.ttf', 'simkai.ttf'), 'Arial': ('arial.ttf', 'arialbd.ttf'),
              'Yu Gothic': ('YuGothM.ttc', 'YuGothB.ttc'), 'Malgun Gothic': ('malgun.ttf', 'malgunbd.ttf')}


def measurement_font(root, family, bold=False):
    """Use the requested face only; never silently substitute a different family."""
    if family not in FONT_FILES:
        return measurement_face(root, family, bold)['path']
    filename = FONT_FILES[family][bool(bold)]
    project = Path(root) / 'assets/fonts' / filename
    candidates = [project]
    if sys.platform == 'win32':
        candidates.append(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / filename)
    elif sys.platform == 'darwin' and family == 'Arial':
        candidates.append(Path('/System/Library/Fonts/Supplemental') / ('Arial Bold.ttf' if bold else 'Arial.ttf'))
    return next((path for path in candidates if path.is_file()), project)


def supported_family(family):
    from .fonts import policy
    return family in FONT_FILES or family in policy()['native_families']


def default_family(text='', locale=None):
    from .fonts import default_family as choose
    return choose(text, locale)


def typography_lines(text, lines=None):
    """Accept layout-only whitespace changes without changing final copy."""
    if lines is None:
        return text.split('\n')
    require(isinstance(lines, list) and 1 <= len(lines) <= 3
            and all(isinstance(line, str) and line.strip() and '\n' not in line and '\r' not in line for line in lines),
            'layout_lines needs one to three nonempty lines')
    require(' '.join(' '.join(lines).split()) == ' '.join(text.split()),
            'Layout must preserve the exact target words and logical order')
    return lines


def measure_typography(text, font_path, box, requested, minimum, outline=2, direction='ltr', lines=None):
    """Measure complete shaping runs, including ink overhang and line boxes."""
    from PIL import ImageFont, features
    require(direction in ('ltr', 'rtl'), 'Invalid text direction')
    require_number(requested, 'font size', minimum=1)
    require_number(minimum, 'minimum font size', minimum=1, maximum=requested)
    actual_lines = typography_lines(text, lines)
    complex_script = direction == 'rtl' or any(0x590 <= ord(char) <= 0xEFF for char in text)
    shaped = features.check('raqm')
    options = {'direction': direction} if shaped else {}
    for size in range(int(requested), math.ceil(minimum)-1, -1):
        font = ImageFont.truetype(str(font_path), size)
        widths = []
        for line in actual_lines:
            left, _, right, _ = font.getbbox(line, **options)
            widths.append(max(font.getlength(line, **options), right) - min(0, left))
        ascent, descent = font.getmetrics()
        ink_width = max(widths) + 2*outline + 4
        line_height = (ascent+descent)*len(actual_lines)*1.2 + 2*outline + 4
        if ink_width <= box[2] and line_height <= box[3]:
            return {'lines': actual_lines, 'font_size': size, 'width': round(ink_width, 3),
                    'height': round(line_height, 3), 'width_coverage': round(ink_width/box[2], 4),
                    'metrics': 'shaped' if shaped else 'basic',
                    'shaping_review_required': complex_script and not shaped, 'fits': True}
    return {'lines': actual_lines, 'font_size': None, 'fits': False,
            'metrics': 'shaped' if shaped else 'basic', 'shaping_review_required': complex_script and not shaped}


def typography_candidates(text, font_path, box, requested, minimum, outline=2, direction='ltr'):
    """Offer bounded whitespace layouts; selection remains a visual decision."""
    from itertools import combinations
    words = text.split()
    require(bool(words), 'No target copy to lay out')
    layouts = [text.split('\n'), [' '.join(words)]]
    positions = sorted({max(1, min(len(words)-1, round(len(words)*fraction/8))) for fraction in range(1, 8)}) if len(words)>1 else []
    for count in (2, 3):
        for cuts in combinations(positions, count-1):
            boundaries = (0, *cuts, len(words))
            layouts.append([' '.join(words[start:end]) for start, end in zip(boundaries, boundaries[1:])])
    unique = list(dict.fromkeys(tuple(lines) for lines in layouts if len(lines) <= 3))
    return [dict(id=f'layout-{index+1}', **measure_typography(text, font_path, box, requested, minimum,
                 outline, direction, list(lines))) for index, lines in enumerate(unique)]


def measurement_face(root, family, bold=False):
    from .fonts import native_face, policy
    require(supported_family(family), 'Unsupported font family')
    if family in policy(root)['native_families']:
        return native_face(root, family, bold)
    return {'path': measurement_font(root, family, bold), 'index': 0, 'family': family}


def font_size(item):
    """Measure the actual font instead of letting a long translation cover its neighbors."""
    try:
        from PIL import ImageFont
    except ImportError:
        # Explicit font measurements are optional for old inventories, mandatory for this route.
        require(not item.get('fit_text'), 'Measured text fitting requires Pillow')
        return item.get('font_size', max(18, round(item['bbox'][3] * .48)))
    family = item.get('font_family', default_family(item['target_text'], item.get('target_language')))
    face = item.get('_font_face') or measurement_face(CODE_ROOT, family, item.get('bold', False))
    font_path = face['path']
    requested = item.get('font_size', max(18, round(item['bbox'][3] * .48)))
    if not item.get('fit_text'):
        return requested
    require(font_path.is_file(), f'Measurement font missing: {family}')
    from .fonts import missing_glyphs
    missing = missing_glyphs(face, item['target_text'])
    require(not missing, 'Font missing glyphs: ' + ', '.join(f'U+{ord(c):04X}' for c in missing))
    padding = item.get('padding', 2)
    # The final ink includes every outline layer and the shadow. Measuring
    # advance alone can approve a phrase whose visible letters get clipped.
    outline = max([item.get('outline', 0),
                   *[layer['width'] for layer in item.get('outline_layers', [])]])
    shadow = abs(item.get('shadow', 0))
    require_number(outline, 'fitting outline', maximum=24)
    require_number(shadow, 'fitting shadow', maximum=24)
    inset = padding + outline + shadow
    w, h = item['bbox'][2]-2*inset, item['bbox'][3]-2*inset
    minimum = item.get('min_font_size', 8)
    require_number(minimum, 'minimum readable font size', minimum=8, maximum=requested)
    for size in range(round(requested), math.ceil(minimum)-1, -1):
        font = ImageFont.truetype(str(font_path), size, index=face['index'])
        # libass defines fontsize using total ascender+descender height; Pillow uses em.
        # Convert metrics before fitting or Chinese text gets needlessly shrunk.
        ascent, descent = font.getmetrics()
        factor = size / (ascent + descent)
        lines = item['target_text'].split('\n')
        widths = [max(font.getlength(line), font.getbbox(line)[2]-font.getbbox(line)[0])*factor for line in lines]
        glyph_height = max(font.getbbox(line)[3]-font.getbbox(line)[1] for line in lines)*factor
        line_height = item.get('line_height', size)
        require_number(line_height, 'line height', minimum=1)
        block_height = (len(lines)-1)*line_height + glyph_height
        if max(widths) <= w-2 and block_height <= h:
            return size
    require(False, 'Translation cannot fit the reviewed source region at readable size')
