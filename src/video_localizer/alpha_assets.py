"""Opt-in hygiene for straight-alpha, 8-bit RGBA asset copies.

This does not infer a foreground matte, erase visible letters, or make an
alpha-ignoring consumer support transparency. Transforms still need alpha-aware
filtering and review; never overwrite an already hash-bound production asset.
"""
from .common import require


def sanitize(image, *, crop=False, padding=0):
    import numpy as np
    from PIL import Image

    require(image.mode == 'RGBA', 'Use explicit straight-alpha 8-bit RGBA input')
    require(type(crop) is bool and type(padding) is int and padding >= 0,
            'Crop must be boolean and padding a nonnegative integer')
    before = np.array(image)
    after = before.copy()
    hidden = before[:, :, 3] == 0
    changed = int(np.count_nonzero(hidden & np.any(before[:, :, :3] != 0, axis=2)))
    after[hidden, :3] = 0
    result = Image.fromarray(after)
    bounds = image.getchannel('A').getbbox()  # Includes every nonzero soft edge.
    origin = [0, 0]
    if crop and bounds:
        left, top, right, bottom = bounds
        box = (max(0, left-padding), max(0, top-padding),
               min(image.width, right+padding), min(image.height, bottom+padding))
        result = result.crop(box)
        origin = list(box[:2])
    return result, {'original_size': list(image.size), 'origin': origin,
                    'output_size': list(result.size), 'visible_bbox': list(bounds) if bounds else None,
                    'empty_foreground': bounds is None, 'cleared_hidden_rgb_pixels': changed,
                    'scope': 'Copy only; alpha and all alpha>0 RGBA values retained. '
                             'Place cropped output at origin in original_size; recheck actual transforms/consumers.'}
