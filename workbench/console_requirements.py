"""Read-only requirement board, bound to saved scope and platform evidence."""
import re
from datetime import datetime, timezone
from pathlib import Path

from store import clean

CODE = re.compile(r'[A-Za-z]{2,8}-\d{8}-\d{3}')


def sha(store, path):
    try: return store.sha(path)
    except (ValueError, OSError): return None


def epoch(value):
    try: return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except (TypeError, ValueError): return 0


def count(value):
    return value if type(value) is int and value >= 0 else None


def publication(store, path, request):
    check_path = str(Path(path).parent/'completion-check.json')
    check = store.read(check_path)
    result = {'state': 'unrecorded', 'verified': None, 'expected': None,
              'checked_at': check.get('checked_at'), 'platform_read_at': check.get('platform_read_at'),
              'closed_at': None, 'check_path': check_path if check else None}
    if not check: return result
    bound = (check.get('requirement_id') == request.get('requirement_id')
             and check.get('code') == request.get('code')
             and bool(request.get('content_version'))
             and check.get('content_version') == request.get('content_version')
             and check.get('request_sha256') == sha(store, path))
    total, verified = check.get('expected_count'), check.get('verified_count')
    valid_counts = (type(total) is int and type(verified) is int and 0 <= verified <= total and total > 0)
    if not bound or not valid_counts:
        result['state'] = 'stale'
        return result
    complete = check.get('complete') is True and verified == total and not check.get('missing')
    result.update(state='verified' if complete else 'partial', verified=verified, expected=total)
    pointer = store.read(str(Path(path).parent/'delivery-closure.json'))
    receipt_path = pointer.get('receipt')
    if complete and isinstance(receipt_path, str) and receipt_path.startswith(str(Path(path).parent/'delivery-closures')+'/'):
        receipt = store.read(receipt_path)
        if (pointer.get('sha256') == sha(store, receipt_path)
                and receipt.get('completion_check_sha256') == sha(store, check_path)
                and receipt.get('requirement_id') == request.get('requirement_id')
                and receipt.get('content_version') == request.get('content_version')
                and receipt.get('complete') is True):
            result.update(state='closed', closed_at=receipt.get('closed_at'))
    return result


def project_requirements(data):
    threads = {t['id']: t for t in data.threads()}
    registered = {}
    for path in data.store.glob('state/fireplay', '*/request.json'):
        r = data.store.read(path)
        if (r.get('requirement_id') and CODE.fullmatch(str(r.get('code', '')))
                and Path(path).parent.name == r['code']):
            registered['fireplay:'+r['requirement_id']] = (path, r)
    ledger = {r['id']: r for r in data.ledger_rows() if r.get('countable') is not False}
    result = []
    for identifier in sorted(ledger.keys() | registered.keys()):
        old = ledger.get(identifier, {})
        path, request = registered.get(identifier, (None, {}))
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
        expired = (old.get('state') == 'expired' or total and outputs == 0
                   and (old.get('stage_counts') or {}).get('expired') == total)
        state = ('attention' if blockers else 'closed' if platform['state'] == 'closed'
                 else 'verified' if platform['state'] == 'verified'
                 else 'unknown' if not current else 'expired' if expired
                 else 'output' if total and outputs is not None and outputs >= total
                 else 'working' if old.get('state') in {'executing', 'partial', 'working'}
                 else 'waiting' if old.get('state') in {'waiting', 'queued', 'discovered', 'received'} or own_threads
                 else 'unknown')
        result.append(clean({'id': identifier, 'code': code,
            'title': brief.get('title') or source.get('title') or next(iter(str(source.get('description') or '').splitlines()), '')[:120] or old.get('title') or code,
            'state': state, 'ledger_state': old.get('state'), 'scope_current': current,
            'priority': source.get('priority'), 'source_count': len(videos), 'targets': targets,
            'task_count': total, 'output_count': outputs, 'quality_count': quality, 'issue_count': issues,
            'stage_counts': {str(k): v for k, v in (old.get('stage_counts') or {}).items() if count(v) is not None} if current else {}, 'threads': list(own_threads.values()),
            'last_user_message_at': question_at or None,
            'received_at': request.get('created_at') or old.get('received_at'),
            'last_activity_at': old.get('last_activity_at'), 'platform': platform,
            'platform_status': source.get('status') or old.get('platform_status'),
            'platform_snapshot_at': request.get('refreshed_at') or old.get('platform_refreshed_at'),
            'blockers': blockers, 'request_path': path, 'requirement_id': request.get('requirement_id'),
            'description': str(source.get('description') or source.get('refText') or '')[:6000],
            'sources': [{'index': v.get('index') or v.get('id'), 'title': v.get('title'),
                         'targets': v.get('targets') or request.get('targets') or []} for v in videos]}))
    # Same stable ordering principle as chats: execution changes never move a row.
    result.sort(key=lambda r: (-(r['last_user_message_at'] or epoch(r.get('received_at'))), r['code']))
    summary = {'total': len(result), **{s: sum(r['state'] == s for r in result)
               for s in ('waiting', 'working', 'output', 'verified', 'closed', 'attention', 'unknown', 'expired')}}
    return {'requirements': result, 'summary': summary, 'observed_at': datetime.now(timezone.utc).isoformat(),
            'scope': '本机已登记需求和现有台账；平台栏为版本绑定的已保存核验，不代表实时平台查询或YouTube成功'}
