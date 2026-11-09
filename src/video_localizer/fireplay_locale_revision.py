"""User-authorized locale additions to funded, unsubmitted single-source work.

Keep existing run identities and the already amended shared budget. No remote
operations, spending, source replacement or implicit authorization occur here.
"""
import copy

from .common import file_hash, inside, object_hash, read_json, require, utc_now, write_json


def accept(previous, snap, sources, decision, targets, folder, root):
    require(decision.get('review_locale_addition') is True
            and decision.get('reviewed_content_version') == previous['content_version']
            and decision.get('revision_reason'), 'Locale addition needs exact prior-version review')
    require(previous.get('budget') and snap['row'].get('canBindMaterials') is True
            and snap['row'].get('status') != 'done', 'Keep the funded, executable requirement')
    require(not list(folder.glob('return-*.json')), 'Resolve prior submissions before adding locales')
    require(len(previous['videos']) == len(sources) == 1,
            'Funded locale addition currently supports exactly one unchanged source')
    before, after = previous['snapshot']['brief'], snap['brief']
    require(previous['requirement_id'] == after['id'], 'Requirement identity changed')
    for key in ('id', 'code', 'deptId', 'title', 'description', 'refText', 'landingUrl',
                'assetType', 'aiMode', 'bizLine', 'category', 'quantity', 'channels',
                'tags', 'requesterIds', 'requestDate', 'dueDate'):
        require(before.get(key) == after.get(key), 'Locale addition changed another field: ' + key)
    prior_targets = previous['targets']
    require(len(targets) > len(prior_targets) and targets[:len(prior_targets)] == prior_targets
            and len(targets) == len(set(targets)), 'Append new locales without reordering existing runs')
    old_video = previous['videos'][0]
    require(old_video['targets'] == prior_targets and sources[0]['targets'] == targets
            and sources[0]['source_url'] == old_video['source_url'], 'Source or per-source locales changed')
    source = old_video.get('source', {})
    require(source.get('sha256') and file_hash(inside(root, source.get('path', 'missing'))) == source['sha256'],
            'Existing source bytes must remain available and unchanged')
    require(old_video.get('members') and old_video.get('pilot') == old_video['members'][0]
            and len(old_video['members']) == len(prior_targets), 'Inspect incomplete existing run mapping first')
    authority_path = inside(root, decision.get('locale_revision_authority', 'missing'))
    grant = read_json(authority_path)
    budget = read_json(inside(root, 'state/budgets/' + previous['budget'] + '.json'))
    expected = {'authority': 'user', 'action': 'accept_funded_locale_addition',
                'requirement_id': previous['requirement_id'],
                'previous_content_version': previous['content_version'],
                'next_content_version': snap['content_version'], 'budget_id': previous['budget'],
                'credit_limit': budget['credit_limit'], 'previous_targets': prior_targets,
                'targets': targets, 'source_sha256s': [source['sha256']]}
    require(all(grant.get(k) == v for k, v in expected.items())
            and grant.get('authorization_ref') and grant.get('source_quote'),
            'Actual user authority must bind both versions, locales, source and original budget cap')
    amendments = budget.get('authorized_amendments', [])
    require(any(a.get('authorization_ref') == grant['authorization_ref']
                and len(a.get('targets', [])) == len(targets)
                and set(a.get('targets', [])) == set(targets)
                and a.get('previous_limit') == a.get('new_total_credit_limit') == grant['credit_limit']
                for a in amendments), 'Use the attributed native budget amendment without increasing its cap')
    budget_targets = budget.get('budget_basis', {}).get('targets', [])
    require(len(budget_targets) == len(targets) and set(budget_targets) == set(targets),
            'Existing shared budget must already authorize the added locales')
    archive = folder / 'revisions' / (object_hash(previous) + '.json')
    if archive.exists():
        require(read_json(archive) == previous, 'Existing revision archive changed')
    else:
        write_json(archive, previous)
    result = copy.deepcopy(previous)
    result['content_version'] = snap['content_version']
    result['targets'] = list(targets)
    result['requested_targets'] = list(after['locales'])
    result['videos'][0]['targets'] = list(targets)
    result.setdefault('revision_history', []).append({
        'scope': 'append_locales_same_budget', 'content_version': previous['content_version'],
        'new_content_version': snap['content_version'], 'path': archive.relative_to(root).as_posix(),
        'previous_targets': list(prior_targets), 'targets': list(targets),
        'reason': decision['revision_reason'], 'reviewed_at': utc_now(),
        'authority': {'path': authority_path.relative_to(root).as_posix(), 'sha256': file_hash(authority_path)},
        'budget_preserved': previous['budget'], 'credit_limit_preserved': grant['credit_limit']})
    return result


def extend_batch(record, video, batch, members, root):
    """Append run slots once; retain pilot verdict, history and all old members."""
    revisions = [x for x in record.get('revision_history', [])
                 if x.get('scope') == 'append_locales_same_budget'
                 and x.get('new_content_version') == record['content_version']]
    require(len(revisions) == 1, 'A changed funded batch needs its exact reviewed locale addition')
    revision = revisions[0]
    pointer = revision['authority']; path = inside(root, pointer['path'])
    require(file_hash(path) == pointer['sha256'], 'Locale-addition authority changed')
    grant = read_json(path)
    require(grant.get('authority') == 'user' and grant.get('action') == 'accept_funded_locale_addition'
            and grant.get('next_content_version') == record['content_version']
            and grant.get('budget_id') == record['budget'] and grant.get('targets') == video['targets'],
            'Batch addition must retain the exact approved scope and shared budget')
    require(batch['request_budget'] == record['budget']
            and batch['source_sha256'] == video['source']['sha256']
            and batch['targets'] == revision['previous_targets']
            and video['targets'] == revision['targets']
            and len(batch['members']) == len(batch['targets'])
            and members[:len(batch['members'])] == batch['members']
            and batch['pilot'] == members[0]
            and batch['credit_limit'] == revision['credit_limit_preserved'] == grant['credit_limit'],
            'Locale addition cannot replace members, source, pilot or funding')
    result = copy.deepcopy(batch)
    result.setdefault('locale_revision_history', []).append({
        'content_version': record['content_version'], 'previous_members': list(batch['members']),
        'previous_targets': list(batch['targets']), 'authority': pointer, 'at': utc_now()})
    result.update(targets=list(video['targets']), members=list(members))
    return result
