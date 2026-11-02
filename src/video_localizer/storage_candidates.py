"""Select short-lived production state without guessing that quiet work is closed."""
from datetime import datetime, timezone
from pathlib import Path
import os
import re

from .common import read_json, require, object_hash


def _linked(path):
    return path.is_symlink() or getattr(path, 'is_junction', lambda: False)()


def files(path):
    """Do not follow directory links, including Windows junctions."""
    if _linked(path):
        return
    for parent, folders, names in os.walk(path, followlinks=False):
        folders[:] = [n for n in folders if not _linked(Path(parent) / n)]
        for name in names:
            item = Path(parent) / name
            if not _linked(item):
                yield item


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _activity(path):
    return max([path.stat().st_mtime, *(p.stat().st_mtime for p in files(path))])


def _age(now, stamp):
    return (now.timestamp() - stamp) / 86400


def _timestamp(value):
    parsed = datetime.fromisoformat(value)
    require(parsed.tzinfo is not None, 'Storage timestamps require an explicit timezone')
    return parsed.timestamp()


def _unresolved_job(data):
    from .budgets import TERMINAL
    if not isinstance(data, dict) or not ('state' in data or data.get('task_id')):
        return False
    active = {'pending', 'queued', 'submitted', 'submitting', 'running', 'processing',
              'polling', 'uploading', 'waiting', 'queuing', 'generating'}
    if data.get('state') in active:
        return True
    terminal = {*TERMINAL, 'completed', 'cancelled', 'aborted'}
    # Unknown queryable tasks stay protected; billing-only receipts need no media.
    return bool(data.get('task_id')) and data.get('state') not in terminal


def select(root, maintenance, pinned_runs, pinned_sources, now):
    """Return exact candidates plus dependencies to bind into the sweep fingerprint."""
    root = Path(root)
    runs = {p.name: p for p in (root / 'runs').iterdir()
            if p.is_dir() and not p.name.startswith('.') and not _linked(p)} if (root / 'runs').exists() else {}
    candidates, retained, records = {}, [], {}
    for name, run in sorted(runs.items()):
        rows = []
        for path in files(run):
            if path.suffix == '.json' and not path.name.startswith('.env'):
                rows.append((path.relative_to(root).as_posix(), read_json(path)))
        records[name] = rows
        record_path = run / 'run.json'
        record = read_json(record_path) if record_path.exists() else {}
        if name in pinned_runs or record.get('source_sha256') in pinned_sources:
            retained.append({'path': 'runs/' + name, 'reason': 'pinned'})
            continue
        active_jobs = [path for path, data in rows if '/jobs/' in path and _unresolved_job(data)]
        if active_jobs:
            retained.append({'path': 'runs/' + name, 'reason': 'remote_job_active'})
            continue
        activity = root / 'state/storage-activity' / (name + '.json')
        resumed_ns = activity.stat().st_mtime_ns if activity.exists() else 0
        closed_path = root / 'state/storage-closed' / (name + '.json')
        if closed_path.exists() and _activity(run) <= closed_path.stat().st_mtime:
            marker = read_json(closed_path)
            delivery = run / 'outputs/delivery.json'
            if delivery.exists() and read_json(delivery).get('sha256') == marker.get('video_sha256'):
                hours = maintenance.get('closed_run_retention_hours', 24)
                stamp = _timestamp(marker['closed_at']) if marker.get('closed_at') else _activity(run)
                if _age(now, stamp) * 24 >= hours:
                    candidates[name] = 'closed_task'
                else:
                    retained.append({'path': 'runs/' + name, 'reason': 'closed_grace_period'})
                continue
        terminal = (record.get('state') in {'failed', 'cancelled', 'aborted'}
                    and record_path.stat().st_mtime_ns >= resumed_ns)
        closures = list((run / 'review/failures').glob('*/closure.json'))
        terminal |= any(p.stat().st_mtime_ns >= resumed_ns and read_json(p).get('state') == 'failed_preproduction'
                        for p in closures)
        if terminal and _age(now, _activity(run)) >= maintenance.get('terminal_run_retention_days', 7):
            candidates[name] = 'terminal_task_idle'
        else:
            retained.append({'path': 'runs/' + name, 'reason': 'unfinished_or_recent'})

    # Removing one candidate can keep another alive: compute the retained closure.
    dependencies = {name: set() for name in runs}
    for name, rows in records.items():
        for _, data in rows:
            for text in _strings(data):
                text = text.replace('\\', '/').casefold()
                for other in runs:
                    relative = 'runs/' + other.casefold()
                    if text == relative or text.startswith(relative + '/') or ('/' + relative + '/') in text or text.endswith('/' + relative):
                        if other != name:
                            dependencies[name].add(other)
    changed = True
    while changed:
        changed = False
        for name in runs.keys() - candidates.keys():
            for dependency in dependencies[name]:
                if dependency in candidates:
                    del candidates[dependency]
                    retained.append({'path': 'runs/' + dependency, 'reason': 'referenced_by_live_task', 'consumer': name})
                    changed = True
    live = runs.keys() - candidates.keys()
    sources, texts = set(pinned_sources), []
    for name in live:
        for _, data in records[name]:
            for text in _strings(data):
                texts.append(text.replace('\\', '/').casefold())
                sources.update(re.findall(r'(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])', text.lower()))
    selected = [{'path': 'runs/' + name, 'reason': reason} for name, reason in sorted(candidates.items())]
    for name in sorted(candidates):
        scratch = root / 'work/runs' / name
        if scratch.is_dir() and not _linked(scratch):
            relative = scratch.relative_to(root).as_posix()
            if not any(relative.casefold() in text for text in texts):
                selected.append({'path': relative, 'reason': 'closed_task_cache'})
    scratch_root = root / 'work/runs'
    for scratch in scratch_root.iterdir() if scratch_root.exists() else []:
        if not scratch.is_dir() or _linked(scratch) or scratch.name in runs or scratch.name in pinned_runs:
            continue
        # Only known task scratch is eligible; unrelated work never ages into consent.
        known = (root / 'state/storage-closed' / (scratch.name + '.json')).exists() or (root / 'state/maintenance' / scratch.name / 'scratch.json').exists()
        if not known:
            retained.append({'path': scratch.relative_to(root).as_posix(), 'reason': 'unregistered_scratch'})
        if known and _age(now, _activity(scratch)) * 24 >= maintenance.get('orphan_scratch_retention_hours', 24):
            relative = scratch.relative_to(root).as_posix()
            if not any(relative.casefold() in text for text in texts):
                selected.append({'path': relative, 'reason': 'orphan_task_cache'})
    for source in (root / 'media').iterdir() if (root / 'media').exists() else []:
        if not source.is_dir() or _linked(source) or not re.fullmatch('[0-9a-f]{64}', source.name):
            continue
        relative = source.relative_to(root).as_posix()
        if source.name in sources or any(relative in text for text in texts):
            continue
        usage = root / 'state/media-usage' / (source.name + '.json')
        stamp = max(_activity(source), _timestamp(read_json(usage)['last_used_at']) if usage.exists() else 0)
        if _age(now, stamp) >= maintenance.get('media_idle_retention_days', 7):
            selected.append({'path': relative, 'reason': 'unreferenced_source_cache'})
    return selected, retained, object_hash({'records': records, 'dependencies': {k: sorted(v) for k, v in dependencies.items()},
                                           'sources': sorted(sources)}), texts
