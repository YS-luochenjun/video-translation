"""Model-independent spatial merge preparation; never submits a model task.

Recipes own source coordinates and native-frame intervals. Output is a mask and
FFmpeg filter graph, not a visual approval. Generated clips need prior review.
"""
from pathlib import Path
from .common import require


def prepare(spec, destination):
    from PIL import Image, ImageDraw, ImageFilter
    width, height = spec['size']
    x, y, w, h = spec['region']
    require(all(isinstance(v, int) for v in [width, height, x, y, w, h]), 'Use integer pixel geometry')
    require(x >= 0 and y >= 0 and w > 0 and h > 0 and x+w <= width and y+h <= height,
            'Repair region exceeds canvas')
    # Avoid implicit YUV420 crop rounding and resulting one-pixel seams.
    require(all(v % 2 == 0 for v in [width, height, x, y, w, h]), 'Use even video crop geometry')
    fps, total = spec['fps'], spec['source_frames']
    require(fps > 0 and isinstance(total, int) and total > 0, 'Invalid native timeline')
    needed = set()
    for a, b in spec['intervals']:
        require(isinstance(a, int) and isinstance(b, int) and 0 <= a < b <= total,
                'Use half-open native-frame intervals')
        require(not needed.intersection(range(a, b)), 'Requested repair intervals overlap')
        needed.update(range(a, b))
    require(bool(needed), 'Supply actual text occurrence intervals')
    coverage = {n: 0 for n in needed}
    expressions = []
    for clip in spec['clips']:
        a, b = clip['source_frames']
        require(isinstance(a, int) and isinstance(b, int) and 0 <= a < b <= total, 'Invalid clip interval')
        require(abs(clip['fps']-fps) < .001 and clip['actual_frames'] == b-a,
                'Clip must preserve native frame count and rate; no stretch or padding')
        lo, hi = clip.get('use_frames', [a, b])
        require(isinstance(lo, int) and isinstance(hi, int) and a <= lo < hi <= b, 'Invalid clip use window')
        spans = []
        for start, end in spec['intervals']:
            left, right = max(start, lo), min(end, hi)
            if left < right:
                spans.append(f'between(n,{left},{right-1})')
                for n in range(left, right):
                    coverage[n] += 1
        require(bool(spans), 'Clip does not cover a requested repair')
        expressions.append('+'.join(spans))
    require(all(count == 1 for count in coverage.values()), 'Each repair frame needs exactly one clip')
    feather = spec.get('feather', 8)
    require(isinstance(feather, int) and 0 <= feather < min(w, h)/2, 'Invalid feather width')
    # Direct 8-bit alpha avoids video-range white=235 leaking source lettering.
    mask = Image.new('L', (w, h), 0)
    ImageDraw.Draw(mask).rectangle((feather, feather, w-feather-1, h-feather-1), fill=255)
    if feather:
        mask = mask.filter(ImageFilter.GaussianBlur(feather/3))
    draw = ImageDraw.Draw(mask)
    for px, py, pw, ph in spec.get('protected_regions', []):
        left, top = max(x, px), max(y, py)
        right, bottom = min(x+w, px+pw), min(y+h, py+ph)
        if left < right and top < bottom:
            draw.rectangle((left-x, top-y, right-x-1, bottom-y-1), fill=0)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    mask.save(destination / 'mask.png')
    # Input 0 is the source/approved neutral base, 1..N are actual repair clips;
    # input N+1 is mask.png, supplied with -loop 1. No audio is selected here.
    count = len(spec['clips'])
    filters = ['[0:v]format=rgba[base0]']
    labels = ''.join(f'[m{i}]' for i in range(1, count+1))
    if count == 1:
        filters.append(f'[{count+1}:v]format=gray[m1]')
    else:
        filters.append(f'[{count+1}:v]format=gray,split={count}{labels}')
    for i, (clip, expression) in enumerate(zip(spec['clips'], expressions), 1):
        start = clip['source_frames'][0] / fps
        filters += [f'[{i}:v]scale={width}:{height},format=rgb24,crop={w}:{h}:{x}:{y},setpts=PTS-STARTPTS[p{i}]',
                    f'[p{i}][m{i}]alphamerge=shortest=1,setpts=PTS-STARTPTS+{start:.9f}/TB[a{i}]',
                    f"[base{i-1}][a{i}]overlay={x}:{y}:format=rgb:eof_action=pass:enable='{expression}'[base{i}]"]
    filters.append(f'[base{count}]null[v]')
    (destination / 'filter.txt').write_text(';\n'.join(filters), encoding='utf-8')
    return {'repair_frames': len(needed), 'coverage': 'exactly_once', 'mask_range': [0, 255],
            'inputs': ['source_or_approved_base', *[c['path'] for c in spec['clips']], 'mask.png'],
            'output_label': '[v]', 'audio': 'Remux the complete approved audio separately; verify packet hash.',
            'review_required': True, 'provider': 'recipe-selected; not hardcoded'}
