"""Explicit expiry and owner-authorized fresh start; accounting/knowledge never expire.

Deletion is selected by a current fingerprint. Recovery metadata is independent
of the selected media; no command here settles charges or claims acceptance.
"""
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from .common import (WorkflowError, file_hash, inside, lock, object_hash,
                     read_json, require, utc_now, write_json)

AREAS = ('runs', 'work', 'outputs', 'media')
RECORD_SUFFIXES = {'.json', '.jsonl', '.txt', '.md', '.csv', '.srt', '.ass', '.vtt', '.py', '.swift', '.js', '.log'}


def _locks(root):
    return [p.relative_to(root).as_posix() for base in ('runs/.locks', 'state/resources')
            for p in (root / base).glob('*.lock')]


def _safe_path(root, relative):
    lexical = root / relative
    resolved = inside(root, relative)
    require(lexical == resolved, 'Linked cleanup path is not eligible: ' + str(relative))
    return resolved


def _tree(path):
    result = []
    if not path.exists() and not path.is_symlink():
        return result
    from .storage_candidates import _linked
    paths = [path]
    if path.is_dir() and not _linked(path):
        for parent, folders, names in os.walk(path, followlinks=False):
            paths.extend(Path(parent) / name for name in [*folders, *names])
            folders[:] = [name for name in folders if not _linked(Path(parent) / name)]
    for p in sorted(paths):
        try:
            s = p.lstat()
            linked = _linked(p)
            result.append({'path': p.relative_to(path.parent).as_posix(), 'bytes': s.st_size,
                           'mtime_ns': s.st_mtime_ns, 'inode': s.st_ino, 'device': s.st_dev,
                           'link': os.readlink(p) if linked else None,
                           'directory': p.is_dir() and not linked})
        except FileNotFoundError:
            # Transient scratch can disappear while capacity is scanned. A
            # selected tree changing still changes its deletion fingerprint.
            # Other I/O errors remain failures; no permission bypass or retry.
            continue
    return result


def _catalog(root):
    from .delivery_layout import catalog
    path = catalog(root)
    if not path.exists() and (root / 'outputs/index.json').exists():
        path = root / 'outputs/index.json'
    return read_json(path) if path.exists() else {'schema_version': 1, 'entries': []}


def authorized(root, reset=False):
    p = root / 'config/storage-authorization.local.json'
    if not p.exists():
        return False
    d = read_json(p)
    return (d.get('workspace') == str(root.resolve()) and d.get('automatic_cleanup') is True
            and (not reset or d.get('reset_existing_data') is True))


def _closed(root, name):
    p = root / 'state/storage-closed' / (name + '.json')
    from .storage_candidates import read_receipt
    gaps = []
    record = read_receipt(p, root, gaps) if p.exists() else None
    return None if gaps else record


def note_closed(run):
    root = run.parent.parent
    if not authorized(root):
        return
    path = run / 'outputs/delivery.json'
    if not path.exists():
        return
    d = read_json(path)
    video = inside(run, d['video'])
    require(video.is_file() and file_hash(video) == d['sha256'], 'Close marker requires the actual formal video')
    write_json(root / 'state/storage-closed' / (run.name + '.json'), {
        'run': run.name, 'video_sha256': d['sha256'], 'closed_at': utc_now(),
        'authority': 'Producer called maintain --close after external submission and required records, under the workflow contract'})


def preview(root, reset=False, now=None):
    from .delivery_layout import settings
    root = Path(root).resolve()
    require(authorized(root, reset), 'Workspace-bound storage authorization is missing')
    require(not _locks(root), 'Active run/heavy-operation locks: do not clear working media')
    now = now or datetime.now(timezone.utc)
    selections = []
    retained, dependencies = [], None
    pressure = False
    if reset:
        selections = [{'path': area, 'reason': 'owner_confirmed_all_tasks_complete_fresh_start'}
                      for area in AREAS if (root / area).exists()]
    else:
        from .storage_policy import settings as budgets
        limits = budgets(root)
        maintenance = read_json(root / 'config/maintenance.json')
        for area in AREAS:
            limit = maintenance.get('work_max_gib', 8) if area == 'work' else limits[area]['max_gib']
            size = sum(row['bytes'] for row in _tree(root / area) if not row['directory'])
            pressure |= bool(limit and size > limit * 1024**3)
            if area != 'work':
                count = sum(p.is_dir() and not p.name.startswith('.') for p in (root/area).iterdir()) if (root/area).exists() else 0
                if area == 'outputs':
                    count = sum((root/e['package']).exists() for e in _catalog(root)['entries'])
                pressure |= bool(limits[area]['max_count'] and count > limits[area]['max_count'])
        pressure |= shutil.disk_usage(root).free < limits['minimum_free_gib']*1024**3
        rows = _catalog(root)['entries']
        order = {id(entry): index for index, entry in enumerate(rows)}
        groups = {}
        for entry in rows:
            if entry.get('expired_at'):
                continue
            if entry['source_sha256'] in limits.get('pinned_sources',[]) or entry.get('origin_run_id') in limits.get('pinned_runs',[]):
                continue
            if not (root / entry['package'] / 'manifest.json').is_file():
                continue
            key = (entry.get('requirement_name', entry['source_sha256']), entry['target_language'], entry.get('task_name', 'legacy'))
            groups.setdefault(key, []).append(entry)
        for group in groups.values():
            group.sort(key=lambda e: (e['archived_at'], order[id(e)]), reverse=True)
            keep_multiple = any(e.get('keep_multiple_versions') for e in group)
            for position, entry in enumerate(group):
                age = (now-datetime.fromisoformat(entry['archived_at'])).total_seconds()/86400
                stale = age >= settings(root)['retention_days']
                older = position > 0 and not keep_multiple
                # Capacity pressure may evict already-closed packages earlier.
                closed = _closed(root, entry.get('origin_run_id', ''))
                early = settings(root).get('evict_latest_under_pressure', False)
                if stale or older or (pressure and closed and early):
                    selections.append({'path': entry['package'], 'reason': 'expired_14_days' if stale else 'superseded' if older else 'capacity',
                                       'entry': entry})
        from .storage_candidates import select
        transient, retained, dependencies, references = select(
            root, maintenance, limits.get('pinned_runs', []), limits.get('pinned_sources', []), now)
        selections.extend(transient)
        incomplete = {item['path'] for item in retained if item['reason'] == 'unreadable_json_receipt'}
        for entry in rows:
            if 'runs/' + str(entry.get('origin_run_id')) in incomplete:
                incomplete.update((entry['package'], 'media/' + entry['source_sha256']))
        unreferenced = []
        for row in selections:
            if row['path'] in incomplete:
                retained.append({'path': row['path'], 'reason': 'owner_missing_evidence'})
                continue
            dependency_paths = [row['path']]
            presentation = row.get('entry', {}).get('presentation')
            if presentation:
                dependency_paths.append(presentation)
            if row['path'].startswith(('outputs/', 'work/')) and any(
                path.casefold() in text for path in dependency_paths for text in references
            ):
                retained.append({'path': row['path'], 'reason': 'referenced_by_live_task'})
            else:
                unreferenced.append(row)
        selections = unreferenced
    unique = {s['path']:s for s in selections}
    selected = []
    for relative, selection in sorted(unique.items()):
        path = _safe_path(root, relative)
        if selection.get('entry', {}).get('presentation'):
            _safe_path(root, selection['entry']['presentation'])
        require(path.parts[len(root.parts)] in AREAS and path != root, 'Storage target escapes allowed media areas')
        require(reset or len(path.parts) > len(root.parts)+1, 'Lifecycle cannot select a whole storage root')
        require(not path.is_symlink(), 'Do not traverse a linked storage root')
        tree = _tree(path)
        selected.append({**selection,'tree_fingerprint':object_hash(tree),
                         'files':sum(not row['directory'] for row in tree),
                         'logical_bytes':sum(row['bytes'] for row in tree if not row['directory'])})
    unavailable = [e['package'] for e in _catalog(root)['entries']
                   if not e.get('expired_at') and not (root / e['package'] / 'manifest.json').is_file()]
    result = {'mode':'reset' if reset else 'lifecycle', 'pressure':pressure, 'selected':selected,
              'retained': retained, 'dependency_fingerprint': dependencies,
              'unavailable_entries': unavailable,
              'authorization_sha256':file_hash(root / 'config/storage-authorization.local.json'),
              'policy_sha256':file_hash(root / 'config/delivery-policy.json'),
              'maintenance_sha256':file_hash(root / 'config/maintenance.json'),
              'capacity_policy_sha256':file_hash(root / 'config/storage-policy.json'),
              'catalog_sha256':object_hash(_catalog(root)),
              'protected':['knowledge', 'state/accounting and operation history', '.runtime', 'config', '.git']}
    return {**result,'fingerprint':object_hash(result)}


def _preserve_records(root, plan, folder):
    from . import bundles
    sources = {}
    legacy = root / 'outputs/index.json'
    if legacy.is_file():
        sources['legacy-delivery-index.json'] = legacy
    from .storage_candidates import files
    for row in plan['selected']:
        path = _safe_path(root, row['path'])
        for file in files(path) if path.is_dir() else [path]:
            if (file.is_file() and not file.is_symlink() and file.suffix.lower() in RECORD_SUFFIXES
                    and not any(p in {'node_modules','__pycache__','.git','test-tmp','cache'} for p in file.relative_to(root).parts)
                    and not file.name.startswith('.env')):
                sources[file.relative_to(root).as_posix()] = file
    receipt = root / 'state/storage-plans' / (plan['fingerprint'] + '.json')
    write_json(receipt, plan)
    sources['selection.json'] = receipt
    return bundles.create(folder,'expired-production-records',plan['fingerprint'],sources,{
        'scope':'Production media explicitly expires. Records, scripts, captions, plans and costs remain; this is NOT full-video recovery.',
        'no_acceptance_or_fee_settlement':True})


def execute(root, expected, reset=False, now=None):
    from . import learning
    root = Path(root).resolve()
    with lock(root / 'state/project-storage.lock'):
        plan = preview(root,reset,now)
        require(plan['fingerprint'] == expected, 'Storage preview changed; regenerate the selection')
        # A new guard cannot enter run_operation while the lifecycle lock exists.
        require(not _locks(root), 'A producer became active; retry after it finishes')
        from . import budgets
        sync_errors = []
        run_paths = [inside(root, row['path']) for row in plan['selected'] if row['path'].startswith('runs/')]
        if reset and (root / 'runs').exists():
            run_paths = [p for p in (root / 'runs').iterdir() if p.is_dir() and not p.name.startswith('.')]
        for run in run_paths:
            try:
                budgets.sync(run)
            except (WorkflowError, OSError, KeyError, ValueError) as exc:
                sync_errors.append({'run':run.name,'error':str(exc),'scope':'Existing reservation and raw journal retained; no charge released'})
        learning.audit(root)
        folder = root / 'state/expired-production' / plan['fingerprint']
        _preserve_records(root, plan, folder / 'records')
        require(preview(root,reset,now)['fingerprint'] == expected, 'Media changed during preservation')
        before = shutil.disk_usage(root).free
        catalog = _catalog(root)
        removed = []
        removing = {row['path'] for row in plan['selected']}
        live_views = {entry.get('presentation') for entry in catalog['entries']
                      if not entry.get('expired_at') and entry['package'] not in removing
                      and (root / entry['package'] / 'manifest.json').is_file()}
        for row in plan['selected']:
            target = _safe_path(root,row['path'])
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            removed.append({k:row[k] for k in ('path','reason','files','logical_bytes')})
            entry = row.get('entry')
            if entry and entry.get('presentation') and entry['presentation'] not in live_views:
                view = _safe_path(root,entry['presentation'])
                if view.is_file() and file_hash(view) == entry['video_sha256']:
                    view.unlink()
        reasons = {row['path']: row['reason'] for row in plan['selected']}
        for entry in catalog['entries']:
            if not entry.get('expired_at') and (reset or not (root / entry['package'] / 'manifest.json').is_file()):
                entry['expired_at'] = utc_now()
                entry['expiry_reason'] = ('owner_fresh_start' if reset else
                                          reasons.get(entry['package'], 'missing_before_sweep'))
        write_json(root / 'state/delivery-index.json',catalog)
        legacy = root / 'outputs/index.json'
        if legacy.exists() and not reset:
            legacy.unlink()  # Its original bytes are in the independent records bundle.
        empty_starts = [root / row['path'] for row in plan['selected'] if row['path'].startswith('outputs/')]
        empty_starts.extend(root / entry['presentation'] for entry in catalog['entries'] if entry.get('presentation'))
        for start in empty_starts:
            parent = start.parent
            while parent != root / 'outputs' and (root / 'outputs') in parent.parents:
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent
        for area in AREAS:
            (root / area).mkdir(exist_ok=True)
        if reset:
            # One-shot authority cannot silently authorize another full reset.
            auth = read_json(root / 'config/storage-authorization.local.json')
            auth['reset_existing_data'] = False
            write_json(root / 'config/storage-authorization.local.json',auth)
        after = shutil.disk_usage(root).free
        result = {'fingerprint':expected,'mode':plan['mode'],'deleted':removed,
                  'logical_bytes_removed':sum(r['logical_bytes'] for r in removed),
                  'free_bytes_before':before,'free_bytes_after':after,'net_free_bytes_change':after-before,
                  'preserved_records':(folder / 'records').relative_to(root).as_posix(),
                  'accounting_sync_errors':sync_errors,
                  'scope':'Actual disk free delta can include concurrent system writes and APFS/hardlink effects; charges and old quality states unchanged.'}
        write_json(folder / 'receipt.json',result)
        learning.audit(root)
        return result


def auto(root):
    root = Path(root).resolve()
    if not authorized(root) or _locks(root):
        return {'state':'deferred_or_disabled'}
    path = root / 'state/storage-lifecycle-latest.json'
    old = read_json(path) if path.exists() else {}
    maintenance = read_json(root / 'config/maintenance.json')
    if time.time()-old.get('checked_unix',0) < maintenance.get('lifecycle_check_seconds',3600):
        return {'state':'not_due'}
    plan = preview(root)
    result = execute(root,plan['fingerprint']) if plan['selected'] or plan['unavailable_entries'] else {'state':'no_eligible_data','pressure':plan['pressure']}
    write_json(path,{'checked_unix':time.time(),**result})
    return result
