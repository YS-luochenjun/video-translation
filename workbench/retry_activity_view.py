"""Read project retry receipts and incrementally import recognized host events."""
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
import time

from video_localizer.retry_activity import database, job_events, previous_job, timestamp, write_events


PAGE_SIZE = 30
HOST_LOOKBACK = 7 * 86400
LOG_TARGET = 'codex_core::responses_retry'
RETRY_NUMBER = re.compile(r'retrying sampling request \((\d+)/(\d+) in ')
CURSOR = re.compile(r'([0-9]{1,15}):([A-Za-z0-9:_-]{1,220})')
BIND_RECEIPT = re.compile(r'([1-9]\d*)-bind-[0-9a-f]{64}\.json')
SOURCES = ('codex', 'kie', 'fireplay')
SCOPE_JOIN = """
    LEFT JOIN retry_owners ON retry_owners.source=json_extract(activity.data,'$.source')
        AND retry_owners.reference=COALESCE(json_extract(activity.data,'$.thread'),json_extract(activity.data,'$.run'))
"""
OWNER = "COALESCE(json_extract(activity.data,'$.requirement'),retry_owners.requirement)"


def checkpoint(connection, name, default=None):
    row = connection.execute('SELECT value FROM checkpoints WHERE name=?', (name,)).fetchone()
    return json.loads(row[0]) if row else default


def save_checkpoint(connection, name, value):
    connection.execute('INSERT OR REPLACE INTO checkpoints VALUES(?,?)', (name, json.dumps(value)))


def import_jobs(root, connection):
    saved = checkpoint(connection, 'kie-job-history')
    if saved:
        return saved['complete']
    events = []
    complete = True
    for path in (root / 'runs').glob('*/jobs/*.json'):
        if path.is_symlink() or not path.resolve().is_relative_to(root / 'runs'):
            continue
        try:
            job = json.loads(path.read_text(encoding='utf-8-sig'))
            if isinstance(job, dict) and path.stem == job.get('id'):
                events.extend(job_events(path.parent.parent.name, job, previous_job(path.parent, job)))
        except FileNotFoundError:
            continue
        except (OSError, ValueError, TypeError, AttributeError):
            complete = False
    with connection:
        connection.executemany('INSERT OR IGNORE INTO activity(id,at,kind,data) VALUES(?,?,?,?)', (
            (event['id'], event['at'], event['kind'], json.dumps({
                key: value for key, value in event.items() if key != 'at'
            }, separators=(',', ':'))) for event in events
        ))
        save_checkpoint(connection, 'kie-job-history', {'complete': complete})
    return complete


def open_host(path):
    return sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=.15)


def import_retries(home, connection, threads):
    path = home / 'logs_2.sqlite'
    identity = f'{path.stat().st_dev}:{path.stat().st_ino}'
    cutoff = int(time.time()) - HOST_LOOKBACK
    saved = checkpoint(connection, 'codex-retries', {})
    offsets = saved.get('offsets', {}) if saved.get('identity') == identity else {}
    events, next_offsets = [], {}
    with closing(open_host(path)) as host:
        for thread in threads:
            offset = offsets.get(thread, 0)
            rows = host.execute("""
                SELECT id, ts, ts_nanos, feedback_log_body FROM logs
                WHERE thread_id=? AND id>? AND ts>=? AND level='WARN' AND target=?
                ORDER BY id LIMIT 200
            """, (thread, offset, cutoff if not offset else 0, LOG_TARGET)).fetchall()
            next_offsets[thread] = rows[-1][0] if rows else offset
            for log_id, seconds, nanos, body in rows:
                matched = RETRY_NUMBER.search(body or '')
                if matched:
                    events.append({
                        'id': f'codex-log:{identity}:{log_id}', 'at': seconds * 1000 + nanos // 1000000,
                        'source': 'codex', 'thread': thread, 'kind': 'retry', 'operation': 'sampling',
                        'attempt': int(matched[1]), 'max_attempts': int(matched[2]),
                        'reason': 'sampling_error', 'outcome': 'observed',
                    })
    status = {'identity': identity, 'offsets': next_offsets}
    if events or status != saved:
        with connection:
            write_events(connection, events)
            save_checkpoint(connection, 'codex-retries', status)


def import_failures(home, connection, threads):
    cutoff = int(time.time()) - HOST_LOOKBACK
    saved = checkpoint(connection, 'codex-failures', {})
    events, next_offsets = [], {}
    with closing(open_host(home / 'thread_history_1.sqlite')) as host:
        for thread in threads:
            offset = saved.get(thread, cutoff)
            rows = host.execute("""
                SELECT turn_id, completed_at FROM thread_turns
                WHERE thread_id=? AND status='failed' AND completed_at>=?
                ORDER BY completed_at, turn_id
            """, (thread, offset)).fetchall()
            next_offsets[thread] = rows[-1][1] if rows else offset
            for turn, ended in rows:
                at = ended * 1000
                events.append({
                    'id': f'codex-turn:{thread}:{turn}', 'at': at, 'source': 'codex',
                    'thread': thread, 'kind': 'failure', 'operation': 'turn',
                    'reason': 'turn_failed', 'outcome': 'failed',
                })
    if events or next_offsets != saved:
        with connection:
            write_events(connection, events)
            if next_offsets != saved:
                save_checkpoint(connection, 'codex-failures', next_offsets)


def remember_owners(connection, console, ledger):
    with ledger.connection() as existing:
        requirements = {row['id']: json.loads(row['data']) for row in existing.execute(
            'SELECT id,data FROM requirements WHERE json_extract(data,\'$.countable\') IS NOT 0')}
        owners = {(source, reference, requirement) for source, reference, requirement in existing.execute("""
            SELECT 'kie', runs.value, tasks.requirement_id FROM tasks, json_each(tasks.data,'$.runs') AS runs
            WHERE runs.type='text'
        """) if requirement in requirements}
    for identifier, row in requirements.items():
        for thread in row.get('threads', []):
            reference = thread.get('threadId') or thread.get('id')
            if reference:
                owners.add(('codex', reference, identifier))
        for budget_id in row.get('budget_ids', []):
            if not re.fullmatch(r'[a-f0-9]{32,64}', budget_id):
                continue
            budget = console.store.read(f'state/budgets/{budget_id}.json')
            if budget.get('id') == budget_id and budget.get('scope_requirement') == row['code']:
                for run in budget.get('runs', {}):
                    owners.add(('kie', run, identifier))
    connection.execute("""
        CREATE TABLE IF NOT EXISTS retry_owners(
            source TEXT, reference TEXT, requirement TEXT, PRIMARY KEY(source,reference)
        )
    """)
    prior = {(source, reference): identifier for source, reference, identifier in connection.execute(
        'SELECT source,reference,requirement FROM retry_owners')}
    with connection:
        connection.executemany("""
            INSERT INTO retry_owners VALUES(?,?,?)
            ON CONFLICT(source,reference) DO UPDATE SET requirement=NULL
            WHERE retry_owners.requirement<>excluded.requirement
        """, [(source, reference, identifier) for source, reference, identifier in sorted(owners)
              if (source, reference) not in prior or prior[source, reference] not in (None, identifier)])


def fireplay_events(outbox, code):
    requirement = outbox.get('requirement_id')
    if not isinstance(requirement, str) or not requirement or outbox.get('code') != code:
        return []
    operations = outbox.get('operations', {})
    packages = outbox.get('packages', [])
    history = outbox.get('upload_attempts', {})
    replacements = outbox.get('transport_history', [])
    events = {}
    for offset, package in enumerate(packages, 1):
        key = f'upload-{offset}'
        attempts = history.get(key, [])
        replacements_for_package = [
            entry for entry in replacements if (entry.get('prior_operation') or {}).get('id') == key
        ]
        previous = [(entry.get('previous_operation') or entry, index + 1) for index, entry in enumerate(attempts)]
        previous.extend((entry['prior_operation'], 1) for entry in replacements_for_package)
        if key in operations:
            previous.append((operations[key], len(attempts) + 1))
        for operation, inferred in previous:
            dispatched = operation.get('dispatched_at')
            at = timestamp(dispatched) if dispatched else None
            if at is None:
                continue
            retry = (operation.get('attempt') or inferred) - 1
            retry += sum(bool(entry.get('recorded_at') and entry['recorded_at'] <= dispatched)
                         for entry in replacements_for_package)
            if retry < 1:
                continue
            video = outbox.get('video_index') or package.get('video_index')
            fingerprint = sha256(json.dumps([requirement, video, key, dispatched, retry]).encode()).hexdigest()
            identifier = f'fireplay-upload:{fingerprint}'
            later = next((entry for entry in attempts if (entry.get('previous_operation') or entry).get('dispatched_at') == dispatched), {})
            reason = 'upload_timeout' if any(entry.get('timeout_evidence') for entry in attempts[:retry]) else (
                'upload_replaced' if replacements_for_package else 'previous_attempt')
            state = operation.get('state')
            events[identifier] = {
                'id': identifier, 'at': at, 'source': 'fireplay', 'requirement': f'fireplay:{requirement}',
                'kind': 'retry', 'operation': 'upload', 'attempt': retry, 'reason': reason,
                'video_index': video, 'locale': package.get('locale'),
                'outcome': 'success' if state == 'verified' else 'timeout' if later.get('timeout_evidence')
                else 'failed' if state == 'retryable_conflict' else 'unknown',
            }
    return list(events.values())


def fireplay_bind_retry(store, path, receipt):
    dispatch = receipt.get('dispatch') or {}
    previous = dispatch.get('prior_operation') or {}
    if (previous.get('id') != 'bind' or previous.get('tool') != 'requirement_bind_materials'
            or previous.get('state') != 'unknown'):
        return []
    prior_path = Path(previous.get('last_observed_receipt') or '')
    if (prior_path.parent != path.parent or not BIND_RECEIPT.fullmatch(prior_path.name)
            or prior_path.name.split('-')[0] != path.name.split('-')[0]
            or prior_path == path or store.sha(prior_path.as_posix()) != dispatch.get('prior_receipt_sha256')):
        return []
    prior_response = store.read(prior_path.as_posix()).get('response') or {}
    if not (prior_response.get('success') is False or prior_response.get('error') or prior_response.get('isError')):
        return []
    prior_items = previous.get('arguments', {}).get('items', [])
    retry_items = dispatch.get('arguments', {}).get('items', [])
    if len(prior_items) != 1 or len(retry_items) != 1:
        return []
    requirement = prior_items[0].get('requirement_id')
    requested = set(retry_items[0].get('material_ids', []))
    at = timestamp(dispatch['dispatched_at']) if dispatch.get('dispatched_at') else None
    prior_at = timestamp(previous['dispatched_at']) if previous.get('dispatched_at') else None
    response = receipt.get('response')
    if (not requirement or retry_items[0].get('requirement_id') != requirement
            or not requested or not requested.issubset(prior_items[0].get('material_ids', []))
            or at is None or prior_at is None or at <= prior_at or not response):
        return []
    verification = receipt.get('verification') or {}
    read_at = timestamp(verification['serverTime']) if verification.get('serverTime') else None
    verified = {material['id'] for row in verification.get('items', [])
                if row.get('id') == requirement for material in row.get('materials', []) if material.get('id')}
    outcome = 'unknown'
    if read_at is not None and read_at >= at and requested <= verified:
        outcome = 'success'
    elif (response.get('success') is False or response.get('error') or response.get('isError')
          or any(result.get('success') is False for result in response.get('results', []))):
        outcome = 'failed'
    status = str(prior_response.get('http_status', ''))
    video = int(path.name.split('-')[0])
    fingerprint = sha256(json.dumps([requirement, video, at, sorted(requested)]).encode()).hexdigest()
    return [{
        'id': f'fireplay-bind:{fingerprint}', 'at': at, 'source': 'fireplay',
        'requirement': f'fireplay:{requirement}', 'kind': 'retry', 'operation': 'bind',
        'attempt': dispatch.get('retry_number') or 1,
        'reason': f'http_{status}' if re.fullmatch(r'[45]\d\d', status) else 'previous_attempt',
        'video_index': video, 'outcome': outcome,
    }]


def import_fireplay(store, connection):
    saved = checkpoint(connection, 'fireplay-outboxes', {})
    files = []
    for pattern in ('*/return-*.json', '*/return-revisions/return-*.json',
                    '*/revisions/return-*.json', '*/transport-revisions/return-*.json'):
        files.extend(store.glob('state/fireplay', pattern))
    files.extend(relative for relative in store.glob('state/fireplay', '*/receipts/*-bind-*.json')
                 if BIND_RECEIPT.fullmatch(Path(relative).name))
    current, events = {}, {}
    for relative in files:
        try:
            stat = store.path(relative).stat()
        except (OSError, ValueError):
            continue
        signature = [stat.st_ino, stat.st_mtime_ns, stat.st_size]
        if saved.get(relative) == signature:
            current[relative] = signature
            continue
        try:
            document = store.read(relative)
            if not document:
                continue
            path = Path(relative)
            if path.parent.name == 'receipts':
                imported = fireplay_bind_retry(store, path, document)
            else:
                imported = fireplay_events(document, path.parts[2])
            for event in imported:
                prior = events.get(event['id'], {})
                if prior.get('outcome') != 'success' and (
                        event['outcome'] != 'unknown' or prior.get('outcome') in (None, 'unknown')):
                    events[event['id']] = event
            current[relative] = signature
        except (AttributeError, OSError, ValueError, TypeError):
            continue
    if current != saved:
        with connection:
            for event in events.values():
                previous = connection.execute('SELECT data FROM activity WHERE id=?', (event['id'],)).fetchone()
                outcome = json.loads(previous[0]).get('outcome') if previous else None
                if outcome != 'success' and (event['outcome'] != 'unknown' or outcome in (None, 'unknown')):
                    write_events(connection, [event])
            save_checkpoint(connection, 'fireplay-outboxes', current)


def read_page(connection, threads, cursor=None, requirement=None):
    if cursor is None:
        return {}
    conditions, params = [], []
    join = ''
    if requirement is not None:
        join = SCOPE_JOIN
        conditions.extend([f'{OWNER}=?', "activity.kind='retry'"])
        params.append(requirement)
    if cursor:
        match = CURSOR.fullmatch(cursor)
        if not match:
            raise ValueError('Invalid retry cursor')
        conditions.append('(activity.at, activity.id) < (?, ?)')
        params.extend([int(match[1]), match[2]])
    boundary = 'WHERE ' + ' AND '.join(conditions) if conditions else ''
    rows = connection.execute(f"""
        SELECT activity.at,activity.id,activity.data FROM activity {join} {boundary}
        ORDER BY activity.at DESC,activity.id DESC LIMIT ?
    """, (*params, PAGE_SIZE + 1)).fetchall()
    events = []
    for at, identifier, raw in rows[:PAGE_SIZE]:
        event = json.loads(raw)
        if event.get('thread'):
            event['session'] = threads.get(event['thread'], '会话不可用')
        events.append({**event, 'at': datetime.fromtimestamp(at / 1000, timezone.utc).isoformat()})
    next_cursor = f'{rows[PAGE_SIZE-1][0]}:{rows[PAGE_SIZE-1][1]}' if len(rows) > PAGE_SIZE else None
    return {'events': events, 'next_cursor': next_cursor}


def cached_summary(console, ledger):
    def collect():
        threads = {row['id']: row['name'] or row['title'] or '未命名会话' for row in console.threads()}
        coverage = {}
        with closing(database(console.root)) as connection:
            remember_owners(connection, console, ledger)
            coverage['kie_history'] = import_jobs(console.root, connection)
            for name, loader in (('codex_retries', import_retries), ('codex_failures', import_failures)):
                try:
                    loader(console.home, connection, threads)
                    coverage[name] = True
                except (OSError, sqlite3.Error):
                    coverage[name] = False
            import_fireplay(console.store, connection)
            counts = {}
            for requirement, source, count in connection.execute(f"""
                SELECT {OWNER}, json_extract(activity.data,'$.source'), count(*)
                FROM activity {SCOPE_JOIN} WHERE activity.kind='retry' AND {OWNER} IS NOT NULL
                GROUP BY 1,2
            """):
                counts.setdefault(requirement, {})[source] = count
        return threads, coverage, counts

    return console._cached('retry_activity', 12, collect)


def counts_for(counts, identifier):
    return {source: counts.get(identifier, {}).get(source, 0) for source in SOURCES}


def view(console, ledger, identifier, cursor=''):
    threads, coverage, counts = cached_summary(console, ledger)
    with closing(database(console.root)) as connection:
        return {'counts': counts_for(counts, identifier), 'coverage': coverage,
                **read_page(connection, threads, cursor, identifier)}
