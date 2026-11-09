"""Replace one positively rejected upload without discarding any write history."""
import copy
import json

from .common import file_hash, inside, read_json, require, utc_now, write_json


def replace_rejected_upload(path, old, value, grant, root):
    require(grant.get('authority') == 'agent' and grant.get('reviewer') and grant.get('reason'),
            'Transport replacement needs an attributed host observation')
    digest = file_hash(path)
    require(grant.get('previous_outbox_sha256') == digest, 'Transport outbox changed')
    require(value['packages'] and 'bind' not in old['operations']
            and (len(value['packages']) == 1 or grant.get('include_unsent_packages') is True),
            'Transport recovery needs one rejected upload; additional packages must be explicitly unsent')
    package = value['packages'][0]
    matches = [(i, p) for i, p in enumerate(old['packages'], 1)
               if (p['video_index'], p['locale']) == (package['video_index'], package['locale'])]
    require(len(matches) == 1, 'Expected one existing transport locale')
    number, previous = matches[0]
    key = f'upload-{number}'
    operation = old['operations'].get(key, {})
    require(operation.get('state') == 'unknown' and not operation.get('result')
            and f'import-{number}' not in old['operations'], 'Cannot replace an accepted or imported upload')
    ref = grant.get('rejection_receipt', {})
    receipt = inside(root, ref.get('path', ''))
    require(ref.get('path') == operation.get('last_observed_receipt')
            and receipt.is_file() and file_hash(receipt) == ref.get('sha256'),
            'Use the actual recorded rejection receipt')
    rejected = read_json(receipt).get('response', {})
    # An explicit gateway body rejection happens before upload acceptance.
    # Timeouts, arbitrary error prose and unknown outcomes never qualify.
    texts = [c.get('text', '') for c in rejected.get('content', []) if c.get('type') == 'text']
    require(rejected.get('isError') is True and len(texts) == 1
            and 'MCP returned HTTP 413:' in texts[0]
            and '"statusCode":413' in texts[0]
            and '"message":"request entity too large"' in texts[0],
            'Only a saved explicit HTTP 413 body rejection permits transport replacement')
    require(previous['sha256'] != package['sha256'], 'Transport package has not changed')
    replacements = [(number, previous, package)]
    seen = {(package['video_index'], package['locale'])}
    for extra in value['packages'][1:]:
        identity = (extra['video_index'], extra['locale'])
        require(identity not in seen, 'Duplicate transport locale')
        seen.add(identity)
        matches = [(i, p) for i, p in enumerate(old['packages'], 1)
                   if (p['video_index'], p['locale']) == identity]
        require(len(matches) == 1, 'Expected one existing unsent transport locale')
        index, prior = matches[0]
        require(not any(k.endswith('-' + str(index)) for k in old['operations'])
                and not old.get('upload_attempts', {}).get(f'upload-{index}')
                and not any((h.get('prior_package', {}).get('video_index'),
                             h.get('prior_package', {}).get('locale')) == identity
                            for h in old.get('transport_history', [])),
                'Additional transport packages must have no dispatched or historical upload')
        require(prior['sha256'] != extra['sha256'], 'Unsent transport package has not changed')
        replacements.append((index, prior, extra))
    archive = path.parent / 'transport-revisions' / f'{path.stem}-{digest}.json'
    if not archive.exists():
        write_json(archive, old)
    require(file_hash(archive) == digest, 'Transport archive differs')
    result = copy.deepcopy(old)
    for index, prior, replacement in replacements:
        result['packages'][index - 1] = replacement
    result['operations'].pop(key)
    result.setdefault('transport_history', []).append({
        'prior_outbox': str(archive.relative_to(root)), 'prior_outbox_sha256': digest,
        'prior_operation': operation, 'prior_package': previous,
        'replacement_package': package, 'observation': grant, 'recorded_at': utc_now()})
    for index, prior, replacement in replacements[1:]:
        result['transport_history'].append({
            'prior_outbox': str(archive.relative_to(root)), 'prior_outbox_sha256': digest,
            'prior_operation': None, 'prior_package': prior, 'replacement_package': replacement,
            'observation': grant, 'recorded_at': utc_now(),
            'basis': 'Reviewed smaller package prepared before any upload; same saved gateway413 rejection'})
    result.update(state='ready', transport_revised_at=utc_now())
    write_json(path, result)
    return result
