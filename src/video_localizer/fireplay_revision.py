"""Narrow review of quantity corrections without replacing funded production."""
from .common import file_hash, require, utc_now, write_json


def return_revision(path, old, value, grant, root):
    """Archive a settled return before an explicitly requested, reviewed repair.

    This changes the active delivery record only. Previously bound platform
    materials and all of their receipts remain in the immutable archive.
    """
    require(grant.get('authority') == 'user' and grant.get('authorization_ref')
            and grant.get('source_quote') and grant.get('reason'),
            'Return revision needs the actual user repair instruction')
    digest = file_hash(path)
    require(grant.get('previous_outbox_sha256') == digest,
            'Return revision must bind the exact previous outbox')
    require(old.get('state') == 'returned' and old.get('operations', {}).get('bind', {}).get('state') == 'verified'
            and all(op.get('state') == 'verified' for op in old.get('operations', {}).values()),
            'Settle all prior return operations before a repair revision')
    previous = {(p['video_index'], p['locale']): p for p in old['packages']}
    current = {(p['video_index'], p['locale']): p for p in value['packages']}
    require(previous.keys() <= current.keys(), 'Repair revision must retain every previously submitted locale')
    require(all(current[k]['sha256'] != p['sha256'] for k, p in previous.items()),
            'Repair revision requires new reviewed video bytes for every replaced locale')
    archive = path.parent / 'return-revisions' / f'{path.stem}-{digest}.json'
    if not archive.exists():
        write_json(archive, old)
    require(file_hash(archive) == digest, 'Prior return archive differs from the verified outbox')
    value['revision_history'] = [*old.get('revision_history', []), {
        'prior_outbox': str(archive.relative_to(root)), 'prior_outbox_sha256': digest,
        'authorization': grant, 'recorded_at': utc_now(),
        'boundary': 'New active repaired deliveries only; prior platform bindings are preserved, not deleted.'}]
    write_json(path, value)
    return value


def quantity_correction(previous, snap, decision, targets):
    if not decision.get('review_quantity_only') or previous.get('content_version') == snap['content_version']:
        return False
    before = previous.get('snapshot', {}).get('brief', {})
    after = snap['brief']
    keys = ('id', 'code', 'deptId', 'title', 'description', 'refText', 'assetType', 'locales', 'channels')
    require(previous.get('budget') and any(v.get('members') for v in previous.get('videos', []))
            and previous.get('decision', {}).get('quantity_mode') == 'one_per_locale'
            and decision.get('quantity_mode') == 'one_per_locale'
            and decision.get('reviewed_content_version') == previous.get('content_version')
            and decision.get('revision_reason') and previous.get('targets') == targets
            and all(before.get(k) == after.get(k) for k in keys)
            and before.get('quantity') != after.get('quantity')
            and after.get('quantity') == sum(len(v['targets']) for v in previous.get('videos', [])),
            'Quantity-only review needs unchanged funded source/language scope and the exact old version')
    return True
