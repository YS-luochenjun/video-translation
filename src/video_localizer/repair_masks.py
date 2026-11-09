"""Explicit source-pixel selectors; thresholds belong to reviewed task recipes."""
from .common import require


def select(frame, region, spec, cv2, np):
    require(set(spec) <= {'hsv_ranges', 'near_hsv_ranges', 'near_radius', 'open_kernel', 'components', 'fill_holes', 'dilate'},
            'Unknown mask selector setting')
    ranges = spec.get('hsv_ranges')
    require(isinstance(ranges, list) and ranges, 'Explicit HSV ranges required')
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = np.zeros(region.shape, np.uint8)
    for bounds in ranges:
        require(isinstance(bounds, list) and len(bounds) == 2 and all(len(v) == 3 for v in bounds),
                'HSV range needs lower and upper triples')
        require(all(type(v) is int and 0 <= v <= limit for row in bounds for v, limit in zip(row, (179,255,255)))
                and all(a <= b for a,b in zip(*bounds)), 'Invalid HSV range')
        mask |= cv2.inRange(hsv, np.array(bounds[0],np.uint8), np.array(bounds[1],np.uint8))
    mask &= region
    if 'near_hsv_ranges' in spec:
        # Source caption outlines can distinguish white lettering from unrelated
        # highlights, jewelry and native white UI. Fill closed glyph interiors
        # only after this source-color proximity test.
        nearby = spec['near_hsv_ranges']
        radius = spec.get('near_radius', 8)
        require(isinstance(nearby,list) and nearby and type(radius) is int and 1<=radius<=64,
                'Explicit nearby HSV ranges and bounded radius required')
        support = np.zeros_like(mask)
        for bounds in nearby:
            require(isinstance(bounds,list) and len(bounds)==2 and all(len(v)==3 for v in bounds)
                    and all(type(v) is int and 0<=v<=limit for row in bounds for v,limit in zip(row,(179,255,255)))
                    and all(a<=b for a,b in zip(*bounds)), 'Invalid nearby HSV range')
            support |= cv2.inRange(hsv,np.array(bounds[0],np.uint8),np.array(bounds[1],np.uint8))
        support = cv2.dilate(support,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(2*radius+1,2*radius+1)))
        mask &= support
    else:
        require('near_radius' not in spec, 'Nearby radius requires nearby HSV ranges')
    if 'open_kernel' in spec:
        kernel = spec['open_kernel']
        require(len(kernel)==2 and all(type(v) is int and 1<=v<=31 for v in kernel), 'Invalid opening kernel')
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((kernel[1],kernel[0]),np.uint8))
    if 'components' in spec:
        limits = spec['components']
        columns = {'area':cv2.CC_STAT_AREA, 'width':cv2.CC_STAT_WIDTH, 'height':cv2.CC_STAT_HEIGHT}
        require(limits and set(limits)<=set(columns), 'Unknown component filter')
        for interval in limits.values():
            require(len(interval)==2 and all(type(v) is int and v>=0 for v in interval)
                    and interval[0]<=interval[1], 'Invalid component bounds')
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        keep = [i for i in range(1,count) if all(a<=stats[i,columns[key]]<=b for key,(a,b) in limits.items())]
        mask = np.isin(labels, keep).astype(np.uint8)*255
    require(type(spec.get('fill_holes',False)) is bool, 'Invalid hole filling flag')
    if spec.get('fill_holes'):
        contours,_ = cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(mask,contours,-1,255,cv2.FILLED)
    radius = spec.get('dilate',0)
    require(type(radius) is int and 0<=radius<=64, 'Invalid mask dilation')
    if radius:
        mask = cv2.dilate(mask,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(radius*2+1,radius*2+1)))
    return mask & region
