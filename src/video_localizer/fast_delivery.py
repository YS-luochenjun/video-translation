"""Explicit basic-quality delivery using hash-bound recipes and one compact review.

This route removes redundant paperwork, not actual audiovisual observations.
Existing strict candidates retain their original workflow and acceptance contract.
"""
from pathlib import Path
from .text_restoration import review_template as restoration_review_template
import shutil

from .common import ROOT, file_hash, guarded, inside, object_hash, read_json, require, utc_now, write_json
from . import media, timing


def _freeze_knowledge(run, plan):
    from .plan_inputs import freeze
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
        freeze(run, plan['id'], name, run / relative)


def policy(root=ROOT):
    return read_json(Path(root) / 'config/fast-delivery.json')


def revision_status(run, output_sha256=None):
    root = run.parent.parent
    settings_path = root / 'config/workspace.json'
    settings = read_json(settings_path) if settings_path.exists() else read_json(ROOT / 'config/workspace.json')
    maximum = 1 + settings['max_revision_rounds']
    versions = set()
    for path in (run / 'plans').glob('*/plan.json'):
        plan = read_json(path)
        digest = plan.get('output_sha256')
        if plan.get('mode') == 'fast' and not digest:
            assets = plan.get('assets', [])
            if assets:
                recipe = inside(run, assets[0]['path'])
                if recipe.is_file() and file_hash(recipe) == assets[0]['sha256']:
                    digest = read_json(recipe).get('output', {}).get('sha256')
        versions.add(digest or 'unverified:' + path.parent.name)
    return {'registered_versions': len(versions), 'maximum_versions': maximum,
            'remaining_full_revisions': max(0, maximum - len(versions)),
            'can_register': output_sha256 in versions or len(versions) < maximum}


def validate_plan(run, plan):
    require(plan['id'] == object_hash({k: v for k, v in plan.items() if k != 'id'})[:16], 'Fast plan changed')
    for key, relative in [('request_sha256', 'inputs/request.json'),
                          ('inventory_sha256', 'analysis/inventory.json')]:
        require(file_hash(run / relative) == plan[key], 'Fast inputs changed; register the new recipe/output')
    request = read_json(run / 'inputs/request.json')
    require(request.get('delivery_mode') == 'fast', 'Fast scope is not selected')
    inventory = read_json(run / 'analysis/inventory.json')
    from .text_restoration import validate as validate_text_restoration
    validate_text_restoration(run, inventory)
    root = run.parent.parent
    require(file_hash(root / 'config/fast-delivery.json') == plan['policy_sha256'], 'Fast policy changed')
    for asset in plan['assets']:
        require(file_hash(inside(run, asset['path'])) == asset['sha256'], 'Fast recipe dependency changed')
    if plan.get('restoration_probe_contract') == 1:
        from .restoration_probes import validate_base
        validate_base(run, plan.get('restoration_base'), plan['assets'])
    from .source_styles import verify_contract as verify_style_contract
    verify_style_contract(run, plan, inventory)
    from .workflow import verified_source
    require(verified_source(run)[1] == plan['source_sha256'], 'Source changed')
    from .typography import verify_contract, verify_receipt
    verify_contract(run, plan, inventory)
    for asset in plan.get('typography_assets', []):
        verify_receipt(run, asset)
    from .typography import verify_assets
    verify_assets(run,plan.get('typography_assets',[]),inventory)
    if plan.get('knowledge_snapshot_version') == 1:
        directory = run / 'plans' / plan['id']
        require(read_json(directory / 'plan.json') == plan, 'Frozen fast plan changed')
        for name, key in (('request.json', 'request_sha256'), ('inventory.json', 'inventory_sha256')):
            require(file_hash(directory / 'inputs' / name) == plan[key], 'Frozen fast input changed')
        for group in ('knowledge', 'source_references', 'knowledge_advisories'):
            for index, entry in enumerate(plan[group]):
                require(file_hash(directory / group / f'{index+1:02d}.md') == entry['sha256'], 'Frozen knowledge changed')
    else:
        require(not request.get('routing_contract_version'),
                'Register the fast recipe with routing and frozen knowledge before continuing')
    return plan


@guarded
def register(run, recipe_relative):
    """Freeze a completed local composition. Registration never supplies a pass."""
    from .workflow import source_path
    from .batches import gate
    gate(run)
    require(read_json(run / 'inputs/request.json').get('delivery_mode') == 'fast', 'Select fast mode explicitly')
    recipe_path = inside(run, recipe_relative)
    recipe = read_json(recipe_path)
    require(recipe['source_sha256'] == file_hash(source_path(run)), 'Recipe source mismatch')
    output = recipe['output']
    require(file_hash(inside(run, output['path'])) == output['sha256'], 'Recipe output changed')
    require(revision_status(run, output['sha256'])['can_register'],
            'Full revision budget reached; finalize the best complete version and record any publication blocker')
    require(recipe.get('native_frame_mapping') is True, 'Fast composition must preserve source frame timing')
    from .knowledge import context_for, retrieve, source_references
    from .knowledge_advisories import retrieve as advisories
    from .routing import validate as validate_routing
    root = run.parent.parent
    request = read_json(run / 'inputs/request.json')
    inventory = read_json(run / 'analysis/inventory.json')
    from .contracts import validate_publisher_marks
    validate_publisher_marks(inventory, run)
    from .text_restoration import validate as validate_text_restoration
    validate_text_restoration(run, inventory)
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
    plan = {'mode': 'fast', 'source_sha256': recipe['source_sha256'], 'output_sha256': output['sha256'],
            'request_sha256': file_hash(run / 'inputs/request.json'),
            'inventory_sha256': file_hash(run / 'analysis/inventory.json'),
            'policy_sha256': file_hash(run.parent.parent / 'config/fast-delivery.json'),
            'knowledge_snapshot_version': 1, 'knowledge_context': context,
            'knowledge': knowledge, 'source_references': references,
            'knowledge_advisories': advisories(context, root), 'routing_assessment': assessment,
            'assets': assets, 'segments': [], 'audio_assets': recipe.get('audio_assets', [])}
    if request.get('text_restoration_contract_version', 0) >= 2:
        from .restoration_probes import validate_base
        # Registration may still produce a complete best-available candidate.
        # Missing base evidence prevents a quality pass, not bounded output.
        validate_base(run, recipe.get('restoration_base'), assets)
        require(not recipe.get('restoration_base') or all(
            s['asset']['sha256'] != output['sha256'] for s in recipe['restoration_base']['segments']),
            'The finished target overlay cannot serve as its own pre-lettering base')
        plan['restoration_probe_contract'] = 1
        plan['restoration_base'] = recipe.get('restoration_base')
    from .source_styles import contract as style_contract, review_template as style_review_template
    styles = style_contract(run, inventory)
    if styles:
        plan['source_style_contract'] = styles
    if request.get('routing_contract_version', 0) >= 1:
        from .captions import contract
        plan['caption_contract'] = contract(inventory)
    from .typography import contract, verify_receipt
    typography_contract = contract(run, inventory)
    if typography_contract:
        receipts = recipe.get('typography_assets', [])
        require(bool(receipts), 'Fast motion recipe needs actual typography receipts')
        covered = set()
        for asset in receipts:
            receipt = verify_receipt(run, asset)
            require(any(a['path'] == receipt['output']['path'] and a['sha256'] == receipt['output']['sha256'] for a in assets),
                    'Fast recipe must bind the actual typography-composited visual')
            covered.update(read_json(inside(run, receipt['provenance']['path']))['texts'])
        require(covered == {i['id'] for i in inventory['text_instances'] if i.get('display',{}).get('motion')},
                'Fast typography receipts do not cover motion instances')
        from .typography import verify_assets
        verify_assets(run,receipts,inventory)
        plan['typography_contract'] = typography_contract
        plan['typography_assets'] = receipts
    plan['id'] = object_hash(plan)[:16]
    _freeze_knowledge(run, plan)
    validate_plan(run, plan)
    write_json(run / 'plan.json', plan)
    write_json(run / 'outputs/candidate.json', {**output, 'mode': 'fast', 'plan_id': plan['id'],
               'typography_assets':plan.get('typography_assets', []),
               'inventory_sha256': plan['inventory_sha256'], 'recipe': recipe_relative})
    checks = {key: {'decision': 'pending', 'observation': '', 'evidence': []}
              for key in policy(run.parent.parent)['review_checks']}
    template = {'video_sha256': output['sha256'], 'plan_id': plan['id'], 'reviewer': '', 'method': '',
                'improvement_workflow': 'agent/workflows/continuous-improvement.md',
                'typography_fallbacks': [],
                'source_style_review': style_review_template(inventory),
                'text_restoration_review': restoration_review_template(inventory),
                'covered_text_ids': [], 'covered_speech_ids': [], 'checks': checks, 'known_variations': [],
                'visual_finish': {'score': None, 'normal_speed_observation': '', 'evidence': [], 'defects': []}}
    write_json(run / 'review/fast-template.json', template)
    write_json(run / 'outputs/reuse-assets.json', {'source_sha256': plan['source_sha256'], 'assets': assets})
    return {'state': 'needs_review', 'template': 'review/fast-template.json', 'plan_id': plan['id'],
            'next_action': f'Run capture {run.name} to collect review evidence for the registered candidate'}


def review_failures(review, candidate, inventory, run, checks):
    from .text_restoration import review_failures as restoration_review_failures
    failures = restoration_review_failures(run, inventory, review, candidate)
    from .source_styles import review_failures as style_review_failures
    failures.extend(style_review_failures(run, inventory, review, candidate))
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


def _count_video_frames(path):
    import json
    counted = json.loads(media.command(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0',
        '-show_entries', 'stream=nb_read_frames', '-of', 'json', path]).stdout)
    return int(counted['streams'][0]['nb_read_frames'])


def _source_frame_count(root, source, digest, decoder):
    identity = {'version': 1, 'source_sha256': digest, 'decoder': decoder}
    path = root / 'state/fast-source-frames' / (object_hash(identity) + '.json')
    require(file_hash(source) == digest, 'Source changed before frame count')
    try:
        cached = read_json(path)
        count = cached['frame_count']
        if (cached['identity'] == identity and type(count) is int and count > 0
                and cached['sha256'] == object_hash({'identity': identity, 'frame_count': count})):
            return count
    except (OSError, ValueError, KeyError, TypeError):
        pass
    count = _count_video_frames(source)
    require(file_hash(source) == digest, 'Source changed during frame count')
    if count > 0:
        record = {'identity': identity, 'frame_count': count}
        write_json(path, {**record, 'sha256': object_hash(record)})
    return count


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
    for segment in (plan.get('restoration_base') or {}).get('segments', []):
        require_clear(plan['source_sha256'], segment['asset']['sha256'], run.parent.parent)
    review_path = run / 'review/fast-review.json'
    review = read_json(review_path) if review_path.exists() else {}
    if review_path.exists():
        # Canonical review consumed by the existing status/learning interfaces.
        shutil.copyfile(review_path, run / 'review/review.json')
    inv = read_json(run / 'analysis/inventory.json')
    failures = review_failures(review, candidate, inv, run, policy(run.parent.parent)['review_checks'])
    # Fast delivery retains the common audio/caption contract. A pass checkbox
    # cannot replace actual AV timing evidence or override a negative model review.
    from . import audio, captions
    capture_path = run / 'review/capture.json'
    captured = read_json(capture_path) if capture_path.exists() else {}
    caption_check = captions.evaluate(run, candidate, inv, captured,
        read_json(run.parent.parent / 'config/quality.json')['caption_sync'], plan)
    failures.extend(caption_check['failures'])
    model_audio_check = audio.model_review_check(run, candidate, plan['source_sha256'], captured)
    failures.extend(model_audio_check['failures'])
    from .typography import review_failures as typography_review_failures
    failures.extend(typography_review_failures(run,plan.get('typography_assets',[]),review))
    failures.extend(visual_finish_failures(review, run, policy(run.parent.parent).get('visual_acceptance')))
    failures.extend('recipe_unresolved:' + str(reason) for reason in recipe.get('known_failures', []))
    # Reuse the full decode only when the actual bytes and decoder are unchanged.
    check_path = run / 'outputs/fast-technical.json'
    cached = read_json(check_path) if check_path.exists() else {}
    probe_version = media.command(['ffprobe', '-version']).stdout
    signature = object_hash({'video': candidate['sha256'], 'source': plan['source_sha256'],
                             'code': file_hash(Path(__file__)),
                             'audio_code': file_hash(Path(__file__).with_name('audio.py')),
                             'audio_policy': inv.get('audio', {}),
                             'decoder': media.command(['ffmpeg', '-version']).stdout,
                             'probe': probe_version})
    if cached.get('signature') != signature:
        from .workflow import source_path
        with timing.measure(run, 'fast.technical_decode'):
            original = source_path(run)
            source, actual = media.probe(original), media.probe(video)
            media.command(['ffmpeg', '-v', 'error', '-xerror', '-i', video, '-f', 'null', '-'])
            errors = []
            if abs(actual['duration'] - source['duration']) > .1: errors.append('duration_changed')
            if (source['width'], source['height']) != (actual['width'], actual['height']): errors.append('dimensions_changed')
            if abs(source['fps'] - actual['fps']) > .001: errors.append('frame_rate_changed')
            counts = [_source_frame_count(run.parent.parent, original, plan['source_sha256'], probe_version),
                      _count_video_frames(video)]
            if counts[0] != counts[1]: errors.append('frame_count_changed')
            audio_report = audio.evaluate_cached(run, original, video,
                                                 inv.get('audio') or {'strategy': 'preserve'}, source['duration'])
            errors.extend(audio_report['failures'])
            cached = {'signature': signature, 'source': source, 'actual': actual, 'frame_counts': counts, 'audio': audio_report, 'failures': errors}
            write_json(check_path, cached)
    failures.extend(cached['failures'])
    result = {'decision': 'pass' if not failures else 'revise', 'scope': 'fast-basic',
              'video_sha256': candidate['sha256'], 'plan_id': plan['id'], 'failures': failures,
              'caption_check': caption_check, 'audio_model_check': model_audio_check,
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
        media.copy_verified_video(inside(run, candidate['path']), run / 'outputs/final.mp4', candidate['sha256'])
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
