"""Small project-local observations of provider failures and retries."""
from contextlib import closing
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import sqlite3

from .common import read_json, write_json


LOGGER = logging.getLogger(__name__)
SCHEMA = """
CREATE TABLE IF NOT EXISTS activity(
    id TEXT PRIMARY KEY, at INTEGER NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS activity_recent ON activity(at DESC, id DESC);
CREATE TABLE IF NOT EXISTS checkpoints(name TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def database(root):
    path = Path(root) / 'state/retry-activity/events.sqlite3'
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=.15)
    try:
        if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='checkpoints'").fetchone():
            connection.execute('PRAGMA journal_mode=WAL')
            connection.executescript(SCHEMA)
        return connection
    except BaseException:
        connection.close()
        raise


def timestamp(value=None):
    try:
        moment = datetime.fromisoformat(value.replace('Z', '+00:00')) if value else datetime.now(timezone.utc)
        if moment.tzinfo is None:
            return None
        return int(moment.timestamp() * 1000)
    except (AttributeError, OverflowError, ValueError):
        return None


def write_events(connection, events):
    connection.executemany("""
        INSERT INTO activity(id, at, kind, data) VALUES(?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET data=excluded.data WHERE data<>excluded.data
    """, ((event['id'], event['at'], event['kind'],
           json.dumps({key: value for key, value in event.items() if key != 'at'}, separators=(',', ':')))
          for event in events))


def record(root, events):
    if events:
        try:
            with closing(database(root)) as connection, connection:
                write_events(connection, events)
        except (OSError, sqlite3.Error):
            LOGGER.warning('Retry activity could not be recorded')


def reason(code=None, error=None, fallback='provider_failed'):
    if isinstance(code, (str, int)) and re.fullmatch(r'[1-5][0-9]{2}', str(code)):
        return f'http_{code}'
    if isinstance(error, str):
        match = re.match(r'KIE (?:HTTP|code) ([1-5][0-9]{2})\b', error)
        if match:
            return 'http_' + match[1]
        if error.startswith('KIE transport/response failure'):
            return 'transport'
    return fallback


def observe_request(call_id, retry, operation, cause, outcome):
    from .timing import current_run
    run = current_run()
    if run is None:
        return
    run = Path(run)
    record(run.parent.parent, [{
        'id': f'kie-http:{call_id}:{retry}', 'at': timestamp(), 'source': 'kie',
        'kind': 'retry' if retry else 'failure', 'operation': operation, 'run': run.name,
        'attempt': retry or None, 'reason': cause, 'outcome': outcome,
    }])


def job_events(run, job, previous=None):
    identifier = job.get('id')
    if not isinstance(identifier, str) or not re.fullmatch(r'[a-f0-9]{64}', identifier):
        return []
    started_at = timestamp(job.get('created_at')) if job.get('created_at') else None
    if started_at is None:
        return []
    state = job.get('state')
    outcome = {'success': 'success', 'fail': 'failed', 'failed': 'failed',
               'ambiguous': 'unknown', 'response_invalid': 'failed',
               'submitted': 'submitted', 'waiting': 'submitted',
               'queuing': 'submitted', 'generating': 'submitted'}.get(state, 'started')
    base = {'source': 'kie', 'run': run, 'job': identifier}
    events = []
    if job.get('retry_of'):
        source = previous or {}
        events.append({
            **base, 'id': f'kie-job:{run}:{identifier}', 'at': started_at, 'kind': 'retry',
            'operation': 'model_retry', 'attempt': job.get('retry_attempt') or 1,
            'reason': reason(source.get('provider_code'), source.get('error'), 'previous_attempt'),
            'outcome': outcome,
        })
    history = job.get('recovery_history') or []
    uploads = job.get('upload_retry_history') or []
    for index in range(max(len(history), len(uploads))):
        recovery = history[index] if index < len(history) else {}
        upload = uploads[index] if index < len(uploads) else {}
        happened = timestamp(recovery.get('at') or upload.get('at')) if recovery.get('at') or upload.get('at') else None
        if happened is None and index + 1 == len(uploads):
            happened = started_at
        if happened is not None:
            events.append({
                **base, 'id': f'kie-recovery:{run}:{identifier}:{index+1}', 'at': happened, 'kind': 'retry',
                'operation': 'asset_retry' if index < len(uploads) else 'pre_dispatch_retry',
                'attempt': index+1, 'reason': reason(error=recovery.get('previous_error'), fallback='previous_attempt'),
                'outcome': outcome if index+1 == max(len(history), len(uploads)) else 'failed',
            })
    if state in ('fail', 'failed') and job.get('task_id'):
        checked_at = timestamp(job['last_checked_at']) if job.get('last_checked_at') else None
        events.append({
            **base, 'id': f'kie-task-failed:{run}:{identifier}', 'at': checked_at or started_at,
            'kind': 'failure', 'operation': 'model_result', 'attempt': None, 'outcome': 'failed',
            'reason': reason(job.get('provider_code'), job.get('provider_error')),
        })
    return events


def observed_job(path, job, *, recovering=False):
    write_json(path, job)
    if not (job.get('retry_of') or job.get('upload_retry_history') or job.get('recovery_history')
            or job.get('state') in ('fail', 'failed') and job.get('task_id')):
        return
    run = path.parent.parent
    try:
        view = {**job, 'state': 'preparing'} if recovering else job
        record(run.parent.parent, job_events(run.name, view, previous_job(path.parent, job)))
    except (TypeError, AttributeError, ValueError):
        LOGGER.warning('Retry job history could not be read')


def previous_job(folder, job):
    identifier = job.get('retry_of')
    if isinstance(identifier, str) and re.fullmatch(r'[a-f0-9]{64}', identifier):
        try:
            value = read_json(folder / f'{identifier}.json')
            if isinstance(value, dict):
                return value
        except (OSError, ValueError):
            pass
    return None
