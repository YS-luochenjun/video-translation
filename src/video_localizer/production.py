"""Reusable local production steps. AI decisions and observed reviews stay explicit."""
from pathlib import Path

from .common import (ROOT, WorkflowError, file_hash, guarded, inside,
                     object_hash, read_json, require, write_json)
from . import batches, workflow


def _fingerprint(run, plan):
    # Conservative invalidation: final copy, source/voice assets, layout inputs,
    # model results, encoder version and renderer code must still match.
    from . import media
    from .library import _bound_assets, _asset_closure
    source = workflow.source_path(run)
    require(file_hash(source) == plan['source_sha256'], 'Production source changed')
    inventory = read_json(run / 'analysis/inventory.json')
    roots = [(source, plan['source_sha256'])]
    workspace_files = {}
    for value in (plan, inventory):
        for path, digest in _bound_assets(value):
            if path.startswith(('knowledge/','assets/','config/')):
                asset = inside(run.parent.parent,path)
                require(asset.is_file() and file_hash(asset) == digest, 'Bound workspace dependency changed')
                workspace_files['workspace/'+path] = digest
            else:
                roots.append((inside(run,path),digest))
    dependencies = _asset_closure(run, roots)
    files = {**workspace_files, **{name: file_hash(path) for name, path in dependencies.items()}}
    jobs = []
    model_segments = {s['id'] for s in plan.get('segments', [])
                      if s.get('route') not in ('local_overlay', 'reference_composite', 'prepared_video')}
    reused_jobs = {s['reused_model_job'] for s in plan.get('segments', []) if s.get('reused_model_job')}
    for path in sorted((run / 'jobs').glob('*.json')):
        job = read_json(path)
        for asset in job.get('results', []) + ([{'path': job['result'], 'sha256': job['result_sha256']}] if job.get('result') else []):
            require(file_hash(inside(run, asset['path'])) == asset['sha256'], 'Model result changed')
        # Audio perception and billing receipts do not change rendered media.
        # Bound TTS/mix assets are already in the verified dependency closure.
        if job.get('id') in reused_jobs or (job.get('plan_id') == plan.get('id')
                                             and job.get('segment') in model_segments):
            jobs.append({key: job.get(key) for key in ('id', 'plan_id', 'segment', 'state', 'task_id',
                          'packet_sha256', 'result', 'result_sha256', 'results')})
    from .render_cache import implementation_signature
    code = implementation_signature()
    fonts = {p.as_posix(): file_hash(p) for p in (ROOT / 'assets/fonts').rglob('*') if p.is_file()}
    return object_hash({'plan': plan, 'inputs': files, 'jobs': jobs, 'code': code, 'fonts': fonts,
                        'encoder': media.command(['ffmpeg', '-version']).stdout})


@guarded
def advance(run, deliver=False, force_render=False):
    from .cli import capture
    if deliver and (run / 'review/finalization.json').exists():
        from .finalization import finish
        result = finish(run)
        return {'run': run.name, 'state': result['state'], 'delivery': result}
    if (run / 'plan.json').exists() and read_json(run / 'plan.json').get('mode') == 'fast':
        from . import fast_delivery
        result = fast_delivery.quality(run)
        return {'run': run.name, 'quality': result,
                'state': 'delivered' if deliver and result['decision'] == 'pass' else
                         'reviewed' if result['decision'] == 'pass' else 'needs_review',
                **({'delivery': fast_delivery.deliver(run)} if deliver and result['decision'] == 'pass' else {})}
    if not (run / 'analysis/inventory.json').exists():
        workflow.analyze(run)
        return {'run': run.name, 'state': 'needs_inventory', 'next': 'Inspect source evidence and complete inventory'}
    # Preserve an explicitly chosen experiment/route. A stale plan requires the
    # operator to re-plan; silently rebuilding could select a different algorithm.
    if not (run / 'plan.json').exists():
        workflow.build_plan(run)
    plan = workflow.current_plan(run)
    batches.gate(run, plan)
    for segment in plan['segments']:
        if segment.get('prepared_video'):
            from .prepared import verify_for_production
            verify_for_production(run, segment['prepared_video'], plan['source_sha256'])
    fingerprint = _fingerprint(run, plan)
    cache = run / 'outputs/production-checkpoint.json'
    saved = read_json(cache) if cache.exists() else {}
    candidate_path = run / 'outputs/candidate.json'
    candidate = read_json(candidate_path) if candidate_path.exists() else {}
    reusable = (not force_render and saved.get('fingerprint') == fingerprint
                and candidate.get('plan_id') == plan['id'] and candidate.get('sha256') == saved.get('video_sha256')
                and inside(run, candidate.get('path', 'missing')).is_file()
                and file_hash(inside(run, candidate['path'])) == candidate['sha256'])
    from .quality_holds import require_clear
    if reusable:
        require_clear(plan['source_sha256'], candidate['sha256'], run.parent.parent)
    else:
        if force_render:
            workflow.render(run, force_segments=True)
        else:
            workflow.render(run)
        candidate = read_json(candidate_path)
        write_json(cache, {'fingerprint': fingerprint, 'video_sha256': candidate['sha256']})
    from .visual_audit import generate
    visual_evidence = generate(run)
    capture(run)  # Include new actual caption observations, never copy a prior pass.
    quality = workflow.quality(run)
    result = {'run': run.name, 'render_reused': reusable, 'quality': quality, 'visual_evidence': visual_evidence,
              'state': 'reviewed' if quality['decision'] == 'pass' else 'needs_review'}
    if deliver and quality['decision'] == 'pass':
        result['delivery'] = workflow.deliver(run)
        result['state'] = 'delivered'
    return result


def advance_batch(batch_id, deliver=False, root=ROOT):
    record = read_json(batches._path(batch_id, root))
    results = []
    for name in record['members']:
        run = Path(root) / 'runs' / name
        try:
            # Serial by default: no concurrent encoders competing for disk/memory.
            result = advance(run, deliver=deliver)
        except (WorkflowError, OSError, KeyError, ValueError) as exc:
            results.append({'run': name, 'state': 'blocked', 'reason': str(exc)})
            break
        results.append(result)
        if result['state'] not in ('reviewed', 'delivered'):
            break
        if name == record['pilot'] and not record.get('pilot_release'):
            break  # batch-approve is an explicit review checkpoint, never auto-signed.
    complete = len(results) == len(record['members']) and all(
        row['state'] in ('reviewed', 'delivered') for row in results)
    return {'batch': batch_id, 'results': results, 'state': 'completed' if complete else 'needs_attention',
            'next': 'All members passed current quality checks' if complete else
                    'Complete missing evidence; batch-approve after reviewing the pilot, then batch-run again'}


@guarded
def tts_packet(run, voice, estimate, speech_ids=None):
    from . import model_tasks
    from .model_routing import selected as selected_model
    inventory = read_json(run / 'analysis/inventory.json')
    lines = inventory.get('speech_segments', [])
    ids = speech_ids or [line['id'] for line in lines]
    selected = {line['id']: line for line in lines}
    require(ids and all(key in selected for key in ids), 'Select existing final speech segments')
    locale = read_json(run / 'inputs/request.json')['target_language']
    data = {'source_sha256': file_hash(workflow.source_path(run)),
            'purpose': 'Narration from finalized speech copy; alignment and actual listening/review remain required',
            'estimated_credits': estimate, 'speech_ids': ids,
            'payload': {'model': selected_model('tts'), 'input': {
                'speakers': [{'speaker_id': 'Speaker 1', 'voice_name': voice}],
                'scene': (f'Read only the exact supplied dialogue in {locale}, in the given order. '
                          'Preserve names, numbers and claims. Do not translate, paraphrase, omit, repeat, '
                          'or speak instructions or speaker labels. Use clear natural advertising speech '
                          'and finish every word. Voice only: no music, sound effects or extra speech.'),
                'dialogue_turns': [{'speaker_id': 'Speaker 1', 'text': '\n\n'.join(selected[key]['target_text'] for key in ids)}]}}}
    relative = 'inputs/tts-' + object_hash(data)[:16] + '.json'
    write_json(run / relative, data)
    model_tasks.packet(run, relative)
    return {'packet': relative, 'paid_submission': False, 'next': 'Inspect model-task packet; submit only if the selected voice/style and budget fit the task'}
