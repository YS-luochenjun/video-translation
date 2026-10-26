"""Explicit basic-quality delivery using hash-bound recipes and one compact review.

This route removes redundant paperwork, not actual audiovisual observations.
Existing strict candidates retain their original workflow and acceptance contract.
"""
from pathlib import Path
import shutil

from .common import ROOT, file_hash, guarded, inside, object_hash, read_json, require, utc_now, write_json
from . import media, timing


def _freeze_knowledge(run, plan):
    directory = run / 'plans' / plan['id']
    frozen = directory / 'plan.json'
    if frozen.exists():
        require(read_json(frozen) == plan, 'Frozen fast plan changed')
    else:
        write_json(frozen, plan)
    for group in ('knowledge', 'source_references', 'knowledge_advisories'):
        for index, entry in enumerate(plan[group]):
            source = inside(run.parent.parent, entry.get('storage_path', entry['path']))
            require(file_hash(source) == entry['sha256'], 'Selected knowledge changed during fast registration')
            target = directory / group / f'{index+1:02d}.md'
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            require(file_hash(target) == entry['sha256'], 'Frozen knowledge changed')
    for name, relative in (('request.json', 'inputs/request.json'), ('inventory.json', 'analysis/inventory.json')):
        target = directory / 'inputs' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copyfile(run / relative, target)
        require(file_hash(target) == file_hash(run / relative), 'Frozen fast input changed')


def policy(root=ROOT):
    return read_json(Path(root) / 'config/fast-delivery.json')


def validate_plan(run, plan):
    require(plan['id'] == object_hash({k: v for k, v in plan.items() if k != 'id'})[:16], 'Fast plan changed')
    for key, relative in [('request_sha256', 'inputs/request.json'),
                          ('inventory_sha256', 'analysis/inventory.json')]:
        require(file_hash(run / relative) == plan[key], 'Fast inputs changed; register the new recipe/output')
    require(read_json(run / 'inputs/request.json').get('delivery_mode') == 'fast', 'Fast scope is not selected')
    root = run.parent.parent
    require(file_hash(root / 'config/fast-delivery.json') == plan['policy_sha256'], 'Fast policy changed')
    for asset in plan['assets']:
        require(file_hash(inside(run, asset['path'])) == asset['sha256'], 'Fast recipe dependency changed')
    from .workflow import source_path
    require(file_hash(source_path(run)) == plan['source_sha256'], 'Source changed')
    if plan.get('knowledge_snapshot_version') == 1:
        directory = run / 'plans' / plan['id']
        require(read_json(directory / 'plan.json') == plan, 'Frozen fast plan changed')
        for name, key in (('request.json', 'request_sha256'), ('inventory.json', 'inventory_sha256')):
            require(file_hash(directory / 'inputs' / name) == plan[key], 'Frozen fast input changed')
        for group in ('knowledge', 'source_references', 'knowledge_advisories'):
            for index, entry in enumerate(plan[group]):
                require(file_hash(directory / group / f'{index+1:02d}.md') == entry['sha256'], 'Frozen knowledge changed')
    else:
        require(not read_json(run / 'inputs/request.json').get('routing_contract_version'),
                'Register the fast recipe with routing and frozen knowledge before continuing')
    return plan


@guarded
def register(run, recipe_relative):
    """Freeze a completed local composition. Registration never supplies a pass."""
    from .workflow import source_path
    require(read_json(run / 'inputs/request.json').get('delivery_mode') == 'fast', 'Select fast mode explicitly')
    recipe_path = inside(run, recipe_relative)
    recipe = read_json(recipe_path)
    require(recipe['source_sha256'] == file_hash(source_path(run)), 'Recipe source mismatch')
    output = recipe['output']
    require(file_hash(inside(run, output['path'])) == output['sha256'], 'Recipe output changed')
    require(recipe.get('native_frame_mapping') is True, 'Fast composition must preserve source frame timing')
    from .knowledge import context_for, retrieve, source_references
    from .knowledge_advisories import retrieve as advisories
    from .routing import validate as validate_routing
    root = run.parent.parent
    request = read_json(run / 'inputs/request.json')
    inventory = read_json(run / 'analysis/inventory.json')
    meta_path = run / 'analysis/media.json'
    if request.get('routing_contract_version', 0) >= 1:
        from .contracts import validate_inventory
        require(meta_path.is_file(), 'Analyze the source before fast registration')
        validate_inventory(inventory, run, read_json(meta_path))
    context = context_for(request, inventory, root)
    knowledge = retrieve(context, root=root)
    references = source_references(context, root=root)
    assessment = validate_routing(inventory, request, run, knowledge + references,
                                  read_json(meta_path)['duration'] if meta_path.exists() else None)
    assets = [{'path': recipe_relative, 'sha256': file_hash(recipe_path)}, *recipe['assets']]
    plan = {'mode': 'fast', 'source_sha256': recipe['source_sha256'],
            'request_sha256': file_hash(run / 'inputs/request.json'),
            'inventory_sha256': file_hash(run / 'analysis/inventory.json'),
            'policy_sha256': file_hash(run.parent.parent / 'config/fast-delivery.json'),
            'knowledge_snapshot_version': 1, 'knowledge_context': context,
            'knowledge': knowledge, 'source_references': references,
            'knowledge_advisories': advisories(context, root), 'routing_assessment': assessment,
            'assets': assets, 'segments': [], 'audio_assets': recipe.get('audio_assets', [])}
    if request.get('routing_contract_version', 0) >= 1:
        from .captions import contract
        plan['caption_contract'] = contract(inventory)
    plan['id'] = object_hash(plan)[:16]
    _freeze_knowledge(run, plan)
    validate_plan(run, plan)
    write_json(run / 'plan.json', plan)
    write_json(run / 'outputs/candidate.json', {**output, 'mode': 'fast', 'plan_id': plan['id'],
               'inventory_sha256': plan['inventory_sha256'], 'recipe': recipe_relative})
    checks = {key: {'decision': 'pending', 'observation': '', 'evidence': []}
              for key in policy(run.parent.parent)['review_checks']}
    template = {'video_sha256': output['sha256'], 'plan_id': plan['id'], 'reviewer': '', 'method': '',
                'covered_text_ids': [], 'covered_speech_ids': [], 'checks': checks, 'known_variations': [],
                'visual_finish': {'score': None, 'normal_speed_observation': '', 'evidence': [], 'defects': []}}
    write_json(run / 'review/fast-template.json', template)
    write_json(run / 'outputs/reuse-assets.json', {'source_sha256': plan['source_sha256'], 'assets': assets})
    return {'state': 'needs_review', 'template': 'review/fast-template.json', 'plan_id': plan['id']}


def review_failures(review, candidate, inventory, run, checks):
    failures = []
    if review.get('video_sha256') != candidate['sha256'] or review.get('plan_id') != candidate['plan_id']:
        failures.append('review_binding_changed')
    if not review.get('reviewer') or not review.get('method'):
        failures.append('review_attribution_missing')
    for key, collection in [('text', 'text_instances'), ('speech', 'speech_segments')]:
        required = {item['id'] for item in inventory.get(collection, [])}
        if set(review.get('covered_' + key + '_ids', [])) != required:
            failures.append(key + '_coverage_missing')
    for name in checks:
        row = review.get('checks', {}).get(name, {})
        if row.get('decision') != 'pass' or not row.get('observation') or not row.get('evidence'):
            failures.append(name + '_unreviewed')
            continue
        for item in row['evidence']:
            path = inside(run, item['path'])
            if not path.is_file() or file_hash(path) != item.get('sha256'):
                failures.append(name + '_evidence_changed')
    return failures


def visual_finish_failures(review, run, acceptance):
    """Permit documented minor cosmetic flaws without waiving content/motion checks."""
    if not acceptance:
        return []
    row = review.get('visual_finish', {})
    score = row.get('score')
    failures = []
    if (type(score) not in (int, float) or not acceptance['minimum_score'] <= score <= acceptance['scale']):
        failures.append('visual_finish_below_threshold_or_unreviewed')
    if not row.get('normal_speed_observation') or not row.get('evidence'):
        failures.append('visual_finish_playback_unreviewed')
    for asset in row.get('evidence', []):
        path = inside(run, asset['path'])
        if not path.is_file() or file_hash(path) != asset.get('sha256'):
            failures.append('visual_finish_evidence_changed')
    defects = row.get('defects')
    if not isinstance(defects, list):
        failures.append('visual_finish_defects_unreviewed')
        return failures
    for defect in defects:
        if (not isinstance(defect, dict) or defect.get('severity') not in acceptance['allowed_severities']
                or not defect.get('observation') or not defect.get('time_range')):
            failures.append('visual_finish_blocking_or_unspecified_defect')
    return failures


@guarded
def quality(run):
    plan = validate_plan(run, read_json(run / 'plan.json'))
    candidate = read_json(run / 'outputs/candidate.json')
    video = inside(run, candidate['path'])
    require(candidate['plan_id'] == plan['id'] and file_hash(video) == candidate['sha256'], 'Candidate changed')
    recipe = read_json(inside(run, candidate['recipe']))
    require(recipe['output'] == {'path': candidate['path'], 'sha256': candidate['sha256']}, 'Candidate is not the frozen recipe output')
    from .quality_holds import require_clear
    require_clear(plan['source_sha256'], candidate['sha256'], run.parent.parent)
    review_path = run / 'review/fast-review.json'
    review = read_json(review_path) if review_path.exists() else {}
    if review_path.exists():
        # Canonical review consumed by the existing status/learning interfaces.
        shutil.copyfile(review_path, run / 'review/review.json')
    inv = read_json(run / 'analysis/inventory.json')
    failures = review_failures(review, candidate, inv, run, policy(run.parent.parent)['review_checks'])
    failures.extend(visual_finish_failures(review, run, policy(run.parent.parent).get('visual_acceptance')))
    failures.extend('recipe_unresolved:' + str(reason) for reason in recipe.get('known_failures', []))
    # Reuse the full decode only when the actual bytes and decoder are unchanged.
    check_path = run / 'outputs/fast-technical.json'
    cached = read_json(check_path) if check_path.exists() else {}
    signature = object_hash({'video': candidate['sha256'], 'source': plan['source_sha256'],
                             'code': file_hash(Path(__file__)),
                             'audio_code': file_hash(Path(__file__).with_name('audio.py')),
                             'audio_policy': inv.get('audio', {}),
                             'decoder': media.command(['ffmpeg', '-version']).stdout})
    if cached.get('signature') != signature:
        from .workflow import source_path
        with timing.measure(run, 'fast.technical_decode'):
            source, actual = media.probe(source_path(run)), media.probe(video)
            media.command(['ffmpeg', '-v', 'error', '-xerror', '-i', video, '-f', 'null', '-'])
            errors = []
            if abs(actual['duration'] - source['duration']) > .1: errors.append('duration_changed')
            if (source['width'], source['height']) != (actual['width'], actual['height']): errors.append('dimensions_changed')
            if abs(source['fps'] - actual['fps']) > .001: errors.append('frame_rate_changed')
            import json
            counts = []
            for path in (source_path(run), video):
                counted = json.loads(media.command(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0',
                    '-show_entries', 'stream=nb_read_frames', '-of', 'json', path]).stdout)
                counts.append(int(counted['streams'][0]['nb_read_frames']))
            if counts[0] != counts[1]: errors.append('frame_count_changed')
            from .audio import evaluate
            audio = evaluate(source_path(run), video, inv.get('audio') or {'strategy': 'preserve'}, source['duration'])
            errors.extend(audio['failures'])
            cached = {'signature': signature, 'source': source, 'actual': actual, 'frame_counts': counts, 'audio': audio, 'failures': errors}
            write_json(check_path, cached)
    failures.extend(cached['failures'])
    result = {'decision': 'pass' if not failures else 'revise', 'scope': 'fast-basic',
              'video_sha256': candidate['sha256'], 'plan_id': plan['id'], 'failures': failures,
              'review_sha256': file_hash(review_path) if review_path.exists() else None,
              'independent_review': False, 'user_acceptance': False,
              'boundary': policy(run.parent.parent)['boundary']}
    write_json(run / 'outputs/quality.json', result)
    return result


@guarded
def deliver(run):
    if (run / 'review/finalization.json').exists():
        from .finalization import finish
        return finish(run)
    result = quality(run)
    if result['decision'] != 'pass':
        return {'state': 'needs_finalization', 'quality': result,
                'next_action': 'End bounded retries, compose the best complete translation and fill review/finalization.json, then finalize. Do not end the user task without a video.',
                'workflow': 'agent/workflows/always-output.md'}
    candidate = read_json(run / 'outputs/candidate.json')
    with timing.measure(run, 'fast.delivery_archive'):
        shutil.copyfile(inside(run, candidate['path']), run / 'outputs/final.mp4')
        write_json(run / 'outputs/delivery.json', {'video': 'outputs/final.mp4', 'sha256': candidate['sha256'],
                   'quality_record': 'outputs/quality.json', 'quality_sha256': file_hash(run / 'outputs/quality.json'),
                   'scope': 'fast-basic', 'delivered_at': utc_now(), 'plan_id': candidate['plan_id']})
        from .library import export
        archived = export(run, root=run.parent.parent)
        queue = run.parent.parent / 'state/deferred-delivery' / (run.name + '.json')
        write_json(queue, {'run': run.name, 'video_sha256': candidate['sha256'], 'status': 'pending',
                          'tasks': ['reflect', 'source-save'], 'created_at': utc_now(),
                          'boundary': 'Durable maintenance queue; no background execution or completion implied'})
    return {'final': archived['package'] + '/final.mp4', 'scope': 'fast-basic',
            'sha256': candidate['sha256'], 'deferred_maintenance': str(queue), 'package': archived}
