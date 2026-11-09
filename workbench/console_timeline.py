"""Read-only chronological chains. Gaps are elapsed unknown time, never work."""
from datetime import datetime, timezone
import json
import sqlite3

from store import clean


def epoch(value):
    try: return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError, AttributeError): return None


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def chains(events, clock):
    timers, agents, executions = [], {}, {}
    seen = set()
    for event in sorted(events, key=lambda e: (epoch(e.get('occurred_at')) or epoch(e.get('recorded_at')) or 0, e.get('id', ''))):
        d, kind = event.get('data', {}), event.get('kind')
        at = epoch(event.get('occurred_at')) or epoch(event.get('recorded_at'))
        if not isinstance(d, dict) or at is None or at > clock: continue
        evidence = d.get('evidence') or event.get('id')
        if kind == 'stage_recorded':
            if d.get('parent_id') or evidence in seen: continue
            seen.add(evidence)
            start, end = epoch(d.get('started_at')), epoch(d.get('ended_at'))
            if start is None or end is None or not start <= end <= clock: continue
            timers.append({'title': clean(d.get('stage') or '未命名执行'), 'start': iso(start), 'end': iso(end),
                           'seconds': round(end-start, 3), 'state': clean(d.get('status') or 'recorded'),
                           'basis': '脚本开始与结束记录', 'evidence': [evidence]})
        elif kind.startswith('executor.'):
            key = d.get('execution_id')
            if not key: continue
            x = executions.setdefault(key, {'start': None, 'last': at, 'end': None, 'title': clean(d.get('stage') or '执行中'), 'evidence': []})
            x['last'] = max(x['last'], at); x['evidence'].append(evidence)
            if kind == 'executor.started': x['start'] = at
            if kind in {'executor.finished', 'executor.failed'}:
                x['end'] = at
                x['state'] = 'failed' if kind == 'executor.failed' else 'completed'
        elif kind in {'claim', 'stage', 'heartbeat', 'block', 'resume', 'release'}:
            scope = d.get('video_id') or '*'
            stream = agents.setdefault(scope, [])
            # Repeated activity confirms the existing stage rather than creating fake nodes.
            title = clean(d.get('stage') or ('等待解除' if kind == 'resume' else '停止负责' if kind == 'release' else '阶段未记录'))
            state = 'waiting' if kind == 'block' else 'stopped' if kind == 'release' else 'recorded'
            if stream and stream[-1]['title'] == title and stream[-1]['state'] == state:
                stream[-1]['last_confirmed_at'] = iso(at)
                stream[-1]['evidence'].append(evidence)
            else:
                if stream:
                    stream[-1]['end'] = iso(at)
                    stream[-1]['seconds'] = round(at-epoch(stream[-1]['start']), 3)
                stream.append({'title': title, 'start': iso(at), 'end': None, 'seconds': None, 'state': state,
                               'last_confirmed_at': iso(at), 'basis': '两次阶段登记之间的历时，包含未分类过程；不是纯工时',
                               'evidence': [evidence]})

    for x in executions.values():
        if x['start'] is None: continue
        # A completed timing record can outlive a missing executor finish event.
        if any(t['title'] == x['title'] and abs(epoch(t['start'])-x['start']) < 3 for t in timers): continue
        fresh = x['end'] is None and clock-x['last'] <= 180
        end = x['end'] if x['end'] is not None else clock if fresh else x['last']
        timers.append({'title': x['title'], 'start': iso(x['start']), 'end': iso(max(end, x['start'])),
                       'seconds': round(max(0, end-x['start']), 3), 'state': x.get('state') or ('running' if fresh else 'unconfirmed'),
                       'last_confirmed_at': iso(x['last']), 'basis': '执行器真实开始 / 结束记录' if x['end'] is not None else '执行器真实活动；超过180秒未确认则停止累计',
                       'evidence': x['evidence']})
    lanes = []
    for scope, rows in agents.items():
        last = rows[-1]
        fresh = clock-epoch(last['last_confirmed_at']) <= 180 and last['state'] != 'stopped'
        last['state'] = ('waiting' if last['state'] == 'waiting' else 'running') if fresh else 'unconfirmed' if last['state'] != 'stopped' else 'stopped'
        # This is time since the last phase entry, explicitly not an activity duration.
        last['end'] = iso(clock if fresh else epoch(last['last_confirmed_at']))
        last['seconds'] = round(max(0, epoch(last['end'])-epoch(last['start'])), 3)
        lanes.append({'title': 'Agent阶段 · '+('整项 / 会话' if scope == '*' else scope), 'kind': 'agent', 'items': rows})
    timers.sort(key=lambda r: (r['start'], r['end']))
    frontier = None
    for row in timers:
        start, end = epoch(row['start']), epoch(row['end'])
        row['gap_before_seconds'] = round(max(0, start-frontier), 3) if frontier is not None else None
        row['overlap_seconds'] = round(max(0, min(frontier, end)-start), 3) if frontier is not None else 0
        frontier = max(frontier or end, end)
    if timers: lanes.append({'title': '脚本执行 · 当前原片 / 语种', 'kind': 'executor', 'items': timers})
    return lanes


def project_timeline(data, thread_id, run_id, requirements):
    events = []
    db_path = data.root/'state/ledger/ledger.sqlite3'
    truncated = False
    if db_path.is_file():
        with sqlite3.connect(db_path.as_uri()+'?mode=ro', uri=True, timeout=3) as db:
            db.row_factory = sqlite3.Row
            if run_id:
                rows = db.execute("SELECT * FROM events WHERE run_id=? AND (kind='stage_recorded' OR kind LIKE 'executor.%') ORDER BY COALESCE(occurred_at,recorded_at) DESC LIMIT 2001", (run_id,)).fetchall()
                truncated = len(rows) > 2000
                events.extend({**dict(r), 'data': json.loads(r['data'])} for r in rows[:2000])
            for req in requirements:
                # Management events have no run; require this exact original chat owner.
                rows = db.execute("SELECT * FROM events WHERE requirement_id=? AND kind IN ('claim','stage','heartbeat','block','resume','release') ORDER BY COALESCE(occurred_at,recorded_at)", (req['id'],)).fetchall()
                for r in rows:
                    value = json.loads(r['data'])
                    if value.get('owner') == thread_id or value.get('session') == thread_id:
                        events.append({**dict(r), 'data': value})
    # Fresh canonical timing files may not have been imported by the collector yet.
    if run_id:
        for path in data.store.glob(f'state/timing/{run_id}', '*.json'):
            value = data.store.read(path)
            if isinstance(value, dict) and value.get('run') == run_id:
                events.append({'id': 'timing:'+str(value.get('id')), 'kind': 'stage_recorded',
                               'occurred_at': value.get('ended_at') or value.get('started_at'), 'data': {**value, 'evidence': path}})
    clock = datetime.now(timezone.utc).timestamp()
    return {'lanes': chains(events, clock), 'observed_at': iso(clock), 'truncated': truncated,
            'note': '按实际时间排列，返工可重复节点。Agent为阶段登记间历时，脚本为开始/结束计时；两者有重叠，不能相加。节点间空白不算工作，未确认活动不持续累计。'}
