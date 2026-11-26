"""Copy a reviewed neutral master and its evidence without copying locale decisions."""
from contextlib import ExitStack
import copy

from .common import WorkflowError, file_hash, inside, read_json, require, run_operation, write_json
from .media import copy_verified_video
from .prepared import verify_for_production
from .timing import measure


def batch_candidates(run, inventory, batch):
    """List matching prepared shots from sibling locales before creating a new master."""
    from .local_audio import _source_scope
    if not batch or run.name not in batch.get('members', []):
        return []
    scope = _source_scope(run)
    if scope is None:
        return []
    missing = [shot for shot in inventory.get('shots', []) if not shot.get('prepared_video')]
    if not missing:
        return []
    source_sha = batch.get('source_sha256')
    candidates = []
    for member in batch['members']:
        if member == run.name:
            continue
        try:
            origin = inside(run.parent, member)
            if origin.parent != run.parent or _source_scope(origin) != scope:
                continue
            if read_json(origin / 'run.json').get('source_sha256') != source_sha:
                continue
            sibling = read_json(origin / 'analysis/inventory.json')
            for shot in sibling.get('shots', []):
                asset = shot.get('prepared_video')
                if not asset:
                    continue
                record_path = inside(origin, asset['record'])
                if not record_path.is_file() or file_hash(record_path) != asset['record_sha256']:
                    continue
                record = read_json(record_path)
                if record.get('approved_for_reuse') is not True or record.get('source_sha256') != source_sha:
                    continue
                if not inside(origin, asset['path']).is_file():
                    continue
                for target in missing:
                    if (shot['start'], shot['end']) == (target['start'], target['end']):
                        candidates.append({'source_run': member, 'source_shot': shot['id'],
                                           'target_shot': target['id'], 'sha256': asset['sha256'],
                                           'state': 'requires_reuse_neutral_verification'})
        except (OSError, ValueError, KeyError, TypeError, WorkflowError):
            continue
    return candidates


def neutral(target, source, source_shot, target_shot):
    require(target != source and target.parent == source.parent, 'Reuse requires two distinct runs in this workspace')
    with ExitStack() as stack:
        for run in sorted((source, target)):
            stack.enter_context(run_operation(run, resume=run == target))
        stack.enter_context(measure(target, 'reuse.neutral'))
        from .workflow import source_path
        original_video = source_path(source)
        target_video = source_path(target)
        source_sha = file_hash(original_video)
        require(file_hash(target_video) == source_sha, 'Neutral master reuse requires the exact same original video')
        original = read_json(source / 'analysis/inventory.json')
        inventory = read_json(target / 'analysis/inventory.json')
        shot = next((s for s in original['shots'] if s['id'] == source_shot), None)
        destination_shot = next((s for s in inventory['shots'] if s['id'] == target_shot), None)
        require(shot and destination_shot and shot.get('prepared_video'), 'Select source prepared shot and existing target shot')
        require((shot['start'], shot['end']) == (destination_shot['start'], destination_shot['end']), 'Neutral master timeline differs')
        asset = shot['prepared_video']
        verify_for_production(source, asset, source_sha, target.parent.parent)
        record = read_json(inside(source, asset['record']))
        prefix = 'inputs/reused-neutral/' + asset['sha256'][:16] + '-' + asset['record_sha256'][:16]

        def copied(relative, expected=None):
            old = inside(source, relative)
            require(old.is_file(), 'Missing neutral reuse evidence')
            if old == original_video:
                require(expected in (None, source_sha), 'Neutral source binding changed')
                return {'path': target_video.relative_to(target).as_posix(), 'sha256': source_sha}
            digest = file_hash(old)
            require(expected is None or digest == expected, 'Neutral evidence changed during reuse')
            new = inside(target, prefix + '/' + relative)
            if new.exists():
                require(file_hash(new) == digest, 'Conflicting neutral evidence; existing bytes are not overwritten')
            else:
                new.parent.mkdir(parents=True, exist_ok=True)
                copy_verified_video(old, new, digest)
            require(file_hash(new) == digest, 'Neutral copy changed')
            return {'path': new.relative_to(target).as_posix(), 'sha256': digest}

        result = copied(asset['path'], asset['sha256'])
        original_record = copied(asset['record'], asset['record_sha256'])
        inputs = [copied(item['path'], item['sha256']) for item in record['inputs']]
        review = read_json(inside(source, record['visual_review']['path']))
        review = copy.deepcopy(review)
        review['evidence'] = [copied(e['path'], e['sha256']) for e in review['evidence']]
        review_path = inside(target, prefix + '/bound-review.json')
        write_json(review_path, review)
        local = copy.deepcopy(record)
        local['inputs'] = inputs + [original_record]
        local['output'] = result
        local['visual_review'] = {'path': review_path.relative_to(target).as_posix(), 'sha256': file_hash(review_path)}
        if local.get('text_visual_audit'):
            local['text_visual_audit'] = copied(local['text_visual_audit']['path'], local['text_visual_audit']['sha256'])
            local['text_visual_review_index'] = copied(local['text_visual_review_index']['path'], local['text_visual_review_index']['sha256'])
        for proposal in local.get('model_proposals', []):
            proposal['job_record'] = copied(proposal['job_record'])['path']
            # This is past task evidence, not a newly billed job in target/jobs.
            local['inputs'].append({'path': proposal['job_record'], 'sha256': file_hash(inside(target, proposal['job_record']))})
        local['reuse_origin'] = {'source_run': source.name, 'original_record': original_record}
        record_path = inside(target, prefix + '/bound-preparation.json')
        write_json(record_path, local)
        result.update(record=record_path.relative_to(target).as_posix(), record_sha256=file_hash(record_path))
        verify_for_production(target, result, source_sha, target.parent.parent)
        destination_shot['prepared_video'] = result
        write_json(target / 'analysis/inventory.json', inventory)
        return {'run': target.name, 'prepared_video': result, 'new_paid_tasks': 0,
                'scope': 'Only neutral visual preparation/evidence copied; target copy, voice, typography and review are still independent. Rebuild the target plan.'}
