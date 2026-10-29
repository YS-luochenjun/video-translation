"""Narrow review of quantity corrections without replacing funded production."""
from .common import require


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
