"""Explicit, funded narration-only narrowing; never reset production or funding."""
import copy
import re

from .common import file_hash, inside, object_hash, read_json, require, utc_now, write_json


def accept_narration_only(previous, snap, sources, decision, targets, folder, root):
    before, after, row = previous['snapshot']['brief'], snap['brief'], snap['row']
    require(decision.get('review_scope_narrowing') is True and decision.get('scope') == 'ad_narration_only',
            'Explicit narration-only scope review required')
    require(decision.get('reviewed_content_version') == previous['content_version']
            and decision.get('revision_reason'), 'Scope review needs the exact old version and reason')
    require(previous.get('budget') and row.get('canBindMaterials') is True
            and row.get('status') != 'done', 'Keep the funded request and current execution permission')
    require(not list(folder.glob('return-*.json')),
            'A request with return operations needs a separate publication revision')
    require(previous['requirement_id'] == row['id'] == after['id'], 'Scope revision identity changed')
    require(sorted(previous['targets']) == sorted(targets), 'Scope narrowing cannot change languages')
    require([v['source_url'] for v in previous['videos']] == [v['source_url'] for v in sources],
            'Scope narrowing cannot replace or append original videos')
    require(all(sorted(a['targets']) == sorted(b['targets']) for a, b in zip(previous['videos'], sources)),
            'Scope narrowing cannot change per-source languages')
    phrase = '只翻译文案的口播'
    description = after.get('description') or ''
    require(description.count(phrase) == 1 and phrase not in (before.get('description') or ''),
            'Only the exact narration-only narrowing is supported')
    def normalize(value):
        return re.sub(r'\s+', ' ', (value or '').replace('\\n', '\n')).strip()
    stripped = re.sub(re.escape(phrase) + r'[，,\s]*', '', description, count=1)
    require(normalize(stripped) == normalize(before.get('description')),
            'Scope narrowing cannot contain another description edit')
    for key in ('title', 'refText', 'landingUrl', 'assetType', 'aiMode', 'bizLine', 'category',
                'quantity', 'locales', 'channels', 'tags', 'requesterIds', 'requestDate', 'dueDate'):
        require(before.get(key) == after.get(key), 'Scope narrowing changed another business field: ' + key)
    authority_path = inside(root, decision.get('scope_revision_authority', 'missing'))
    authority = read_json(authority_path)
    budget = read_json(inside(root, 'state/budgets/' + previous['budget'] + '.json'))
    expected = {'authority': 'user', 'action': 'accept_funded_narration_only_revision',
                'requirement_id': previous['requirement_id'],
                'previous_content_version': previous['content_version'],
                'next_content_version': snap['content_version'], 'budget_id': previous['budget'],
                'credit_limit': budget['credit_limit']}
    require(all(authority.get(key) == value for key, value in expected.items())
            and authority.get('authorization_ref') and authority.get('source_quote'),
            'Funded scope narrowing needs the exact human authority; platform text is not authorization')
    require(sorted(authority.get('targets', [])) == sorted(targets)
            and sorted(authority.get('source_sha256s', [])) == sorted(
                v['source']['sha256'] for v in previous['videos']), 'Scope authority source/languages changed')
    archive = folder / 'revisions' / (object_hash(previous) + '.json')
    if archive.exists():
        require(read_json(archive) == previous, 'Existing scope-revision archive changed')
    else:
        write_json(archive, previous)
    result = copy.deepcopy(previous)
    result.setdefault('revision_history', []).append({
        'content_version': previous['content_version'], 'new_content_version': snap['content_version'],
        'path': archive.relative_to(root).as_posix(), 'scope': 'ad_narration_only',
        'reason': decision['revision_reason'], 'reviewed_at': utc_now(),
        'authority': {'path': authority_path.relative_to(root).as_posix(),
                      'sha256': file_hash(authority_path)}, 'budget_preserved': previous['budget']})
    result['content_version'] = snap['content_version']
    result['production_scope'] = {'visual': 'preserve_source', 'speech': 'advertising_narration_only',
                                  'source_quote': phrase, 'authority_ref': authority['authorization_ref']}
    return result
