"""Read-only Fireplay material query planning and local launch observations."""
import argparse
import json
from pathlib import Path

from collector import Ledger
from console_requirements import verified_material_ids
from store import Store
from video_localizer.common import lock, write_json
from video_localizer.ledger import now, seconds


WORKSPACE = Path(__file__).resolve().parents[1]
OBSERVATIONS = 'state/fireplay/monitor/material-launch.json'
BATCH_SIZE = 12


def allowed_materials(store, ledger):
    identifiers = set()
    for row in ledger.view(current_only=True, activity=False)['requirements']:
        identifiers.update(verified_material_ids(store, row.get('platform') or {}))
    return identifiers


def plan(store, ledger):
    previous = store.read(OBSERVATIONS).get('materials', {})
    identifiers = sorted(allowed_materials(store, ledger),
                         key=lambda key: (seconds(previous.get(key, {}).get('checked_at')) or 0, key))
    return [
        {'materialIds': identifiers[start:start+BATCH_SIZE], 'scope': 'all', 'statsWindow': 'all_time',
         'response_detail': 'summary', 'limit': BATCH_SIZE}
        for start in range(0, min(len(identifiers), 2*BATCH_SIZE), BATCH_SIZE)
    ]


def record(store, ledger, response):
    meta = response.get('query_meta', {})
    filters = meta.get('filters', {})
    requested = filters.get('materialIds') or []
    observed_at = meta.get('queried_at')
    observed_seconds = seconds(observed_at)
    allowed = allowed_materials(store, ledger)
    if (filters.get('scope') != 'all' or filters.get('statsWindow') != 'all_time'
            or filters.get('launchStatus') or filters.get('resultSource') != 'all' or filters.get('page') != 1
            or not 0 < len(requested) <= BATCH_SIZE or len(set(requested)) != len(requested)
            or not set(requested) <= allowed or meta.get('launch_status_scope') is not None
            or response.get('has_more') is not False or meta.get('truncated') is not False
            or observed_seconds is None or not -60 <= seconds(now())-observed_seconds <= 1800
            or response.get('total') != len(response.get('items') or [])):
        raise ValueError('素材投放查询范围或回执不完整')
    updates = {}
    for item in response.get('items', []):
        identifier = item.get('id')
        observed = item.get('hasLaunchRecord')
        if identifier not in requested or identifier in updates or type(observed) is not bool:
            raise ValueError('素材投放回执缺少精确状态')
        updates[identifier] = {'has_launch_record': observed, 'observed_at': observed_at}
    path = store.path(OBSERVATIONS)
    with lock(path.with_suffix('.lock')):
        current = store.read(OBSERVATIONS).get('materials', {})
        fresh = {key: {**current.get(key, {}), **updates.get(key, {}), 'checked_at': observed_at}
                 for key in requested if observed_seconds > (seconds(current.get(key, {}).get('checked_at')) or 0)}
        if fresh:
            write_json(path, {'materials': current | fresh})
    return {'updated': len(updates.keys() & fresh.keys()), 'returned': len(updates),
            'requested': len(requested), 'observed_at': observed_at}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('plan', 'record'))
    parser.add_argument('--response', type=Path)
    args = parser.parse_args()
    if args.action == 'record' and args.response is None:
        parser.error('record requires --response')
    store, ledger = Store(WORKSPACE), Ledger(WORKSPACE)
    if args.action == 'plan':
        value = plan(store, ledger)
    else:
        value = record(store, ledger, json.loads(args.response.read_text(encoding='utf-8')))
    print(json.dumps(value, ensure_ascii=False))


if __name__ == '__main__':
    main()
