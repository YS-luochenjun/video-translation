"""Copy a reviewed neutral master and its evidence without copying locale decisions."""
from contextlib import ExitStack
import copy
import shutil

from .common import file_hash, inside, read_json, require, run_operation, write_json
from .prepared import verify_for_production
from .timing import measure


def neutral(target, source, source_shot, target_shot):
    require(target != source and target.parent == source.parent, 'Reuse requires two distinct runs in this workspace')
    with ExitStack() as stack:
        for run in sorted((source, target)):
            stack.enter_context(run_operation(run))
        stack.enter_context(measure(target, 'reuse.neutral'))
        from .workflow import source_path
        source_sha = file_hash(source_path(source))
        require(file_hash(source_path(target)) == source_sha, 'Neutral master reuse requires the exact same original video')
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
            digest = file_hash(old)
            require(expected is None or digest == expected, 'Neutral evidence changed during reuse')
            new = inside(target, prefix + '/' + relative)
            if new.exists():
                require(file_hash(new) == digest, 'Conflicting neutral evidence; existing bytes are not overwritten')
            else:
                new.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(old, new)
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
