"""Select short-lived production state without guessing that quiet work is closed."""
from datetime import datetime, timezone
from pathlib import Path
import os
import json
import re

from .common import WorkflowError, file_hash, inside, read_json, require, object_hash


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


def read_receipt(path, root, gaps, *, mapping=False):
    try:
        record = read_json(path)
    except json.JSONDecodeError as exc:
        gaps.append(path.relative_to(root).as_posix())
        # Keep readable path/hash references even in a partly written receipt.
        # Extract references without treating broken JSON as a valid task state.
        return [exc.doc, *re.findall(r"(?i)runs[/\\\\][^/\"'\s\\\\]+", exc.doc)]
    if mapping and not isinstance(record, dict):
        gaps.append(path.relative_to(root).as_posix())
    return record


def _obsolete_neutral(root, run, rows, hash_owners):
    parent = run / 'outputs/local-repair'
    if not parent.is_dir() or _linked(parent):
        return []
    inventory = next((row for name, row in rows if name.endswith('/analysis/inventory.json')), {})
    if not isinstance(inventory, dict):
        return []
    try:
        shots = inventory['shots']
        duration = read_json(run / 'analysis/media.json')['duration']
        if len(shots) != 1 or shots[0]['start'] != 0 or shots[0]['end'] != duration or duration <= 0:
            return []
        current = shots[0]['prepared_video']
        current_path = inside(run, current['path'])
        current_mtime = current_path.stat().st_mtime_ns
    except (WorkflowError, KeyError, TypeError, ValueError, OSError):
        return []
    managed = []
    for relative, record in rows:
        path = root / relative
        if path.name != 'preparation.json' or path.parent.parent != parent or not isinstance(record, dict):
            continue
        video = path.with_name('visual-master.mkv')
        output = record.get('output')
        if not isinstance(output, dict):
            continue
        asset = {'path': video.relative_to(run).as_posix(), 'sha256': output.get('sha256')}
        if (output == asset and record.get('approved_for_reuse') is False
                and record.get('contains_target_typography') is False and record.get('probe_only') is False
                and record.get('source_sha256') == inventory.get('source_sha256')
                and re.fullmatch('[a-f0-9]{64}', asset['sha256'] or '') and video.is_file() and not _linked(video)):
            managed.append((relative, video, asset))
    selected = []
    for relative, video, asset in managed:
        if (asset['sha256'] == current['sha256'] or hash_owners.get(asset['sha256'], {run.name}) != {run.name}
                or current_mtime <= video.stat().st_mtime_ns):
            continue
        if any(asset['path'].casefold() in text.replace('\\', '/').casefold() or asset['sha256'] in text
               for other, data in rows if other != relative for text in _strings(data)):
            continue
        if file_hash(video) == asset['sha256']:
            selected.append({'path': video.relative_to(root).as_posix(), 'reason': 'superseded_neutral_cache'})
    if not selected:
        return []
    from .prepared import verify_for_production
    from .media import probe
    try:
        verify_for_production(run, current, inventory['source_sha256'], root)
        if abs(probe(current_path)['duration'] - duration) > .15:
            return []
    except (WorkflowError, OSError, ValueError, KeyError, TypeError):
        return []
    return selected


def select(root, maintenance, pinned_runs, pinned_sources, now):
    """Return exact candidates plus dependencies to bind into the sweep fingerprint."""
    root = Path(root)
    runs = {p.name: p for p in (root / 'runs').iterdir()
            if p.is_dir() and not p.name.startswith('.') and not _linked(p)} if (root / 'runs').exists() else {}
    candidates, retained, records = {}, [], {}
    for name, run in sorted(runs.items()):
        rows, gaps, controls = [], [], {}
        record_path = run / 'run.json'
        delivery_path = run / 'outputs/delivery.json'
        for path in files(run):
            if path.suffix == '.json' and not path.name.startswith('.env'):
                control = (path in (record_path, delivery_path)
                           or (path.name == 'closure.json' and path.parent.parent == run / 'review/failures'))
                data = read_receipt(path, root, gaps, mapping=control)
                rows.append((path.relative_to(root).as_posix(), data))
                if control:
                    controls[path] = data
        records[name] = rows
        closed_path = root / 'state/storage-closed' / (name + '.json')
        marker = read_receipt(closed_path, root, gaps, mapping=True) if closed_path.exists() else None
        stamp = None
        if isinstance(marker, dict) and 'closed_at' in marker:
            try:
                stamp = _timestamp(marker['closed_at'])
            except (TypeError, ValueError, WorkflowError):
                gaps.append(closed_path.relative_to(root).as_posix())
        if gaps:
            retained.append({'path': 'runs/' + name, 'reason': 'unreadable_json_receipt', 'receipts': sorted(gaps)})
            continue
        record = controls.get(record_path, {})
        if name in pinned_runs or record.get('source_sha256') in pinned_sources:
            retained.append({'path': 'runs/' + name, 'reason': 'pinned'})
            continue
        active_jobs = [path for path, data in rows if '/jobs/' in path and _unresolved_job(data)]
        if active_jobs:
            retained.append({'path': 'runs/' + name, 'reason': 'remote_job_active'})
            continue
        activity = root / 'state/storage-activity' / (name + '.json')
        resumed_ns = activity.stat().st_mtime_ns if activity.exists() else 0
        delivery = controls.get(delivery_path, {})
        if marker and _activity(run) <= closed_path.stat().st_mtime:
            if marker.get('video_sha256') and delivery.get('sha256') == marker['video_sha256']:
                hours = maintenance.get('closed_run_retention_hours', 24)
                closed_at = stamp if stamp is not None else _activity(run)
                if _age(now, closed_at) * 24 >= hours:
                    candidates[name] = 'closed_task'
                else:
                    retained.append({'path': 'runs/' + name, 'reason': 'closed_grace_period'})
                continue
        terminal = (record.get('state') in {'failed', 'cancelled', 'aborted'}
                    and record_path.stat().st_mtime_ns >= resumed_ns)
        terminal |= any(path not in (record_path, delivery_path)
                        and data.get('state') == 'failed_preproduction' and path.stat().st_mtime_ns >= resumed_ns
                        for path, data in controls.items())
        if terminal and _age(now, _activity(run)) >= maintenance.get('terminal_run_retention_days', 7):
            candidates[name] = 'terminal_task_idle'
        else:
            reason = 'awaiting_close_receipt' if delivery_path in controls else 'unfinished_or_recent'
            retained.append({'path': 'runs/' + name, 'reason': reason})

    # Removing one candidate can keep another alive: compute the retained closure.
    dependencies = {name: set() for name in runs}
    names = {name.casefold(): name for name in runs}
    for name, rows in records.items():
        for _, data in rows:
            for text in _strings(data):
                text = text.replace('\\', '/').casefold()
                parts = text.split('/')
                for index, part in enumerate(parts[:-1]):
                    if part == 'runs':
                        other = names.get(parts[index + 1])
                        if other and other != name:
                            dependencies[name].add(other)
    changed = True
    while changed:
        changed = False
        for name in sorted(runs.keys() - candidates.keys()):
            for dependency in sorted(dependencies[name]):
                if dependency in candidates:
                    del candidates[dependency]
                    retained.append({'path': 'runs/' + dependency, 'reason': 'referenced_by_live_task', 'consumer': name})
                    changed = True
    live = runs.keys() - candidates.keys()
    sources, texts, hash_owners = set(pinned_sources), set(), {}
    for name in live:
        for _, data in records[name]:
            for text in _strings(data):
                normalized = text.replace('\\', '/').casefold()
                if any(area in normalized for area in ('runs/', 'work/', 'media/', 'outputs/')):
                    texts.add(normalized)
                for digest in re.findall(r'(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])', text.lower()):
                    sources.add(digest)
                    hash_owners.setdefault(digest, set()).add(name)
    selected = [{'path': 'runs/' + name, 'reason': reason} for name, reason in sorted(candidates.items())]
    consumers = set().union(*(dependencies[name] for name in live))
    for row in retained:
        if row['reason'] == 'closed_grace_period':
            name = Path(row['path']).name
            if name not in consumers:
                selected.extend(_obsolete_neutral(root, runs[name], records[name], hash_owners))
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
        registrations = [p for p in (root / 'state/storage-closed' / (scratch.name + '.json'),
                         root / 'state/maintenance' / scratch.name / 'scratch.json') if p.exists()]
        gaps = []
        for registration in registrations:
            read_receipt(registration, root, gaps)
        retired = root / 'state/run-retention' / (scratch.name + '.json')
        retirement_stamp = 0
        if retired.exists() and not registrations:
            receipt = read_receipt(retired, root, gaps)
            if (isinstance(receipt, dict) and receipt.get('schema_version') == 1
                    and receipt.get('run') == scratch.name and receipt.get('status') == 'deleted'
                    and isinstance(receipt.get('deleted_at'), str)):
                try:
                    retirement_stamp = _timestamp(receipt['deleted_at'])
                except (ValueError, WorkflowError):
                    gaps.append(retired.relative_to(root).as_posix())
        if gaps:
            retained.append({'path': scratch.relative_to(root).as_posix(), 'reason': 'unreadable_json_receipt', 'receipts': gaps})
            continue
        known = bool(registrations) or retirement_stamp > 0
        if not known:
            retained.append({'path': scratch.relative_to(root).as_posix(), 'reason': 'unregistered_scratch'})
        if known and _age(now, max(_activity(scratch), retirement_stamp)) * 24 >= maintenance.get('orphan_scratch_retention_hours', 24):
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
        gaps = []
        usage_record = read_receipt(usage, root, gaps) if usage.exists() else None
        if gaps:
            retained.append({'path': relative, 'reason': 'unreadable_json_receipt', 'receipts': gaps})
            continue
        stamp = max(_activity(source), _timestamp(usage_record['last_used_at']) if usage.exists() else 0)
        if _age(now, stamp) >= maintenance.get('media_idle_retention_days', 7):
            selected.append({'path': relative, 'reason': 'unreferenced_source_cache'})
    return selected, retained, object_hash({'records': records, 'dependencies': {k: sorted(v) for k, v in dependencies.items()},
                                           'sources': sorted(sources)}), texts
