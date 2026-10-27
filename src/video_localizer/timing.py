"""Local stage measurements; elapsed work is not provider compute or human review time."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
import time
import uuid
import warnings
import os
import threading
from functools import wraps

from .common import read_json, write_json

_active = ContextVar('stage_timer', default=None)
_run = ContextVar('stage_run', default=None)


def timed(stage):
    def decorate(function):
        @wraps(function)
        def invoke(*args, **kwargs):
            run = _run.get()
            if run is None:
                return function(*args, **kwargs)
            with measure(run, stage):
                return function(*args, **kwargs)
        return invoke
    return decorate


def directory(run):
    run = Path(run).resolve()
    return run.parent.parent / 'state/timing' / run.name


@contextmanager
def measure(run, stage):
    parent = _active.get()
    event = {'id': uuid.uuid4().hex, 'run': Path(run).name, 'stage': stage,
             'parent_id': parent, 'started_at': datetime.now(timezone.utc).isoformat(),
             'status': 'running'}
    started = time.perf_counter()
    token = _active.set(event['id'])
    run_token = _run.set(run)
    heartbeat_stop = threading.Event()
    heartbeat_thread = None
    def record_activity(kind):
        try:
            from .ledger import runtime_event
            runtime_event(run, kind, {'stage': stage, 'execution_id': event['id'],
                                     'pid': os.getpid(), 'actor_kind': 'local_executor'},
                          identifier=event['id']+'-'+kind.rsplit('.', 1)[-1] if kind != 'executor.heartbeat' else None)
        except (OSError, ValueError):
            warnings.warn('Ledger activity pending; execution result is unchanged', RuntimeWarning)
    if parent is None:
        record_activity('executor.started')
        def heartbeat():
            while not heartbeat_stop.wait(60):
                record_activity('executor.heartbeat')
        heartbeat_thread = threading.Thread(target=heartbeat, daemon=True, name='ledger-executor-heartbeat')
        heartbeat_thread.start()
    try:
        yield
        event['status'] = 'completed'
    except BaseException:
        event['status'] = 'failed'
        raise
    finally:
        heartbeat_stop.set()
        if heartbeat_thread:
            heartbeat_thread.join(timeout=2)
            record_activity('executor.'+('finished' if event['status']=='completed' else 'failed'))
        _active.reset(token)
        _run.reset(run_token)
        event.update(seconds=round(time.perf_counter()-started, 6),
                     ended_at=datetime.now(timezone.utc).isoformat())
        try:
            write_json(directory(run) / (event['id'] + '.json'), event)
        except OSError:
            warnings.warn('Stage timing could not be saved; execution result is unchanged', RuntimeWarning)


def report(runs):
    events = [read_json(p) for run in runs for p in directory(run).glob('*.json')]
    ids = {event['id'] for event in events}
    top = [event for event in events if event['parent_id'] not in ids]
    stages = {}
    for event in events:
        row = stages.setdefault(event['stage'], {'calls': 0, 'failures': 0, 'inclusive_seconds': 0})
        row['calls'] += 1
        row['failures'] += event['status'] != 'completed'
        row['inclusive_seconds'] += event['seconds']
    intervals = sorted((datetime.fromisoformat(e['started_at']).timestamp(),
                        datetime.fromisoformat(e['ended_at']).timestamp()) for e in top)
    merged = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    wall = sum(end-start for start, end in merged)
    span = merged[-1][1]-merged[0][0] if merged else 0
    return {'events': len(events), 'stages': stages,
            'top_level_work_seconds': round(sum(e['seconds'] for e in top), 4),
            'observed_active_wall_seconds': round(wall, 4), 'observed_span_seconds': round(span, 4),
            'unobserved_gap_seconds': round(max(0, span-wall), 4),
            'scope': 'Instrumented local stages only. Inclusive nested timings must not be summed. Gaps can include agent reasoning, review, user waits or external work; they are not measured OCR or model time.'}
