"""Locale batch orchestration and pilot gates; budgets belong to user requests."""
from pathlib import Path
import re

from .common import (ROOT, file_hash, inside, lock, read_json, require, require_number,
                     run_operation, utc_now, write_json)


def _path(batch_id, root):
    require(isinstance(batch_id, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,59}', batch_id),
            'Invalid batch id')
    return Path(root) / 'state/batches' / (batch_id + '.json')


def authorization(root=ROOT):
    from .kie_access import policy as access_policy
    access = access_policy(root)
    path = Path(root) / 'config/kie-authorization.local.json'
    if not path.exists():
        return {'automatic_use': False, 'reason': 'No project owner authorization configured', 'task_verification': access}
    value = read_json(path)
    require(value.get('provider') == 'KIE' and value.get('source_quote'), 'Invalid KIE authorization')
    enabled = value.get('automatic_use') is True and Path(value.get('workspace', '')).resolve() == Path(root).resolve()
    return {**value, 'automatic_use': enabled, 'sha256': file_hash(path), 'task_verification': access}


def create(batch_id, video, targets, brief, reused=False, root=ROOT):
    from . import workflow
    from . import budgets
    from .languages import resolve
    path = _path(batch_id, root)
    languages = [resolve(target, root)['target_language'] for target in targets]
    require(languages and len(languages) == len(set(languages)), 'Batch needs distinct target languages')
    names = [batch_id + '-' + str(i+1).zfill(2) for i in range(len(languages))]
    settings = read_json(Path(root) / 'config/workspace.json')
    request_budget = budgets.for_source(file_hash(video), root)
    budgets.require_targets(request_budget, languages, root)
    require(request_budget['mode'] == ('reuse' if reused else 'first'), 'Batch mode must match the existing human request budget')
    cap = request_budget['credit_limit']
    require_number(cap, 'batch credits', minimum=1)
    with lock(path.with_suffix('.lock')):
        require(not path.exists(), 'Batch already exists; use batch-status or batch-run to resume')
        require(all(not (Path(root) / 'runs' / name).exists() for name in names), 'Batch run already exists')
        source_sha = file_hash(video)
        record = {'schema_version': 1, 'id': batch_id, 'source_sha256': source_sha,
                  'created_at': utc_now(), 'credit_limit': cap, 'reused_budget': reused,
                  'pilot': names[0], 'members': names, 'targets': languages,
                  'request_budget': request_budget['id'],
                  'state': 'initializing', 'authorization': authorization(root)}
        write_json(path, record)
        for name, language in zip(names, languages):
            workflow.create_run(video, language, brief, name)
            run = Path(root) / 'runs' / name
            require(read_json(run / 'run.json')['source_sha256'] == source_sha, 'Source changed during batch creation')
            write_json(run / 'inputs/batch.json', {'id': batch_id, 'source_sha256': source_sha,
                       'run': name, 'origin_workspace': str(Path(root).resolve())})
            if reused and request_budget.get('budget_basis', {}).get('policy') not in ('source_duration', 'per_target_language'):
                write_json(run / 'inputs/budget.json', {'source_sha256': source_sha,
                    'reason': 'Explicit incremental reuse batch; lower existing workspace limit',
                    'max_paid_jobs_per_run': settings['max_paid_jobs_per_run'],
                    'max_estimated_credits_per_run': cap})
        record['state'] = 'pilot_pending'
        write_json(path, record)
    return {'batch': batch_id, 'pilot': names[0], 'members': dict(zip(languages, names)),
            'credit_limit': cap, 'next': 'Analyze and review the pilot; batch-run never invents inventory or review.'}


def binding(run):
    run = Path(run).resolve()
    root = run.parent.parent
    pointer = run / 'inputs/batch.json'
    if pointer.exists():
        reference = read_json(pointer)
        # An archived package carries historical batch provenance, not permission
        # to bill a different workspace/run against the original owner's batch.
        historical = (reference.get('run', run.name) != run.name or
                      Path(reference.get('origin_workspace', str(root))).resolve() != root)
        if historical:
            found = [p.stem for p in (root / 'state/batches').glob('*.json')
                     if run.name in read_json(p).get('members', [])]
            require(len(found) <= 1, 'Run belongs to conflicting batches')
            if not found:
                return None
            batch_id = found[0]
        else:
            batch_id = reference['id']
    else:
        # Removing a pointer must not allow a member to escape aggregate accounting.
        found = [p.stem for p in (root / 'state/batches').glob('*.json')
                 if run.name in read_json(p).get('members', [])]
        require(len(found) <= 1, 'Run belongs to conflicting batches')
        if not found:
            return None
        batch_id = found[0]
    path = _path(batch_id, root)
    record = read_json(path)
    require(run.name in record['members'], 'Run not registered in batch')
    require(read_json(run / 'run.json')['source_sha256'] == record['source_sha256'], 'Batch source mismatch')
    require(record['state'] != 'initializing', 'Batch initialization incomplete; inspect its recorded members')
    return path


def reserve(run, job_id, estimate):
    from . import budgets
    gate(run)
    return budgets.reserve(run, job_id, estimate)


def sync(run):
    from .budgets import sync as settle
    settle(run)


def masters(plan):
    return [{'start': s['start'], 'end': s['end'], 'sha256': s['prepared_video']['sha256']}
            for s in plan['segments'] if s.get('prepared_video')]


def _pilot_snapshot(record, root):
    from . import workflow
    from .quality_holds import require_clear
    pilot = Path(root) / 'runs' / record['pilot']
    with run_operation(pilot):
        plan = workflow.current_plan(pilot)
        require(plan['source_sha256'] == record['source_sha256'], 'Pilot belongs to another source')
        from .prepared import verify_for_production
        for segment in plan['segments']:
            if segment.get('prepared_video'):
                verify_for_production(pilot, segment['prepared_video'], record['source_sha256'], root)
        candidate = read_json(pilot / 'outputs/candidate.json')
        require_clear(record['source_sha256'], candidate['sha256'], root)
        quality = workflow.quality(pilot)
        require(quality['decision'] == 'pass',
                'Representative language has not passed current quality checks')
        if plan.get('mode') == 'fast':
            require(quality.get('scope') == 'fast-basic' and quality.get('review_sha256'),
                    'Representative fast language needs its current basic review')
            visual = {'scope': 'fast-basic', 'decision': 'pass',
                      'review_sha256': quality['review_sha256']}
        else:
            require(quality.get('text_visual_audit'),
                    'Representative language has not passed current quality checks')
            visual = quality['text_visual_audit']  # Freshly verified under this run lock.
        return {'plan_id': plan['id'], 'video_sha256': candidate['sha256'],
                'review_sha256': file_hash(pilot / 'review/review.json'), 'masters': masters(plan), 'text_visual_audit': visual}


def _finalized_pilot_snapshot(record, root):
    """Freeze a completed fast pilot without claiming quality or master approval."""
    from . import finalization
    pilot = Path(root) / 'runs' / record['pilot']
    with run_operation(pilot):
        require(read_json(Path(root) / 'config/workspace.json').get('output_policy') == 'best_available_required',
                'Best-available batch output is not selected')
        request = read_json(pilot / 'inputs/request.json')
        require(request.get('delivery_mode') == 'fast', 'Best-available expansion requires a fast pilot')
        completion_path = pilot / 'outputs/completion.json'
        require(completion_path.is_file(), 'Finalize the complete representative video before expanding')
        completion = read_json(completion_path)
        require(completion.get('state') == 'delivered_with_issues' and completion.get('decode_passed') is True
                and completion.get('quality_passed') is False, 'Representative completion is not a decoded best-available output')
        spec_path = inside(pilot, completion['spec'])
        require(file_hash(spec_path) == completion['spec_sha256'], 'Representative finalization changed')
        spec = read_json(spec_path)
        video = finalization.validate_completion(pilot, spec)
        require(spec['source_sha256'] == record['source_sha256'] == completion['source_sha256'],
                'Representative completion belongs to another source')
        require(completion['inventory_sha256'] == spec['inventory_sha256']
                and completion['request_sha256'] == spec['request_sha256'], 'Representative completion inputs changed')
        digest = file_hash(video)
        require(digest == completion['video_sha256'] == file_hash(pilot / 'outputs/final.mp4'),
                'Representative completed video changed')
        return {'scope': 'best_available', 'video_sha256': digest,
                'completion_sha256': file_hash(completion_path), 'review_sha256': file_hash(spec_path),
                'masters': [], 'quality_passed': False, 'neutral_approval': False,
                'limitations': spec['limitations']}


def approve(batch_id, root=ROOT, best_available=False):
    path = _path(batch_id, root)
    record = read_json(path)
    snapshot = _finalized_pilot_snapshot(record, root) if best_available else _pilot_snapshot(record, root)
    with lock(path.with_suffix('.lock')):
        record = read_json(path)
        record.update(pilot_release=snapshot, state='pilot_completed_with_issues' if best_available else 'pilot_reviewed')
        write_json(path, record)
    return {'batch': batch_id, 'pilot_release': snapshot,
            'scope': 'Existing attributable video review and current technical gates; this command does not assert human acceptance.'}


def gate(run, plan=None):
    path = binding(run)
    if not path:
        return
    record = read_json(path)
    if Path(run).name == record['pilot']:
        return
    require(record.get('pilot_release'), 'Review the representative language and run batch-approve before expanding')
    best_available = record['pilot_release'].get('scope') == 'best_available'
    if best_available:
        require(read_json(Path(run) / 'inputs/request.json').get('delivery_mode') == 'fast',
                'A best-available pilot does not approve strict expansion')
    snapshot = (_finalized_pilot_snapshot(record, Path(run).parent.parent) if best_available
                else _pilot_snapshot(record, Path(run).parent.parent))
    require(snapshot == record['pilot_release'], 'Pilot changed since batch release; review and approve the new version')
    if plan is not None:
        require(masters(plan) == snapshot['masters'], 'Batch neutral master differs from the reviewed pilot')


def status(batch_id, root=ROOT):
    from .timing import report
    from . import budgets
    path = _path(batch_id, root)
    with lock(path.with_suffix('.lock')):
        record = read_json(path)
    scope = record.get('request_budget') or budgets.for_source(record['source_sha256'], root)['id']
    accounting = budgets.status(scope, root)
    used = accounting['reserved_or_billed_credits']
    return {**record, 'reserved_or_billed_credits': used,
            'credit_limit': accounting['credit_limit'],
            'remaining_estimated_credits': max(0, accounting['credit_limit']-used),
            'unknown_billing_jobs': accounting['unknown_billing_jobs'], 'request_accounting': accounting,
            'timing': report([Path(root) / 'runs' / name for name in record['members']]),
            'scope': 'Conservative estimate gate; unknown charges stay reserved. Supplier overbilling cannot be prevented by local estimates.'}
