"""Batch target lettering into a native-timeline alpha layer, without editing source pixels.

ImageGen supplies a few reviewed artistic assets; the existing exact-font ASS
renderer supplies all timed phrases. No per-frame generation or model calls.
"""
import copy
from fractions import Fraction
from pathlib import Path

from .common import (file_hash, guarded, inside, object_hash, read_json,
                     require, require_number, write_json)


def _box(box, meta):
    require(isinstance(box, list) and len(box) == 4, 'Style layer needs an explicit target box')
    x, y, w, h = [require_number(v, 'style layer box') for v in box]
    require(w > 0 and h > 0 and x+w <= meta['width'] and y+h <= meta['height'], 'Style layer box exceeds frame')
    return x, y, w, h


def _art_filter(row, index, item, origin, duration, meta):
    box = item['display']['bbox']
    x, y, w, h = _box(box, meta)
    start, end = max(0, item['start']-origin), min(duration, item['end']-origin)
    require(end > start, 'Artwork is outside the selected shot')
    crop = row.get('crop')
    filters = ''
    if crop:
        require(len(crop) == 4 and all(type(v) is int and v >= 0 for v in crop)
                and crop[2] > 0 and crop[3] > 0, 'Invalid artwork crop')
        filters = f'crop={crop[2]}:{crop[3]}:{crop[0]}:{crop[1]},'
    motion = row.get('motion', {'kind': 'static'})
    require(motion.get('kind') in {'static', 'pop'}, 'Complex tracking needs a separately reviewed surface layer')
    factor = '1'
    if motion['kind'] == 'pop':
        entrance = require_number(motion.get('entrance_seconds', .16), 'entrance seconds', minimum=.03, maximum=.5)
        initial = require_number(motion.get('initial_scale', .94), 'initial scale', minimum=.75, maximum=1)
        pulse = require_number(motion.get('pulse', 0), 'pulse', maximum=.03)
        require(row.get('motion_reason'), 'Explain the observed source motion and target adaptation')
        factor = f'({initial}+(1-{initial})*min(1,max(0,(t-{start})/{entrance})))*(1-{pulse}*(1-cos(2*PI*(t-{start}))))'
    # The motion stays inside the declared box; no tracking/occlusion is implied.
    return (f'[{index}:v]{filters}scale={int(w)}:{int(h)}:force_original_aspect_ratio=decrease,'
            f"scale=w='iw*({factor})':h='ih*({factor})':eval=frame,format=rgba[art{index}];"
            f"[base{index-1}][art{index}]overlay=x={x}+({w}-overlay_w)/2:y={y}+({h}-overlay_h)/2:"
            f"enable='gte(t,{start})*lt(t,{end})':format=auto[base{index}]")


@guarded
def render(run, relative, apply=False):
    from . import compositor, media, resources, source_styles, surface, workflow
    from .captions import checked_units, normalized, units
    from .layout import overlaps
    from .visual_audit import _timestamps
    spec_path = inside(run, relative)
    spec = read_json(spec_path)
    inventory_path = run / 'analysis/inventory.json'
    inventory = copy.deepcopy(read_json(inventory_path))
    source = workflow.source_path(run)
    source_sha = file_hash(source)
    require(spec.get('source_sha256') == inventory['source_sha256'] == source_sha, 'Style layer source changed')
    require(spec.get('reason'), 'Describe the source-led lettering choice')
    shot = next((s for s in inventory['shots'] if s['id'] == spec.get('shot')), None)
    require(shot is not None, 'Select an existing source shot')
    meta = media.probe(source)
    times = _timestamps(source)
    fps = meta['fps']
    require(0 < fps <= 120 and all(abs(t-n/fps) < .0002 for n, t in enumerate(times)),
            'Variable frame timing needs another explicitly reviewed composition route')
    numbers = [n for n,t in enumerate(times) if shot['start']-.00001 <= t < shot['end']-.00001]
    require(numbers and abs(times[numbers[0]]-shot['start']) < .0002, 'Align shot start to the native source frame')
    origin, duration = times[numbers[0]], len(numbers)/fps
    artwork = spec.get('artwork', [])
    typed_ids = spec.get('typeset_ids', [])
    ids = typed_ids + [a['instance_id'] for a in artwork]
    require(ids and len(ids) == len(set(ids)), 'Select distinct target lettering instances')
    items = {i['id']: i for i in inventory['text_instances']}
    require(all(i in items and items[i].get('target_text') for i in ids), 'Select actual finalized target copy')
    active = [i for i in inventory['text_instances'] if i['start'] < shot['end'] and i['end'] > shot['start']]
    require(set(ids) <= {i['id'] for i in active}, 'Selected lettering is outside the shot')
    require(not any(i.get('display', {}).get('typography_layer') for i in active if i['id'] not in ids),
            'Include every existing surface instance; do not silently discard its layer')
    for identity in ids:
        item = items[identity]
        if item.get('trajectory'):
            require(identity in typed_ids, 'Tracked artistic lettering needs a separately reviewed surface layer')
            require(item.get('style_treatment', {}).get('adaptations', {}).get('layout'),
                    'Explain the timed target layout adaptation')
            item['display'].pop('bbox', None)  # Existing compositor consumes each timed target box.
        require(item.get('style_treatment', {}).get('route') == ('typeset' if identity in typed_ids else 'imagegen_asset'),
                'Style route must match the actual renderer')
        box = (item['trajectory'][0]['bbox'] if item.get('trajectory') else
               item.get('display', {}).get('bbox', item['bbox']))
        _box(box, meta)
        require(all(not overlaps(box, p) for p in item.get('protected_regions', [])), 'Target lettering covers protected content')
        for point in item.get('trajectory', []):
            _box(point['bbox'], meta)
            require(all(not overlaps(point['bbox'], p) for p in
                        point.get('protected_regions', item.get('protected_regions', []))),
                    'Timed target lettering covers protected content')
        item.setdefault('display', {})['typography_layer'] = True
    source_styles.contract(run, inventory)  # Existing source/frame/font/style gates.
    inputs = []
    for row in artwork:
        asset = row['asset']; path = inside(run, asset['path'])
        require(path.is_file() and file_hash(path) == asset['sha256'], 'Reviewed artwork changed')
        require(path.suffix.lower() == '.png', 'Use a transparent PNG artwork asset')
        from PIL import Image
        with Image.open(path) as image:
            require(image.mode == 'RGBA' and image.getchannel('A').getextrema()[0] == 0,
                    'Artwork must preserve transparency, without a solid text panel')
            if row.get('crop'):
                x,y,w,h = row['crop']
                require(x >= 0 and y >= 0 and w > 0 and h > 0 and x+w <= image.width and y+h <= image.height,
                        'Artwork crop exceeds the actual image')
        require(row.get('text_checked') == items[row['instance_id']]['target_text'] and row.get('observed_by'),
                'Attribute an actual exact-copy artwork inspection')
        inputs.append(asset)
    typed = []
    for identity in typed_ids:
        item = copy.deepcopy(items[identity])
        require(item.get('display', {}).get('font_asset'), 'Typeset phrases need a real bound font')
        inputs.append(item['display']['font_asset'])
        item['display']['typography_layer'] = False
        item['action'] = 'erase_then_overlay'  # Generate lettering events only, no erasure filter.
        fragments = checked_units(units(item), item['end'])
        require(all(u['start'] >= item['start'] for u in fragments) and
                normalized(''.join(u['text'] for u in fragments)) == normalized(item['target_text']),
                'Timed phrases must preserve the complete finalized copy and source window')
        typed.append(item)
    binding = {'spec': spec, 'source_sha256': source_sha, 'shot': [origin, duration],
               'instances': surface.instance_bindings(active), 'inputs': inputs,
               'implementation': file_hash(Path(__file__)),
               'text_implementation': {name: file_hash(Path(__file__).with_name(name))
                                       for name in ('compositor.py', 'layout.py', 'fonts.py', 'captions.py')}}
    folder = run / 'inputs/style-layers' / object_hash(binding)[:24]
    record_path = folder / 'provenance.json'
    output = folder / 'layer.mov'
    reused = record_path.exists()
    if reused:
        record = read_json(record_path)
        require(record.get('binding') == binding, 'Style layer provenance changed')
        cached = {**record['output'], 'record': record_path.relative_to(run).as_posix(),
                  'record_sha256': file_hash(record_path)}
        surface.verify(run, cached, source_sha,
                       read_json(run / 'inputs/request.json')['target_language'], active)
    else:
        folder.mkdir(parents=True, exist_ok=True)
        events = compositor.text_events({'start': origin, 'end': origin+duration}, typed, meta, folder, run=run)
        (folder / 'lettering.ass').write_text('\n'.join(compositor.header(meta)+events+['']), encoding='utf-8-sig')
        rate = str(Fraction(fps).limit_denominator(100000))
        args = ['-f', 'lavfi', '-i', f"color=c=black@0:s={meta['width']}x{meta['height']}:r={rate},format=rgba"]
        for row in artwork:
            args += ['-loop', '1', '-framerate', rate, '-i', inside(run, row['asset']['path'])]
        graph = '[0:v]format=rgba[base0];'
        for index, row in enumerate(artwork, 1):
            graph += _art_filter(row, index, items[row['instance_id']], origin, duration, meta) + ';'
        graph += f"[base{len(artwork)}]{media.ass_filter('lettering.ass', folder / 'fonts')}:alpha=1,format=argb[out]"
        with resources.heavy(run, 'source_style_layer'):
            media.ffmpeg([*args, '-filter_complex_threads', '1', '-filter_complex', graph, '-map', '[out]',
                          '-frames:v', len(numbers), '-an', '-c:v', 'qtrle', '-pix_fmt', 'argb', output], cwd=folder)
        actual = _timestamps(output)
        require(len(actual) == len(numbers) and all(abs(t-n/fps) < .0002 for n,t in enumerate(actual)),
                'Style layer changed native timing')
        asset = {'path': output.relative_to(run).as_posix(), 'sha256': file_hash(output),
                 'record': record_path.relative_to(run).as_posix()}
        record = {'source_sha256': source_sha, 'target_language': read_json(run / 'inputs/request.json')['target_language'],
                  'texts': {i: items[i]['target_text'] for i in ids}, 'instance_bindings': surface.instance_bindings(active),
                  'output': {'path': asset['path'], 'sha256': asset['sha256']}, 'alpha_channel': True,
                  'inputs': inputs, 'binding': binding, 'native_frames': len(numbers),
                  'method': 'Few artistic assets plus hash-bound font phrases; one native-timeline batch render, no source erasure or AI generation.',
                  'limitations': 'Pending actual whole-scene, motion, audio and per-language review; simple pop is an adaptation, not recovered tracking.'}
        write_json(record_path, record)
    asset = {**record.get('asset', {'path': output.relative_to(run).as_posix(), 'sha256': file_hash(output),
                                  'record': record_path.relative_to(run).as_posix()}), 'record_sha256': file_hash(record_path)}
    if apply:
        shot['surface_typography'] = asset
        before = run / 'inputs/style-layers' / (object_hash(binding)[:24] + '-before.json')
        if not before.exists():
            write_json(before, read_json(inventory_path))
        write_json(inventory_path, inventory)
    return {'asset': asset, 'reused': reused, 'native_frames': len(numbers), 'automatic_pass': False,
            'next': 'Bind shot.surface_typography, replan/register and review the actual encoded video'}
