"""Measured transparent text blocks inside existing UI containers.

Geometry, copy and protected objects belong to the source-bound recipe. This
renderer never paints a background or silently squeezes text below its minimum.
"""
from pathlib import Path
from .common import require
from .layout import overlaps


def render(spec, destination):
    from PIL import Image, ImageDraw, ImageFont, features
    width, height = spec['size']
    canvas = Image.new('RGBA', (width, height))
    draw = ImageDraw.Draw(canvas)
    records = []
    for block in spec['blocks']:
        x, y, w, h = block['box']
        require(w > 0 and h > 0 and x >= 0 and y >= 0 and x+w <= width and y+h <= height,
                'Text box exceeds canvas')
        container = block['container']
        cx, cy, cw, ch = container
        require(cx <= x and cy <= y and x+w <= cx+cw and y+h <= cy+ch,
                'Text box exceeds its existing container')
        protected = spec.get('protected_regions', [])
        require(not any(overlaps(block['box'], box) for box in protected),
                'Text box intersects a protected object')
        require(block.get('align', 'left') in ('left', 'center', 'right'), 'Invalid alignment')
        # Thai/Arabic/Indic require shaping; detached marks are not a fallback.
        if block.get('requires_shaping'):
            require(features.check('raqm'), 'Complex text requires a shaping-capable renderer')
        lines = block['lines']
        require(lines and all(isinstance(line, str) and line for line in lines), 'Supply reviewed line breaks')
        font_path = Path(block['font'])
        require(font_path.is_file(), 'Requested font is missing')
        chosen = None
        stroke = block.get('stroke_width', 0)
        gap = block.get('line_gap', 2)
        for size in range(block['font_size'], block['min_font_size']-1, -1):
            font = ImageFont.truetype(str(font_path), size)
            bounds = [draw.textbbox((0, 0), line, font=font, stroke_width=stroke) for line in lines]
            total = sum(b[3]-b[1] for b in bounds) + gap*(len(lines)-1)
            if max(b[2]-b[0] for b in bounds) <= w and total <= h:
                chosen = (size, font, bounds, total)
                break
        require(chosen is not None, 'Text needs revised line breaks or a larger reviewed box')
        size, font, bounds, total = chosen
        cursor = y
        glyph_boxes = []
        for line, b in zip(lines, bounds):
            line_width, line_height = b[2]-b[0], b[3]-b[1]
            offset = {'left': 0, 'center': (w-line_width)/2, 'right': w-line_width}[block.get('align', 'left')]
            glyph_box = [x+offset, cursor, line_width, line_height]
            require(not any(overlaps(glyph_box, prior) for record in records for prior in record['glyph_boxes']),
                    'Rendered text blocks overlap')
            draw.text((x+offset-b[0], cursor-b[1]), line, font=font,
                      fill=block.get('color', '#111111'), stroke_width=stroke,
                      stroke_fill=block.get('stroke_color', '#111111'))
            glyph_boxes.append(glyph_box)
            cursor += line_height+gap
        records.append({'id': block['id'], 'font_size': size, 'glyph_boxes': glyph_boxes})
    canvas.save(destination)
    return {'size': [width, height], 'background': 'transparent', 'blocks': records}


def protected_patch_filters(region, protected_regions):
    """Black out protected rectangles in a grayscale patch alpha mask.

Coordinates are source-frame coordinates; the returned filters act on a cropped
patch. Apply them after feathering so protection never leaks through a soft edge.
"""
    x, y, w, h = region
    filters = []
    for px, py, pw, ph in protected_regions:
        left, top = max(x, px), max(y, py)
        right, bottom = min(x+w, px+pw), min(y+h, py+ph)
        if right > left and bottom > top:
            filters.append(f'drawbox=x={left-x}:y={top-y}:w={right-left}:h={bottom-top}:color=black:t=fill')
    return filters
