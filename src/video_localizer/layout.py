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
    w, h = item['bbox'][2]-2*padding, item['bbox'][3]-2*padding
    minimum = item.get('min_font_size', 8)
    require_number(minimum, 'minimum readable font size', minimum=8, maximum=requested)
    for size in range(round(requested), math.ceil(minimum)-1, -1):
        font = ImageFont.truetype(str(font_path), size, index=face['index'])
        # libass defines fontsize using total ascender+descender height; Pillow uses em.
        # Convert metrics before fitting or Chinese text gets needlessly shrunk.
        ascent, descent = font.getmetrics()
        factor = size / (ascent + descent)
        lines = item['target_text'].split('\n')
        widths = [font.getlength(line)*factor for line in lines]
        glyph_height = max(font.getbbox(line)[3]-font.getbbox(line)[1] for line in lines)*factor
        line_height = item.get('line_height', size)
        require_number(line_height, 'line height', minimum=1)
        block_height = (len(lines)-1)*line_height + glyph_height
        if max(widths) <= w-2 and block_height <= h:
            return size
    require(False, 'Translation cannot fit the reviewed source region at readable size')
