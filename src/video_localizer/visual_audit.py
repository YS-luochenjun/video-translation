"""Native-size comparison evidence and explicit per-instance review contracts.

No detector or evidence generator may assign pass. Local owners can edit code/files;
this validates attributable observations, not whether a person actually saw pixels.
"""
import copy
import html
import json
import math
import os
import uuid
from contextlib import ExitStack, nullcontext
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from . import media
from .common import (WorkflowError, file_hash, guarded, inside, object_hash, operation_hash, read_json,
                     require, utc_now, write_json)

CHECKS = ('erasure', 'background_and_foreground', 'typography_fit', 'motion_occlusion_timing')
SOURCE_KEYS = ('id', 'source_text', 'start', 'end', 'bbox', 'trajectory', 'action',
               'text_role', 'background_is_static', 'protected_regions')
STYLE_KEYS = ('shape_weight', 'height_alignment_spacing', 'color_effects', 'motion_occlusion')
MANIFEST = 'text-visual-audit.json'


def _asset(run, value):
    path = inside(run, value['path'])
    require(path.is_file() and file_hash(path) == value['sha256'], 'Visual audit asset missing or changed')
    return path


def _shot_items(inventory, shot=None):
    require(isinstance(inventory.get('text_instances'), list), 'Visual audit needs the actual text inventory')
    items = inventory['text_instances']
    if shot:
        items = [i for i in items if i['start'] < shot['end'] and i['end'] > shot['start']]
    require(len({i['id'] for i in items}) == len(items), 'Duplicate visual instance IDs')
    return items


def context(run, stage, shot_id=None, asset=None, clocks=None):
    from .workflow import source_path
    inventory = read_json(run / 'analysis/inventory.json')
    original = source_path(run)
    source_sha = file_hash(original)
    shot = None
    if stage == 'neutral':
        if shot_id:
            shot = next((s for s in inventory['shots'] if s['id'] == shot_id), None)
        elif asset:
            # Equal video bytes can legitimately belong to different intervals.
            # The released record carries the interval, including during reuse
            # before its pointer has been installed in the target inventory.
            record = read_json(inside(run, asset['record']))
            if record.get('text_visual_audit'):
                audit = read_json(inside(run, record['text_visual_audit']['path']))
                matches = [s for s in inventory['shots'] if [s['start'], s['end']] == audit['binding']['interval']]
            else:
                matches = [s for s in inventory['shots'] if s.get('prepared_video') == asset]
            require(len(matches) == 1, 'Neutral preparation needs one unambiguous shot interval')
            shot = matches[0]
        require(shot is not None, 'Select an existing neutral shot')
        asset = asset or shot.get('prepared_video')
        require(asset, 'Shot has no prepared video')
        from .prepared import verify
        verify(run, asset, source_sha)
        target = _asset(run, asset)
        interval = [shot['start'], shot['end']]
        offset = shot['start']
    else:
        require(stage == 'final', 'Unknown visual audit stage')
        candidate = read_json(run / 'outputs/candidate.json')
        target = _asset(run, candidate)
        interval, offset = [0, read_json(run / 'analysis/media.json')['duration']], 0
    items = _shot_items(inventory, shot)
    binding = {'version': 1, 'stage': stage, 'source_sha256': source_sha,
               'video_sha256': file_hash(target), 'interval': interval,
               'instances': [{k: i.get(k) for k in SOURCE_KEYS} for i in items],
               'features': sorted(inventory.get('content_features', []))}
    binding['layers'] = [{'label': 'source', 'sha256': source_sha, 'interval': interval},
                         {'label': stage, 'sha256': file_hash(target), 'interval': interval}]
    if stage == 'final':
        binding.update(inventory_sha256=file_hash(run / 'analysis/inventory.json'),
                       locale=read_json(run / 'inputs/request.json')['target_language'],
                       plan_id=read_json(run / 'plan.json')['id'])
        for index, segment in enumerate(inventory['shots']):
            for field, label in [('prepared_video', 'neutral'), ('surface_typography', 'typography')]:
                if segment.get(field):
                    _asset(run, segment[field])
                    binding['layers'].append({'label': f'{label}-{index}', 'sha256': segment[field]['sha256'],
                                              'interval': [segment['start'], segment['end']]})
    if items:
        times, meta = _clock(target, {} if clocks is None else clocks)
        require(abs(meta['duration']-(interval[1]-interval[0])) <= .15,
                'Visual evidence video does not cover the required source timeline')
        binding['coverage'] = {}
        for item in items:
            numbers, mode = required_frames(item, times, offset, binding['features'])
            binding['coverage'][item['id']] = {'frames': numbers, 'pts': [times[n]+offset for n in numbers],
                'region': _region(item, meta['width'], meta['height']), 'sampling': mode}
    return binding, items, inventory, original, target, offset


def directory(run, binding):
    identity = object_hash(binding)[:24]
    base = run / 'inputs/visual-audit' if binding['stage'] == 'neutral' else run / 'review' / binding['video_sha256'][:12] / 'visual-audit'
    return base / identity


def _timestamps(path):
    data = json.loads(media.command(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_frames', '-show_entries', 'frame=best_effort_timestamp_time', '-of', 'json', path]).stdout)
    times = [float(f['best_effort_timestamp_time']) for f in data['frames']]
    require(times and all(math.isfinite(t) for t in times) and all(a < b for a, b in zip(times, times[1:])),
            'Visual audit requires monotonic decoded frame timestamps')
    return [t-times[0] for t in times]


def _clock(path, cache):
    key = str(path)
    if key not in cache:
        loader = lambda: (_timestamps(path), media.probe(path))
        cache[key] = cache['_reuse'].clock(path, loader) if cache.get('_reuse') else loader()
    return cache[key]


def required_frames(item, times, offset, features):
    absolute = [t+offset for t in times]
    active = [n for n, t in enumerate(absolute) if item['start'] <= t < item['end']]
    require(active, 'Text instance has no decoded frames in this shot')
    dynamic = bool(item.get('trajectory')) or item.get('background_is_static') is not True or bool(
        set(features) & {'animated_text', 'foreground_occlusion', 'surface_typography', 'complex_repair'})
    selected = set(active if dynamic else [active[0], active[len(active)//2], active[-1]])
    events = [item['start'], item['end']] + [p['time'] for p in item.get('trajectory', [])]
    for event in events:
        center = min(range(len(times)), key=lambda n: abs(absolute[n]-event))
        selected.update(range(max(0, center-2), min(len(times), center+3)))
    return sorted(selected), 'continuous' if dynamic else 'static_with_boundaries'


def _region(item, width, height):
    boxes = [item['bbox']] + [p['bbox'] for p in item.get('trajectory', [])]
    require(all(len(b) == 4 and all(isinstance(v, (int, float)) and math.isfinite(v) for v in b)
                and b[2] > 0 and b[3] > 0 for b in boxes), 'Invalid visual audit region')
    x = max(0, math.floor(min(b[0] for b in boxes))-16)
    y = max(0, math.floor(min(b[1] for b in boxes))-16)
    right = min(width, math.ceil(max(b[0]+b[2] for b in boxes))+16)
    bottom = min(height, math.ceil(max(b[1]+b[3] for b in boxes))+16)
    require(right > x and bottom > y, 'Visual audit region is outside the frame')
    return [x, y, right-x, bottom-y]


def _selection(numbers):
    groups = []
    for number in sorted(set(numbers)):
        if groups and number == groups[-1][1]+1:
            groups[-1][1] = number
        else:
            groups.append([number, number])
    return '+'.join(f'between(n,{a},{b})' for a, b in groups)


def _extract(path, numbers, region, destination):
    destination.mkdir(parents=True, exist_ok=True)
    x, y, w, h = region
    media.ffmpeg(['-i', path, '-vf', f"select='{_selection(numbers)}',crop={w}:{h}:{x}:{y}:exact=1",
                  '-fps_mode', 'passthrough', '-an', destination / '%06d.png'])
    files = sorted(destination.glob('*.png'))
    require(len(files) == len(set(numbers)), 'Visual evidence extraction is incomplete')
    return dict(zip(sorted(set(numbers)), files))


def _template(binding, row):
    return {'binding_id': object_hash(binding), 'instance_id': row['id'], 'reviewer': '',
            'review_type': 'same_agent', 'reviewed_at': '', 'reviewed_pages': [],
            'source_appearance': {key: '' for key in STYLE_KEYS}, 'target_requirements': '',
            'route_limitations': '', 'playback_observation': '',
            'checks': {key: {'status': 'pending', 'observation': '', 'evidence_pages': []}
                       for key in (CHECKS if binding['stage'] == 'final' else CHECKS[:2]+CHECKS[3:])}}


@guarded
def generate(run, stage='final', shot_id=None, reuse_decode=True):
    from PIL import Image, ImageDraw
    storage = read_json(run / 'run.json').get('visual_storage')
    from .visual_reuse import EvidenceCache
    decode_cache = EvidenceCache(run.parent.parent) if storage == 'comparisons-v3' and reuse_decode else None
    clocks = {'_reuse': decode_cache}
    binding, items, inventory, source, target, offset = context(run, stage, shot_id, clocks=clocks)
    folder = directory(run, binding)
    manifest_path = folder / MANIFEST
    if manifest_path.exists():
        manifest = read_json(manifest_path)
        _verify_files(folder, manifest)
        if not (folder/'reviews.json').exists():
            write_json(folder/'reviews.json', {})
        return {'manifest': str(manifest_path.relative_to(run)), 'manifest_sha256': file_hash(manifest_path),
                'viewer': str((folder/'index.html').relative_to(run)), 'reused': True, 'automatic_pass': False,
                'decode_reuse': {**(decode_cache.stats if decode_cache else {}), 'whole_bundle_reused': True}}
    if folder.exists():
        backup = folder.with_name(folder.name+'-incomplete-'+uuid.uuid4().hex[:8])
        require(folder.resolve().is_relative_to(run.resolve()) and backup.resolve().is_relative_to(run.resolve())
                and not backup.exists(), 'Incomplete evidence recovery must stay inside its run')
        folder.rename(backup)  # Retain failed capture; never touch source or delivered media.
    folder.mkdir(parents=True)
    times, meta = _clock(target, clocks)
    require(meta['width'] > 0 and meta['height'] > 0, 'Missing video geometry')
    rows, files = [], {}
    pages_html = []
    compact = storage in ('comparisons-v2', 'comparisons-v3')
    from .visual_storage import PageStore
    store = PageStore(run.parent.parent) if storage == 'comparisons-v3' else None
    # Crop pixels live in the lossless comparison strips; only extraction scratch is temporary.
    with ExitStack() as streams, (TemporaryDirectory(dir=folder, prefix='.crops-') if compact and not store else nullcontext(str(folder))) as scratch:
        for item in items:
            numbers, mode = required_frames(item, times, offset, binding['features'])
            region = _region(item, meta['width'], meta['height'])
            key = object_hash(item['id'])[:12]
            row = {'id': item['id'], 'action': item['action'], 'region': region, 'sampling': mode,
                   'required_frames': numbers, 'pts': [times[n]+offset for n in numbers], 'pages': [], 'missing_layers': []}
            # Every comparison uses the nearest decoded PTS; actual selected timestamps
            # are recorded so frame-rate conversion is visible, never assumed to be 30fps.
            layers = [('source', source, 0, binding['interval'])]
            if stage == 'neutral':
                layers.append(('neutral', target, offset, binding['interval']))
            else:
                for index, shot in enumerate(inventory['shots']):
                    if not any(shot['start'] <= times[n]+offset < shot['end'] for n in numbers):
                        continue
                    for field, label in [('prepared_video', 'neutral'), ('surface_typography', 'typography')]:
                        if shot.get(field):
                            layers.append((f'{label}-{index}', _asset(run, shot[field]), shot['start'], [shot['start'], shot['end']]))
                        else:
                            row['missing_layers'].append(f'{label}:{shot["id"]}')
                layers.append(('final', target, 0, binding['interval']))
            mapped = []
            for label, path, shift, interval in layers:
                timeline, layer_meta = _clock(path, clocks)
                require((layer_meta['width'], layer_meta['height']) == (meta['width'], meta['height']),
                        'Comparison layers need matching native dimensions; normalize through the production route first')
                mapping = {n: min(range(len(timeline)), key=lambda k: abs(timeline[k]+shift-(times[n]+offset)))
                           for n in numbers if interval[0] <= times[n]+offset < interval[1]}
                if not mapping:
                    continue
                if decode_cache:
                    crops = streams.enter_context(decode_cache.tiles(path, mapping.values(), region, label, _selection))
                elif store:
                    from .crop_stream import CropStream
                    crops = streams.enter_context(CropStream(path,mapping.values(),region,_selection))
                else:
                    crops = _extract(path, mapping.values(), region, Path(scratch) / key / label)
                mapped.append((label, mapping, crops, timeline, shift))
            # One native crop strip per frame: the viewer scrolls at 1:1 scale. It
            # never reduces 131 frames into a single unreadable contact sheet.
            for n in numbers:
                observations, parts, references = {}, [], []
                relative = f'{key}/compare-{n:06}.png'
                if decode_cache:
                    references = [(crops, mapping[n]) for _, mapping, crops, _, _ in mapped if n in mapping]
                pixel_key = decode_cache.restore_page(references, folder / relative, store) if decode_cache else None
                for label, mapping, crops, timeline, shift in mapped:
                    if n not in mapping:
                        continue
                    source_n = mapping[n]
                    observations[label] = {'frame': source_n, 'pts': timeline[source_n]+shift}
                    if pixel_key:
                        continue
                    path = crops[source_n]
                    if decode_cache:
                        parts.append(path)
                    else:
                        with (Image.open(path) if isinstance(path,Path) else nullcontext(path)) as im:
                            tile = Image.new('RGB', (im.width, im.height+25), '#777777')
                            tile.paste(im.convert('RGB'), (0, 25), im.getchannel('A') if 'A' in im.getbands() else None)
                            caption = label if store else f'{label} f{source_n}'
                            ImageDraw.Draw(tile).text((3, 4), caption, fill='white')
                            parts.append(tile)
                if not pixel_key:
                    strip = Image.new('RGB', (sum(p.width for p in parts), max(p.height for p in parts)), '#777777')
                    left = 0
                    for part in parts:
                        strip.paste(part, (left, 0)); left += part.width
                    (folder / key).mkdir(parents=True, exist_ok=True)
                    pixel_key = store.save(strip, folder / relative) if store else None
                    if not store:
                        strip.save(folder / relative)
                    if decode_cache:
                        left = 0
                        tile_hashes = [crops.fingerprint(source_n) for crops, source_n in references]
                        for part, (crops, source_n) in zip(parts, references):
                            crops.remember(source_n, folder / relative, [left, 0, left + part.width, part.height],
                                           pixel_key, strip.size, tile_hashes)
                            left += part.width
                row['pages'].append({'id': relative, 'frame': n, 'pts': times[n]+offset, 'layers': observations,
                                     **({'pixels_sha256': pixel_key} if store else {})})
                pages_html.append(f'<p>{html.escape(item["id"])} frame {n}, PTS {times[n]+offset:.6f}</p><img src="{relative}" alt="native-size comparison">')
            if store:
                for _,_,crops,_,_ in mapped:
                    crops.__exit__(None,None,None)
            write_json(folder / 'templates' / (key+'.json'), _template(binding, row))
            rows.append(row)
    # Full compositions and playback remain necessary alongside cropped strips.
    for label, path in [('source', source), (stage, target)]:
        media.ffmpeg(['-i', path, '-frames:v', '1', folder / (label+'-composition.png')])
    playback = ''.join(f'<p><a href="{html.escape(Path(os.path.relpath(p, folder)).as_posix(), quote=True)}">Open {label} video for normal-speed playback</a></p>' for label, p in [('source', source), (stage, target)])
    viewer = '<!doctype html><meta charset="utf-8"><title>Visual review evidence</title><style>img{max-width:none}body{background:#ddd;font-family:sans-serif}</style><h1>Evidence only — pending until individually reviewed</h1><p>Native pixels, no CSS shrinking. Compare full composition and play the source/output too. Generated frames do not prove review.</p>' + playback + ''.join(pages_html)
    (folder / 'index.html').write_text(viewer, encoding='utf-8')
    for path in folder.rglob('*'):
        if path.is_file() and 'templates' not in path.relative_to(folder).parts:
            files[path.relative_to(folder).as_posix()] = file_hash(path)
    if decode_cache:
        decode_cache.verify_inputs()
    if store:
        store.commit()
    manifest = {'binding': binding, 'instances': rows, 'files': files,
                'created_at': utc_now(), 'storage': storage if compact else 'layers-v1',
                'decision': 'pending', 'automatic_pass': False}
    if decode_cache:
        manifest['decode_reuse'] = decode_cache.stats
    if store:
        manifest['pixel_storage'] = store.stats
    write_json(manifest_path, manifest)
    write_json(folder / 'reviews.json', {})
    if decode_cache:
        decode_cache.commit()
    return {'manifest': str(manifest_path.relative_to(run)), 'viewer': str((folder/'index.html').relative_to(run)),
            'instances': len(rows), 'automatic_pass': False, 'next': 'Use visual-pages for native galleries; inspect playback, then visual-notes for explicit per-instance notes (or visual-review).',
            'manifest_sha256': file_hash(manifest_path),
            'identical_pixel_pages_reused': store.hits if store else 0,
            'decode_reuse': decode_cache.stats if decode_cache else {'enabled': False},
            'pixel_storage': store.stats if store else {}}


def _verify_files(folder, manifest):
    require(manifest.get('files'), 'Visual comparison evidence is empty')
    hashes = {}
    for name, sha in manifest['files'].items():
        path = inside(folder, name)
        require(path.is_file() and operation_hash(path, hashes) == sha, 'Visual comparison evidence missing or changed')


def _meaningful(text):
    return isinstance(text, str) and len(text.strip()) >= 8 and text.strip().lower() not in {
        'checked and passed', 'all checks passed', '符合要求，检查通过', '已检查，符合要求'}


def _review_valid(record, row, binding):
    require(record.get('binding_id') == object_hash(binding) and record.get('instance_id') == row['id'], 'Visual observation binding mismatch')
    require(isinstance(record.get('reviewer'), str) and record['reviewer'].strip()
            and record.get('reviewed_at') and record.get('review_type') in ('same_agent','independent','human'), 'Visual reviewer attribution missing')
    try:
        require(datetime.fromisoformat(record['reviewed_at'].replace('Z', '+00:00')).tzinfo is not None,
                'Visual review timestamp needs a timezone')
    except (ValueError, AttributeError) as exc:
        raise WorkflowError('Invalid visual review timestamp') from exc
    pages = {p['id'] for p in row['pages']}
    require(set(record.get('reviewed_pages', [])) == pages and pages, 'Visual frame review coverage is incomplete')
    require(all(_meaningful(record.get('source_appearance', {}).get(k)) for k in STYLE_KEYS), 'Source appearance observations are incomplete')
    require(_meaningful(record.get('playback_observation')), 'Actual playback/composition observation missing')
    if binding['stage'] == 'final':
        require(_meaningful(record.get('target_requirements')), 'Target appearance requirements missing')
        if row['missing_layers']:
            require(_meaningful(record.get('route_limitations')), 'Unseparated route needs explicit evidence limitations; never invent layers')
    keys = CHECKS if binding['stage'] == 'final' else CHECKS[:2]+CHECKS[3:]
    require(set(record.get('checks', {})) == set(keys), 'Visual check categories are incomplete')
    for key in keys:
        check = record['checks'][key]
        acceptable = check.get('status') == 'pass' or (key == 'erasure' and row['action'] == 'preserve' and check.get('status') == 'not_applicable')
        require(acceptable, 'Visual check is pending or failed: '+row['id']+':'+key)
        require(_meaningful(check.get('observation')), 'Concrete visual observation missing: '+key)
        evidence = check.get('evidence_pages', [])
        require(evidence and set(evidence) <= pages, 'Visual check must cite actual comparison pages')


@guarded
def review(run, manifest_relative, observation_relative):
    folder = inside(run, manifest_relative).parent
    manifest = read_json(folder / MANIFEST)
    _verify_files(folder, manifest)
    observation = read_json(inside(run, observation_relative))
    require(isinstance(observation, dict), 'Submit one instance observation, never a batch of pass decisions')
    row = next((r for r in manifest['instances'] if r['id'] == observation.get('instance_id')), None)
    require(row is not None, 'Unknown visual instance')
    # Fail/pending observations are retained too; they cannot release production.
    require(observation.get('binding_id') == object_hash(manifest['binding']), 'Stale visual observation')
    relative = 'observations/' + object_hash(observation) + '.json'
    destination = inside(folder, relative)
    if not destination.exists():
        write_json(destination, observation)
    index = read_json(folder / 'reviews.json')
    index[row['id']] = {'path': relative, 'sha256': file_hash(destination)}
    write_json(folder / 'reviews.json', index)
    try:
        _review_valid(observation, row, manifest['binding'])
        state = 'reviewed'
    except WorkflowError as exc:
        return {'instance': row['id'], 'state': 'pending_or_failed', 'reason': str(exc)}
    return {'instance': row['id'], 'state': state, 'automatic_pass': False}


def verify_bundle(folder, binding, review_index=None):
    require((folder / MANIFEST).is_file(), 'Per-instance visual audit missing; run visual-evidence')
    manifest = read_json(folder / MANIFEST)
    require(manifest['binding'] == binding, 'Visual audit is stale for this source, inventory, locale or video')
    _verify_files(folder, manifest)
    rows = manifest['instances']
    require(len(rows) == len(binding['instances']) and {r['id'] for r in rows} == {i['id'] for i in binding['instances']}, 'Visual instance coverage mismatch')
    index_path = review_index or folder / 'reviews.json'
    index = read_json(index_path)
    require(set(index) == {r['id'] for r in rows}, 'Per-instance visual observations are pending or incomplete')
    notes = []
    for row in rows:
        expected = binding['coverage'][row['id']]
        require(row['required_frames'] == expected['frames'] and row['pts'] == expected['pts']
                and row['region'] == expected['region'] and row['sampling'] == expected['sampling'], 'Required visual frame coverage was reduced')
        require([p['frame'] for p in row['pages']] == expected['frames']
                and [p['pts'] for p in row['pages']] == expected['pts']
                and all(p['id'] in manifest['files'] for p in row['pages']), 'Native comparison frame pages are missing')
        for page in row['pages']:
            needed = {layer['label'] for layer in binding['layers']
                      if layer['interval'][0] <= page['pts'] < layer['interval'][1]}
            require(set(page.get('layers', {})) == needed, 'Required source/neutral/typography/output comparison layer missing')
        reference = index[row['id']]
        path = inside(folder, reference['path'])
        require(path.is_file() and file_hash(path) == reference['sha256'], 'Visual observation missing or changed')
        record = read_json(path)
        _review_valid(record, row, binding)
        notes.append(tuple(record['checks'][key]['observation'].strip() for key in sorted(record['checks'])))
    require(len(notes) == len(set(notes)), 'Duplicated per-instance observations; batch boilerplate cannot release production')
    return {'manifest_sha256': file_hash(folder/MANIFEST), 'reviews_sha256': file_hash(index_path)}


def verify_final(run):
    binding, items, *_ = context(run, 'final')
    if not items:
        return {'scope': 'No text instances; source inventory completeness still requires review'}
    return verify_bundle(directory(run, binding), binding)


def verify_neutral(run, asset):
    binding, items, *_ = context(run, 'neutral', asset=asset)
    if not items:
        return {}
    record = read_json(inside(run, asset['record']))
    reference = record.get('text_visual_audit', {})
    require(reference.get('path') and reference.get('sha256'), 'Neutral per-instance visual audit missing; generate, review and release it')
    path = _asset(run, reference)
    frozen = _asset(run, record['text_visual_review_index'])
    live = path.parent / 'reviews.json'
    result = verify_bundle(path.parent, binding, live if live.exists() else frozen)
    require(result['reviews_sha256'] == record.get('text_visual_reviews_sha256'), 'Neutral observations changed after release')
    return result


@guarded
def release_neutral(run, shot_id):
    binding, items, inventory, *_ = context(run, 'neutral', shot_id)
    require(items, 'No text instances to release; empty observations cannot approve a neutral master')
    from .quality_holds import require_clear
    require_clear(binding['source_sha256'], binding['video_sha256'], run.parent.parent)
    folder = directory(run, binding)
    verified = verify_bundle(folder, binding)
    shot = next(s for s in inventory['shots'] if s['id'] == shot_id)
    asset = shot['prepared_video']
    record = copy.deepcopy(read_json(inside(run, asset['record'])))
    frozen_index = folder / ('review-index-'+verified['reviews_sha256'][:16]+'.json')
    selected_reviews = read_json(folder / 'reviews.json')
    write_json(frozen_index, selected_reviews)
    review_path = folder / ('neutral-review-'+verified['reviews_sha256'][:16]+'.json')
    manifest = read_json(folder / MANIFEST)
    bound_paths = {folder/MANIFEST, frozen_index}
    bound_paths.update(inside(folder, name) for name in manifest['files'])
    bound_paths.update(inside(folder, reference['path']) for reference in selected_reviews.values())
    evidence = [{'path': p.relative_to(run).as_posix(), 'sha256': file_hash(p)}
                for p in sorted(bound_paths)]
    write_json(review_path, {'source_sha256': binding['source_sha256'], 'video_sha256': binding['video_sha256'],
        'decision': 'pass', 'reviewer': 'Aggregate of individually attributed visual observations',
        'checks': {k: 'pass' for k in ('source_text_removal','texture_and_color','foreground_motion','temporal_boundaries')},
        'evidence': evidence, 'scope': 'Record gate, not independent perception or automatic visual acceptance'})
    record['inputs'] = list({r['path']: r for r in record['inputs']+evidence}.values())
    record.update(approved_for_reuse=True, visual_review={'path': review_path.relative_to(run).as_posix(), 'sha256': file_hash(review_path)},
                  text_visual_audit={'path': (folder/MANIFEST).relative_to(run).as_posix(), 'sha256': verified['manifest_sha256']},
                  text_visual_reviews_sha256=verified['reviews_sha256'],
                  text_visual_review_index={'path': frozen_index.relative_to(run).as_posix(), 'sha256': file_hash(frozen_index)})
    path = folder / ('released-preparation-'+object_hash(record)[:16]+'.json')
    write_json(path, record)
    shot['prepared_video'] = {**asset, 'record': path.relative_to(run).as_posix(), 'record_sha256': file_hash(path)}
    write_json(run / 'analysis/inventory.json', inventory)
    return {'shot': shot_id, 'asset': shot['prepared_video'], 'next': 'Rebuild plan; historical preparation records and media were not overwritten'}
