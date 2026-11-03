"""Read-only timing design diagnostics; no generated media or automatic AV pass.

Source visibility controls erasure/scene events; actual target speech controls
spoken captions. Keep these clocks separate, and expose conflicts on resume.
"""
from __future__ import annotations

import math
from pathlib import Path

from . import captions
from .common import WorkflowError, file_hash, inside, object_hash, read_json
from .layout import overlaps


def _interval(value):
    return (isinstance(value, (list, tuple)) and len(value) == 2
            and all(type(n) in (int, float) and math.isfinite(n) for n in value)
            and 0 <= value[0] < value[1])


def _box(value):
    return (isinstance(value, (list, tuple)) and len(value) == 4
            and all(type(n) in (int, float) and math.isfinite(n) for n in value)
            and value[2] > 0 and value[3] > 0)


def design(inventory, source_bindings=None, source_styles=None):
    """Inspect declared timelines, never infer timing or motion from lettering."""
    bindings, styles = source_bindings or {}, source_styles or {}
    rows, risks, active = [], [], []
    for item in inventory.get('text_instances', []):
        if item.get('action') == 'preserve' or not item.get('target_text'):
            continue
        identity, role = item['id'], item.get('text_role')
        frozen = bindings.get(identity, {}).get('interval')
        source = frozen or item.get('source_interval')
        try:
            target_units = captions.units(item)
        except (KeyError, TypeError, ValueError):
            target_units = []
            risks.append({'kind': 'invalid_target_units', 'ids': [identity]})
        row = {'id': identity, 'role': role, 'source_interval': source,
               'source_timing_basis': 'frozen_source_observation' if frozen else
                                      'declared_erase_window' if source else 'missing',
               'clock': 'actual_target_speech' if role == 'speech_caption' else 'source_scene_event',
               'target_units': target_units, 'review_questions': []}
        rows.append(row)
        def flag(kind, **details):
            risks.append({'kind': kind, 'ids': [identity], **details})
        valid = []
        for unit in row['target_units']:
            if not _interval([unit.get('start'), unit.get('end')]):
                flag('invalid_target_interval')
            else:
                valid.append(unit)
        if source is not None and not _interval(source):
            flag('invalid_source_interval')
        if role == 'speech_caption':
            row['review_questions'] = ['Compare each phrase with actual final mixed speech, not source English times.',
                'Inspect before entry and after exit; check unreadable pops, overlaps and cut boundaries.']
            if not item.get('display', {}).get('timed_fragments'):
                flag('spoken_caption_without_aligned_fragments')
            if any(b['start'] < a['end'] - .001 for a, b in zip(valid, valid[1:])):
                flag('spoken_fragments_overlap_or_unordered')
            row['source_erase_window_is_not_target_display'] = True
        elif role == 'scene_text':
            row['review_questions'] = ['Check appearance/disappearance against the original scene event, not narration.',
                'Preserve the observed reveal/emphasis/exit; do not add motion to an originally static title.']
            if not _interval(source):
                flag('scene_source_timing_unfrozen')
            elif valid:
                target = [min(u['start'] for u in valid), max(u['end'] for u in valid)]
                reason = item.get('style_treatment', {}).get('adaptations', {}).get('timing')
                if any(abs(a-b) > .001 for a, b in zip(source, target)) and not reason:
                    flag('scene_event_timing_changed_without_reason', source_interval=source, target_interval=target)
        else:
            flag('text_role_needs_classification')
        motion = styles.get(item.get('source_style_id'), {}).get('motion', {})
        row['observed_source_motion'] = motion
        if motion.get('kind') in ('rigid', 'complex'):
            row['review_questions'].append('Inspect actual continuous motion; still artwork is not motion completion.')
            choice = item.get('style_treatment', {})
            supported = (item.get('display', {}).get('motion') or item.get('trajectory')
                         or choice.get('route') in ('tracked_layer', 'wan_reference'))
            if not supported and not choice.get('adaptations', {}).get('motion'):
                flag('source_motion_has_no_target_treatment')
        box = item.get('display', {}).get('bbox', item.get('bbox'))
        if _box(box):
            for unit in valid:
                active.append({'id': identity, 'box': box, 'start': unit['start'], 'end': unit['end'],
                               'moving': bool(item.get('trajectory') or item.get('display', {}).get('motion'))})
    # Sweep actual display fragments, not the longer source-erasure windows.
    pairs = {}
    live = []
    for current in sorted(active, key=lambda u: u['start']):
        live = [u for u in live if u['end'] > current['start'] + .001]
        for other in live:
            if other['id'] == current['id'] or not overlaps(other['box'], current['box']):
                continue
            ids = tuple(sorted((other['id'], current['id'])))
            pair = pairs.setdefault(ids, {'kind': 'simultaneous_text_regions_need_review', 'ids': list(ids),
                'intervals': [], 'moving_geometry': False,
                'scope': 'Declared regions may overlap; inspect actual pixels. This is not a proven visual collision.'})
            pair['intervals'].append([max(other['start'], current['start']), min(other['end'], current['end'])])
            pair['moving_geometry'] |= current['moving'] or other['moving']
        live.append(current)
    risks.extend(pairs.values())
    return {'schema_version': 1, 'instances': rows, 'risks': risks,
            'automatic_pass': False, 'paid_calls': 0,
            'next_action': 'Resolve timing design risks, then inspect current encoded video/audio and caption-check. '
                           'Keep bounded best-available output/submission policy; diagnostics do not block delivery.',
            'proof_boundary': 'Inventory and bound source/alignment diagnostics only. No OCR, listening, motion or quality approval.'}


def diagnose(run, inventory=None):
    run = Path(run)
    inventory = inventory if inventory is not None else read_json(run/'analysis/inventory.json')
    bindings, styles, errors = {}, {}, []
    pointer = inventory.get('source_style_snapshot')
    if pointer:
        try:
            path = inside(run, pointer['path'])
            record = read_json(path)
            basis = record['basis']
            if (file_hash(path) != pointer['sha256'] or basis['source_sha256'] != inventory['source_sha256']
                    or path.parent.name != object_hash(basis)):
                raise WorkflowError('Source timing snapshot missing, changed or belongs to another source')
            if not isinstance(basis.get('source_bindings'), dict) or not isinstance(basis.get('styles'), list):
                raise WorkflowError('Source timing snapshot has no instance bindings/styles')
            bindings = basis['source_bindings']
            styles = {s['id']: s for s in basis['styles']}
        except (WorkflowError, OSError, ValueError, KeyError, TypeError):
            errors.append({'kind': 'source_timing_snapshot_unverified', 'ids': []})
    result = design(inventory, bindings, styles)
    if any(r['role'] == 'speech_caption' for r in result['instances']):
        asset = inventory.get('caption_alignment')
        try:
            if not asset:
                raise WorkflowError('Actual mixed-audio alignment record is missing')
            path = inside(run, asset['path'])
            if file_hash(path) != asset['sha256']:
                raise WorkflowError('Caption alignment record changed')
            compiled = captions.compile_alignment(run, inventory, read_json(path),
                                                  read_json(run/'analysis/media.json')['duration'])
            result['alignment_record'] = asset
            for item in inventory.get('text_instances', []):
                if item['id'] in compiled and item.get('display', {}).get('timed_fragments') != compiled[item['id']]:
                    errors.append({'kind': 'target_timing_differs_from_reviewed_alignment', 'ids': [item['id']]})
        except (WorkflowError, OSError, ValueError, KeyError, TypeError):
            errors.append({'kind': 'actual_target_audio_alignment_unverified', 'ids': [],
                           'next_action': 'Bind/review the selected final mix and apply captions alignment; do not copy source timing.'})
    result['risks'].extend(errors)
    result['risk_count'] = len(result['risks'])
    result['inventory_object_sha256'] = object_hash(inventory)
    result['run'] = run.name
    return result
