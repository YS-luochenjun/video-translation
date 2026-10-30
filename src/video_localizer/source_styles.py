"""Immutable source typography observations, explicit target choices and review.

Codex supplies observed design facts. This module never guesses a font, edits
pixels, invokes a model, or turns a static reference into motion acceptance.
"""
from __future__ import annotations

import copy
import json
import re
import shutil
from pathlib import Path

from .common import WorkflowError, file_hash, guarded, inside, object_hash, read_json, require, require_number, write_json


CHECKS = ('lettering', 'layout', 'motion', 'protected_content')
ROUTES = ('typeset', 'imagegen_asset', 'tracked_layer', 'wan_reference')


def required(run):
    path = Path(run) / 'inputs/request.json'
    return path.exists() and read_json(path).get('source_style_contract_version', 0) >= 1


def _items(inventory):
    return [i for i in inventory.get('text_instances', [])
            if i.get('action') != 'preserve' and i.get('target_text')
            and i.get('text_role') != 'publisher_mark']


def _binding(item):
    return {'source_text': item['source_text'], 'bbox': item['bbox'],
            'interval': item.get('source_interval', [item['start'], item['end']])}


def _rgb(value):
    return isinstance(value, str) and bool(re.fullmatch(r'#[0-9A-Fa-f]{6}', value))


def _validate_style(style, meta):
    require(isinstance(style, dict) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', style.get('id', '')),
            'Source style needs a stable id')
    require(style.get('observation') and isinstance(style.get('instance_ids'), list) and style['instance_ids']
            and all(isinstance(i, str) for i in style['instance_ids']), 'Source style needs actual observations and instances')
    appearance = style.get('appearance', {})
    require(appearance.get('kind') in ('plain', 'artistic'), 'Classify plain or artistic lettering from the source')
    require(appearance.get('font_class') in ('serif', 'sans', 'handwriting', 'display', 'unknown')
            and appearance.get('weight') in ('regular', 'bold', 'unknown')
            and isinstance(appearance.get('italic'), bool) and _rgb(appearance.get('color')),
            'Describe source font class, weight, italic and colour; do not invent a font filename')
    require(isinstance(appearance.get('outline_layers'), list) and isinstance(appearance.get('effects'), str)
            and appearance['effects'].strip(), 'Source style needs outline layers and observed effects (or explicit none)')
    for stroke in appearance['outline_layers']:
        require(isinstance(stroke, dict) and _rgb(stroke.get('color')), 'Invalid observed outline colour')
        require_number(stroke.get('width'), 'source outline width', maximum=meta['height'])
    layout = style.get('layout', {})
    box = layout.get('bbox', [])
    require(isinstance(box, list) and len(box) == 4, 'Source style layout needs an observed bbox')
    x, y, w, h = [require_number(v, 'style bbox') for v in box]
    require(w > 0 and h > 0 and x+w <= meta['width'] and y+h <= meta['height'], 'Source style bbox exceeds frame')
    require(type(layout.get('line_count')) is int and layout['line_count'] > 0
            and layout.get('align') in ('left', 'center', 'right'), 'Source style needs line count and alignment')
    motion = style.get('motion', {})
    require(motion.get('kind') in ('static', 'rigid', 'complex') and motion.get('observation'),
            'Describe observed motion separately from the lettering complexity')
    require(style.get('protected_content'), 'Describe adjacent protected content, or explicitly state none')


@guarded
def capture(run, relative, apply=False):
    """Extract a few ORIGINAL video frames and save an immutable design snapshot."""
    from . import media, workflow
    run = Path(run)
    source = workflow.source_path(run)
    inventory = read_json(run / 'analysis/inventory.json')
    meta = read_json(run / 'analysis/media.json')
    spec = read_json(inside(run, relative))
    require(spec.get('source_sha256') == file_hash(source) == inventory['source_sha256'], 'Source style belongs to another source')
    require(spec.get('observed_by') and spec.get('styles'), 'Source style capture needs attributed visual observations')
    items = {i['id']: i for i in _items(inventory)}
    styles, bindings, seen = [], {}, set()
    for original in spec['styles']:
        style = copy.deepcopy(original)
        _validate_style(style, meta)
        require(style['id'] not in seen, 'Duplicate source style id')
        seen.add(style['id'])
        require(len(style['instance_ids']) == len(set(style['instance_ids'])), 'Duplicate style instance id')
        for identity in style['instance_ids']:
            require(identity in items and identity not in bindings, 'Style must bind each translated source instance once')
            bindings[identity] = _binding(items[identity])
        times = style.pop('reference_times', None)
        if times is None:
            start, end = bindings[style['instance_ids'][0]]['interval']
            times = [(start+end)/2]
        require(isinstance(times, list) and 1 <= len(times) <= 3, 'Capture 1-3 representative source times per style')
        for timestamp in times:
            require_number(timestamp, 'source style reference time', maximum=meta['duration'])
            require(any(bindings[i]['interval'][0] <= timestamp < bindings[i]['interval'][1]
                        for i in style['instance_ids']), 'Style reference time is outside its source text intervals')
        style['reference_times'] = sorted({float(t) for t in times})
        styles.append(style)
    require(set(bindings) == set(items), 'Capture source styles for every translated text instance; publisher removal is separate')
    basis = {'schema_version': 1, 'source_sha256': inventory['source_sha256'],
             'canvas': {k: meta[k] for k in ('width', 'height', 'duration')},
             'observed_by': spec['observed_by'], 'styles': styles, 'source_bindings': bindings}
    identity = object_hash(basis)
    directory = run / 'analysis/source-styles' / identity
    record_path = directory / 'snapshot.json'
    if record_path.exists():
        record = read_json(record_path)
        require(record['basis'] == basis, 'Immutable source style snapshot changed')
    else:
        frames = {}
        directory.mkdir(parents=True, exist_ok=True)
        times = sorted({t for s in styles for t in s['reference_times']})
        for index, timestamp in enumerate(times):
            path = directory / 'frames' / f'{index:03d}.jpg'
            path.parent.mkdir(parents=True, exist_ok=True)
            media.ffmpeg(['-ss', timestamp, '-i', source, '-frames:v', '1', '-q:v', '2', path])
            require(path.is_file(), 'Original source style frame did not decode')
            frames[str(timestamp)] = {'path': path.relative_to(run).as_posix(), 'sha256': file_hash(path), 'time': timestamp}
        record = {'basis': basis, 'frames': frames,
                  'proof_boundary': 'Attributed source observations and original-video stills, not recovered fonts or motion/quality acceptance.'}
        write_json(record_path, record)
    pointer = {'path': record_path.relative_to(run).as_posix(), 'sha256': file_hash(record_path)}
    _snapshot(run, pointer, inventory)
    if apply:
        inventory['source_style_snapshot'] = pointer
        for style in styles:
            for item in inventory['text_instances']:
                if item['id'] in style['instance_ids']:
                    item['source_style_id'] = style['id']
        write_json(run / 'analysis/inventory.json', inventory)
    return {'snapshot': pointer, 'style_count': len(styles), 'source_frames': len(record['frames']),
            'applied': apply, 'state': 'needs_target_choices', 'new_paid_tasks': 0}


def _snapshot(run, pointer, inventory):
    path = inside(run, pointer['path'])
    require(path.is_file() and file_hash(path) == pointer['sha256'], 'Source style snapshot missing or changed')
    record = read_json(path)
    basis = record['basis']
    require(basis['source_sha256'] == inventory['source_sha256'] == read_json(run/'run.json')['source_sha256'],
            'Source style snapshot belongs to another source')
    meta = read_json(run/'analysis/media.json')
    require(basis['canvas'] == {k: meta[k] for k in ('width', 'height', 'duration')}, 'Source style canvas or duration changed')
    require(path.parent.name == object_hash(basis), 'Source style snapshot identity changed')
    for style in basis['styles']:
        _validate_style(style, meta)
        for timestamp in style['reference_times']:
            require(str(timestamp) in record['frames'], 'Missing required source style frame')
    for asset in record['frames'].values():
        frame = inside(run, asset['path'])
        require(frame.is_file() and file_hash(frame) == asset['sha256'], 'Source style reference frame missing or changed')
    require(basis['source_bindings'] == {i['id']: _binding(i) for i in _items(inventory)},
            'Source text/geometry changed; capture a new style snapshot instead of overwriting the old one')
    return record


@guarded
def reuse(run, source_run):
    """Copy an independently verified exact-source snapshot, without target choices."""
    from .workflow import source_path
    source_path(run)
    source_path(source_run)
    inventory = read_json(run/'analysis/inventory.json')
    source_inventory = read_json(source_run/'analysis/inventory.json')
    pointer = source_inventory.get('source_style_snapshot')
    require(pointer, 'Source run has no captured typography snapshot')
    record = _snapshot(source_run, pointer, source_inventory)
    require(inventory['source_sha256'] == record['basis']['source_sha256']
            and {i['id']: _binding(i) for i in _items(inventory)} == record['basis']['source_bindings'],
            'Style reuse requires exact source text instances/geometry; target language is reviewed separately')
    for asset in [pointer, *record['frames'].values()]:
        dest = inside(run, asset['path'])
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            require(file_hash(dest) == asset['sha256'], 'Existing target style asset differs; do not overwrite it')
        else:
            shutil.copyfile(inside(source_run, asset['path']), dest)
    _snapshot(run, pointer, inventory)
    inventory['source_style_snapshot'] = copy.deepcopy(pointer)
    for style in record['basis']['styles']:
        for item in inventory['text_instances']:
            if item['id'] in style['instance_ids']:
                item['source_style_id'] = style['id']
                item.pop('style_treatment', None)
    write_json(run/'analysis/inventory.json', inventory)
    return {'snapshot': pointer, 'state': 'needs_target_choices', 'target_approval_inherited': False}


def contract(run, inventory):
    pointer = inventory.get('source_style_snapshot')
    items = _items(inventory)
    if not pointer and not required(run):
        return None  # Old requests keep their historical contract.
    if not items:
        return None
    require(pointer, 'Capture source typography before erasure/planning: style-capture RUN SPEC --apply')
    record = _snapshot(run, pointer, inventory)
    styles = {s['id']: s for s in record['basis']['styles']}
    assets, choices = [pointer, *record['frames'].values()], {}
    for item in items:
        identity = item.get('source_style_id')
        require(identity in styles and item['id'] in styles[identity]['instance_ids'], 'Text instance needs its actual source style id')
        choice = item.get('style_treatment', {})
        require(choice.get('route') in ROUTES and choice.get('reason') and isinstance(choice.get('adaptations'), dict),
                'Choose a typography route and explain target-language adaptations')
        require(all(isinstance(k, str) and isinstance(v, str) and v.strip() for k, v in choice['adaptations'].items()),
                'Every typography adaptation needs a concrete reason')
        style, display = styles[identity], item.get('display', {})
        require(all(isinstance(display.get(k, default), bool) for k, default in [('bold', True), ('italic', False)]),
                'Target font weight/italic flags must be explicit booleans')
        require(all(_rgb(display[k]) for k in ('color', 'outline_color', 'shadow_color') if k in display),
                'Target typography colours must be RGB values')
        if choice['route'] == 'typeset':
            require(not display.get('pill') and not display.get('reveal_seconds'),
                    'Pill/per-character reveal needs a supported motion or bound surface route, not silent static typesetting')
            require(style['motion']['kind'] == 'static' or style['motion']['kind'] == 'rigid'
                    and (display.get('motion') or item.get('trajectory')) or choice['adaptations'].get('motion'),
                    'Moving source text needs a tracked route or an explicit motion downgrade')
            require(choice.get('font_choice_reason'),
                    'Explain the real font choice and observed effects, or select ImageGen for unsupported art')
            asset = display.get('font_asset')
            require(asset, 'Source-style typesetting needs a real hash-bound font_asset, not a default font')
            from .fonts import inspect_asset
            inspect_asset(run, asset, item['target_text'], display.get('bold', True), display.get('italic', False))
            assets.append(asset)
            appearance = style['appearance']
            target_outlines = list(display.get('outline_layers', []))
            if display.get('outline', 2):
                target_outlines.append({'width':display.get('outline',2),'color':display.get('outline_color','#111111')})
            def outlines(rows):
                values = [(r['width'],r['color'].lower()) for r in rows if r['width'] > 0]
                return [v for index,v in enumerate(values) if not index or v != values[index-1]]
            differences = {'color': display.get('color', '#FFFFFF').lower() != appearance['color'].lower(),
                           'italic': display.get('italic', False) != appearance['italic'],
                           'weight': appearance['weight'] != 'unknown' and display.get('bold', True) != (appearance['weight'] == 'bold'),
                           'line_count': len(item['target_text'].split('\n')) != style['layout']['line_count'],
                           'outlines': outlines(target_outlines) != outlines(appearance['outline_layers']),
                           'layout': display.get('bbox',item['bbox']) != item['bbox'],
                           'align': display.get('align', 'center') != style['layout']['align']}
            require(all(not changed or choice['adaptations'].get(key) for key, changed in differences.items()),
                    'Source colour/italic/weight/line-count/outlines/alignment changed without an explained adaptation')
        elif choice['route'] in ('imagegen_asset', 'tracked_layer'):
            require(display.get('typography_layer'), 'Artistic/tracked assets need the existing bound surface typography layer')
            shots = [s for s in inventory.get('shots', []) if item['start'] < s['end'] and item['end'] > s['start']]
            require(shots and all(s.get('surface_typography') for s in shots),
                    'Bind the actual artistic/tracked layer to every covered shot; a route label is not execution')
            from .surface import verify
            for shot in shots:
                verify(run, shot['surface_typography'], inventory['source_sha256'],
                       read_json(run/'inputs/request.json')['target_language'],
                       [i for i in inventory['text_instances'] if i['start'] < shot['end'] and i['end'] > shot['start']])
        else:
            shots = [s for s in inventory.get('shots', []) if item['start'] < s['end'] and item['end'] > s['start']]
            require(item['action'] in ('model_edit', 'regenerate') and shots and all(s.get('reference_image') for s in shots),
                    'Wan typography reference route requires an actual same-shot reference image')
            for shot in shots:
                asset = shot['reference_image']
                path = inside(run, asset['path'])
                require(path.is_file() and file_hash(path) == asset.get('sha256'), 'Wan style reference missing or changed')
        choices[item['id']] = {'source_style_id': identity, 'treatment': choice,
                               'target_text': item['target_text'], 'display': display}
    return {'version': 1, 'snapshot': pointer, 'instances': choices,
            'assets': list({a['path']: {'path': a['path'], 'sha256': a['sha256']} for a in assets}.values())}


def verify_contract(run, plan, inventory):
    require(plan.get('source_style_contract') == contract(run, inventory), 'Source typography changed; rebuild/register the plan')


def status(run, inventory):
    if not required(run) and not inventory.get('source_style_snapshot'):
        return {'state': 'legacy_not_required', 'required': False, 'blockers': []}
    try:
        value = contract(run, inventory)
        return {'state': 'ready_for_planning', 'required': True,
                'snapshot': inventory.get('source_style_snapshot'), 'instances': len((value or {}).get('instances', {})),
                'blockers': []}
    except WorkflowError as exc:
        return {'state': 'needs_target_choices' if inventory.get('source_style_snapshot') else 'needs_source_capture',
                'required': True, 'blockers': [str(exc)]}


def validate_routes(run, inventory, segments):
    if not inventory.get('source_style_snapshot'):
        return
    for segment in segments:
        for item in _items(inventory):
            if item['id'] not in segment['instance_ids']:
                continue
            route = item['style_treatment']['route']
            if route == 'typeset' and item['action'] != 'solid_overlay':
                require(segment['route'] in ('prepared_video', 'reference_composite')
                        or segment.get('model_text_mode') == 'erase_then_overlay',
                        'Typeset source style requires a clean-master/erase-then-overlay route')
            if route == 'wan_reference':
                require(segment['route'] == 'wan_edit' and segment.get('model_text_mode', 'replace') == 'replace',
                        'Wan target typography reference cannot be used as an erase-only pass')


def prompt_lines(run, inventory, items):
    pointer = inventory.get('source_style_snapshot')
    if not pointer:
        return []
    record = read_json(inside(run, pointer['path']))
    styles = {s['id']: s for s in record['basis']['styles']}
    result = []
    for item in items:
        if item.get('source_style_id') not in styles:
            continue
        style = styles[item['source_style_id']]
        facts = {k: style[k] for k in ('appearance', 'layout', 'motion')}
        result.append(f"Source typography for {item['id']} (observations, not font-file recovery): "
                      + json.dumps(facts, ensure_ascii=False, separators=(',', ':'))
                      + '. Preserve its visual hierarchy; target-language adaptations: '
                      + json.dumps(item['style_treatment']['adaptations'], ensure_ascii=False))
    return result


def review_template(inventory):
    return [{'instance_id': i['id'], 'source_style_id': i.get('source_style_id'),
             'checks': {k: {'status': 'pending', 'observation': ''} for k in CHECKS}, 'evidence': []}
            for i in _items(inventory)] if inventory.get('source_style_snapshot') else []


def review_failures(run, inventory, review, candidate):
    if not inventory.get('source_style_snapshot') and not required(run):
        return []
    items = _items(inventory)
    if not items:
        return []
    failures = []
    rows = review.get('source_style_review', [])
    if not isinstance(rows, list) or len(rows) != len(items) or {r.get('instance_id') for r in rows if isinstance(r, dict)} != {i['id'] for i in items}:
        return ['source_style_review_coverage_missing']
    captured_path = run/'review/capture.json'
    captured = read_json(captured_path) if captured_path.exists() else {}
    if captured.get('video_sha256') != candidate['sha256']:
        failures.append('source_style_current_video_capture_missing')
    for row in rows:
        item = next(i for i in items if i['id'] == row['instance_id'])
        if row.get('source_style_id') != item.get('source_style_id'):
            failures.append('source_style_review_binding_changed:' + item['id'])
        for key in CHECKS:
            check = row.get('checks', {}).get(key, {})
            if check.get('status') not in ('pass', 'minor') or not check.get('observation'):
                failures.append('source_style_' + key + '_unreviewed_or_failed:' + item['id'])
        if not row.get('evidence'):
            failures.append('source_style_result_evidence_missing:' + item['id'])
        for asset in row.get('evidence', []):
            path = inside(run, asset['path'])
            if (path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp')
                    or not path.is_file() or file_hash(path) != asset.get('sha256')
                    or captured.get('files', {}).get(asset['path']) != asset.get('sha256')):
                failures.append('source_style_result_evidence_changed:' + item['id'])
    return failures
