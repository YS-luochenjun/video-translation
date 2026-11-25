"""Read-only requirement board, bound to saved scope and platform evidence."""
import re
from datetime import datetime, timezone
from pathlib import Path

from store import clean
from video_localizer.common import WorkflowError
from video_localizer.fireplay_submission import completion_gate
from video_localizer.ledger import Ledger, platform_completed, progress_state

CODE = re.compile(r'[A-Za-z]{2,8}-\d{8}-\d{3}')


def sha(store, path):
    try: return store.sha(path)
    except (ValueError, OSError): return None


def epoch(value):
    try: return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except (TypeError, ValueError): return 0


def count(value):
    return value if type(value) is int and value >= 0 else None


def monitor_rows(store):
    state = store.read('state/fireplay/monitor/state.json')
    rows = state.get('requirements') if isinstance(state, dict) else None
    return rows if isinstance(rows, dict) else {}


def latest_platform_status(monitored, requirement_id, code, status, observed_at):
    entry = monitored.get(requirement_id)
    row = entry.get('row') if isinstance(entry, dict) else None
    if (requirement_id and isinstance(row, dict) and row.get('id') == requirement_id and row.get('code') == code
            and row.get('status') and epoch(entry.get('last_seen_at')) > epoch(observed_at)):
        return row['status'], entry['last_seen_at']
    return status, observed_at


def publication(store, path, request):
    check_path = str(Path(path).parent/'completion-check.json')
    check = store.read(check_path)
    result = {'state': 'unrecorded', 'verified': None, 'expected': None,
              'checked_at': check.get('checked_at'), 'platform_read_at': check.get('platform_read_at'),
              'closed_at': None, 'check_path': check_path if check else None}
    if not check: return result
    same_scope = (check.get('requirement_id') == request.get('requirement_id')
                  and check.get('code') == request.get('code')
                  and bool(request.get('content_version'))
                  and check.get('content_version') == request.get('content_version'))
    total, verified = check.get('expected_count'), check.get('verified_count')
    valid_counts = (type(total) is int and type(verified) is int and 0 <= verified <= total and total > 0)
    if not same_scope or not valid_counts:
        result['state'] = 'stale'
        return result
    request_hash = sha(store, path)
    exact_request = bool(request_hash) and check.get('request_sha256') == request_hash
    complete = check.get('complete') is True and verified == total and not check.get('missing')
    pointer = store.read(str(Path(path).parent/'delivery-closure.json'))
    receipt_path = pointer.get('receipt')
    closure = None
    check_hash = None
    if complete and isinstance(receipt_path, str) and receipt_path.startswith(str(Path(path).parent/'delivery-closures')+'/'):
        receipt = store.read(receipt_path)
        receipt_hash = sha(store, receipt_path)
        check_hash = sha(store, check_path)
        if (receipt_hash and pointer.get('sha256') == receipt_hash
                and check_hash and receipt.get('completion_check_sha256') == check_hash
                and receipt.get('requirement_id') == request.get('requirement_id')
                and receipt.get('content_version') == request.get('content_version')
                and receipt.get('complete') is True):
            closure = receipt
    if not exact_request:
        if (not closure or closure.get('code') != request['code']
                or closure.get('expected_count') != total or closure.get('verified_count') != verified
                or not request_hash):
            result['state'] = 'stale'
            return result
        try:
            gate = completion_gate(request, store.root)
        except (WorkflowError, OSError, ValueError, KeyError, TypeError, AttributeError):
            gate = {}
        if (not gate.get('can_close') or gate.get('expected_count') != total
                or sha(store, path) != request_hash or sha(store, check_path) != check_hash):
            result['state'] = 'stale'
            return result
    state = 'closed' if closure else 'verified' if complete else 'partial'
    result.update(state=state, verified=verified, expected=total, closed_at=closure.get('closed_at') if closure else None)
    return result


def verified_items(store, platform):
    if platform.get('verified') is None or not platform.get('check_path'):
        return []
    verified = store.read(platform['check_path']).get('verified') or []
    if not isinstance(verified, list) or len(verified) != platform['verified']:
        return []
    return [item for item in verified if isinstance(item, dict)
            and re.fullmatch(r'[0-9a-f-]{36}', str(item.get('material_id', '')))]


def verified_material_ids(store, platform):
    return {item['material_id'] for item in verified_items(store, platform)}


def material_launch_summary(material_ids, observations):
    if not material_ids:
        return None
    dated = [observations[identifier] for identifier in material_ids if identifier in observations]
    dated = [row for row in dated if row.get('observed_at') == row.get('checked_at')
             and type(row.get('has_launch_record')) is bool]
    count_launched = sum(row['has_launch_record'] for row in dated)
    timestamps = [row['observed_at'] for row in dated if epoch(row.get('observed_at'))]
    return {'materials': len(material_ids), 'checked': len(dated), 'launched': count_launched,
            'observed_at': min(timestamps, key=epoch, default=None)}


def add_ledger_evidence(store, rows, *, include_description=False):
    monitored = monitor_rows(store)
    observations = store.read('state/fireplay/monitor/material-launch.json').get('materials', {})
    for row in rows:
        if row.get('origin') != 'fireplay' or not CODE.fullmatch(row['code']):
            continue
        path = f"state/fireplay/{row['code']}/request.json"
        request = store.read(path)
        if row['id'] != 'fireplay:' + str(request.get('requirement_id')) or request.get('code') != row['code']:
            continue
        snapshot = request.get('snapshot', {}).get('row', {})
        row['platform_status'], row['platform_refreshed_at'] = latest_platform_status(
            monitored, request['requirement_id'], row['code'], snapshot.get('status') or row.get('platform_status'),
            request.get('refreshed_at') or row.get('platform_refreshed_at'))
        if request.get('content_version') == row.get('content_version'):
            platform = publication(store, path, request)
            if platform.get('expected') in (None, row['task_count']):
                row['platform'] = platform
                row['launch'] = material_launch_summary(verified_material_ids(store, platform), observations)
            else:
                row['platform'] = {**platform, 'state': 'stale', 'verified': None, 'expected': None, 'closed_at': None}
        else:
            row['platform'] = {**(row.get('platform') or {}), 'state': 'stale',
                               'verified': None, 'expected': None, 'closed_at': None}
        if include_description:
            row['description'] = str(snapshot.get('description') or snapshot.get('refText') or '')[:6000]
        row['progress_state'] = progress_state(row)


def project_requirements(data):
    threads = {t['id']: t for t in data.threads()}
    registered = {}
    for path in data.store.glob('state/fireplay', '*/request.json'):
        r = data.store.read(path)
        if (r.get('requirement_id') and CODE.fullmatch(str(r.get('code', '')))
                and Path(path).parent.name == r['code']):
            registered['fireplay:'+r['requirement_id']] = (path, r)
    cohort = data.store.read('config/ledger.json').get('cohort', {})
    exclusions = data.store.read('state/ledger/cohort-overrides.json').get('time_exclusions', {})
    ledger = {r['id']: r for r in data.ledger_rows() if r.get('countable') is not False}
    monitored = monitor_rows(data.store)
    launch_observations = data.store.read('state/fireplay/monitor/material-launch.json').get('materials', {})
    result = []
    for identifier in sorted(ledger.keys() | registered.keys()):
        old = ledger.get(identifier, {})
        path, request = registered.get(identifier, (None, {}))
        scope_record = old or {'id': identifier, 'received_at': request.get('created_at')}
        if not Ledger.in_cohort(scope_record, cohort, exclusions):
            continue
        code = request.get('code') or old.get('code') or identifier
        source = request.get('snapshot', {}).get('row', {})
        brief = request.get('snapshot', {}).get('brief', {})
        # Never combine an old ledger's output counts with a revised input scope.
        current = not request or bool(old) and old.get('content_version') == request.get('content_version')
        total = count(old.get('task_count')) if current else None
        outputs = count(old.get('output_count')) if current else None
        quality = count(old.get('quality_count')) if current else None
        issues = count(old.get('issue_count')) if current else None
        videos = request.get('videos') or old.get('videos') or []
        targets = sorted({str(t) for v in videos for t in (v.get('targets') or request.get('targets') or [])})
        if request and not total:
            total = sum(len(set(v.get('targets') or request.get('targets') or [])) for v in videos) or None
        candidates = list(old.get('threads') or [])
        candidates += [request.get('chat') or {}]+[v.get('chat') or {} for v in videos]
        own_threads = {}
        for t in candidates:
            tid = t.get('threadId') or t.get('id')
            if tid in threads:
                original = threads[tid]
                own_threads[tid] = {'id': tid, 'title': clean(original.get('name') or original.get('title') or tid),
                                    'archived': bool(original.get('archived'))}
        question_at = max((data.last_user_message_at(threads[tid]) or 0 for tid in own_threads), default=0)
        blockers = list(request.get('blockers') or old.get('blockers') or [])
        if old.get('block_reason'): blockers.append(old['block_reason'])
        platform = publication(data.store, path, request) if path else {'state': 'unrecorded', 'verified': None, 'expected': None}
        if total and platform.get('expected') is not None and platform['expected'] != total:
            platform.update(state='stale', verified=None, expected=None, closed_at=None)
        platform_status, platform_at = latest_platform_status(
            monitored, request.get('requirement_id'), code,
            source.get('status') or old.get('platform_status'),
            request.get('refreshed_at') or old.get('platform_refreshed_at'),
        )
        expired = (old.get('state') == 'expired' or total and outputs == 0
                   and (old.get('stage_counts') or {}).get('expired') == total)
        state = ('closed' if platform['state'] == 'closed'
                 else 'verified' if platform['state'] == 'verified'
                 else 'completed' if platform_completed(platform_status)
                 else 'attention' if blockers
                 else 'unknown' if not current else 'expired' if expired
                 else 'output' if total and outputs is not None and outputs >= total
                 else 'working' if old.get('state') in {'executing', 'partial', 'working'}
                 else 'waiting' if old.get('state') in {'waiting', 'queued', 'discovered', 'received'} or own_threads
                 else 'unknown')
        publication_blocked = old.get('publication_blocked_count', 0) if current else 0
        progress = progress_state({
            'origin': 'fireplay' if request else old.get('origin'),
            'state': old.get('state') if current else None, 'platform': platform,
            'task_count': total, 'output_count': outputs, 'platform_status': platform_status,
            'blockers': blockers, 'publication_blocked_count': publication_blocked,
        })
        result.append(clean({'id': identifier, 'code': code,
            'title': brief.get('title') or source.get('title') or next(iter(str(source.get('description') or '').splitlines()), '')[:120] or old.get('title') or code,
            'state': state, 'ledger_state': old.get('state'), 'scope_current': current,
            'progress_state': progress, 'has_ledger': bool(old),
            'first_started_at': old.get('first_started_at') if current else None,
            'complete_at': old.get('complete_at') if current else None,
            'publication_blocked_count': publication_blocked,
            'time_exclusion': old.get('time_exclusion') if current else None,
            'priority': source.get('priority'), 'source_count': len(videos), 'targets': targets,
            'task_count': total, 'output_count': outputs, 'quality_count': quality, 'issue_count': issues,
            'stage_counts': {str(k): v for k, v in (old.get('stage_counts') or {}).items() if count(v) is not None} if current else {}, 'threads': list(own_threads.values()),
            'last_user_message_at': question_at or None,
            'received_at': request.get('created_at') or old.get('received_at'),
            'last_activity_at': old.get('last_activity_at'), 'platform': platform,
            'launch': material_launch_summary(verified_material_ids(data.store, platform), launch_observations),
            'platform_status': platform_status, 'platform_snapshot_at': platform_at,
            'blockers': blockers, 'request_path': path, 'requirement_id': request.get('requirement_id'),
            'description': str(source.get('description') or source.get('refText') or '')[:6000],
            'sources': [{'index': v.get('index') or v.get('id'), 'title': v.get('title'),
                         'targets': v.get('targets') or request.get('targets') or []} for v in videos]}))
    # Same stable ordering principle as chats: execution changes never move a row.
    result.sort(key=lambda r: (-(r['last_user_message_at'] or epoch(r.get('received_at'))), r['code']))
    summary = {'total': len(result), **{s: sum(r['state'] == s for r in result)
               for s in ('waiting', 'working', 'output', 'verified', 'closed', 'completed', 'attention', 'unknown', 'expired')}}
    return {'requirements': result, 'summary': summary, 'observed_at': datetime.now(timezone.utc).isoformat(),
            'scope': '本机已登记需求和现有台账；平台栏为版本绑定的已保存核验，不代表实时平台查询或YouTube成功'}
