"""Incremental task-scoped housekeeping; durable packages are never cache targets."""
from pathlib import Path
import os

from .common import (WorkflowError, file_hash, inside, object_hash, read_json,
                     require, run_operation, utc_now, write_json)


def _context(run):
    run = Path(run).absolute()
    root = run.parent.parent
    require(run.parent.name == 'runs' and run.resolve() == run, 'Expected a real run directory')
    config = root / 'config/maintenance.json'
    policy = read_json(config) if config.exists() else {}
    return root, policy, root / 'state/maintenance' / run.name


def _plain(root, path):
    path = Path(path).absolute()
    require(path.is_relative_to(root) and path.resolve() == path, 'Cleanup path escapes workspace or uses a link')
    for part in [path, *path.parents]:
        if part == root:
            break
        require(not part.is_symlink() and not getattr(part, 'is_junction', lambda: False)(), 'Linked cleanup path')
    return path


def register(run, relative, reason):
    """Register one completed, rebuildable file, never a whole unbounded folder."""
    root, _, state = _context(run)
    path = _plain(root, root / relative)
    require(path.is_relative_to(root / 'work/runs' / run.name), 'Scratch must belong to work/runs/RUN')
    require(path.is_file() and str(reason).strip(), 'Existing scratch file and rebuild reason required')
    with run_operation(run):
        registry = state / 'scratch.json'
        data = read_json(registry) if registry.exists() else {'files': {}}
        data['files'][path.relative_to(root).as_posix()] = {
            'sha256': file_hash(path), 'bytes': path.stat().st_size, 'rebuild': reason}
        write_json(registry, data)
    return data


def status(run):
    root, policy, state = _context(run)
    last = state / 'latest.json'
    return {'enabled': bool(policy.get('enabled')), 'scratch_directory': f'work/runs/{run.name}',
            'last': read_json(last) if last.exists() else None,
            'close_command': f'bin/va.ps1 maintain {run.name} --close',
            'contract': 'agent/contracts/storage.md'}


def _empty(root, directory):
    removed = []
    if not directory.exists():
        return removed
    _plain(root, directory)
    for parent, dirs, files in os.walk(directory, topdown=False, followlinks=False):
        path = Path(parent)
        _plain(root, path)
        if path == directory or path.name.startswith('.'):
            continue
        try:
            path.rmdir()  # Only empty directories; concurrent creation safely refuses.
            removed.append(path.relative_to(root).as_posix())
        except OSError:
            pass
    return removed


def _references(root, candidates, errors=None):
    """Conservative references in records; failure to read prevents cache eviction."""
    import json
    referenced = set()
    if not candidates:
        return referenced
    targets = {(root / relative).resolve(): relative for relative in candidates}
    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)
    for area in ('runs', 'outputs', 'media', 'knowledge', 'state'):
        for record in (root / area).rglob('*'):
            if record.suffix.lower() not in ('.json', '.md', '.txt', '.py') or not record.is_file():
                continue
            if record.is_relative_to(root / 'state/maintenance'):
                continue
            try:
                _plain(root, record)
                raw = record.read_text(encoding='utf-8-sig')
                parsed = json.loads(raw) if record.suffix.lower() == '.json' else None
            except (OSError, UnicodeError, ValueError, WorkflowError) as exc:
                if errors is None:
                    raise
                # An unreadable record may reference ANY candidate. Never guess it is safe.
                issue = {'path': record.relative_to(root).as_posix(),
                         'error_type': type(exc).__name__}
                if isinstance(exc, json.JSONDecodeError):
                    issue.update(line=exc.lineno, column=exc.colno)
                errors.append(issue)
                referenced.update(candidates)
                continue
            text = raw.replace('\\\\', '/').replace('\\', '/')
            for relative in candidates:
                if relative in text or str(root / relative).replace('\\', '/') in text:
                    referenced.add(relative)
            if record.suffix.lower() == '.json':
                bases = [root, record.parent]
                if area == 'runs':
                    bases.append(root / 'runs' / record.relative_to(root / 'runs').parts[0])
                for value in strings(parsed):
                    if not value or len(value) > 1024 or '\n' in value or '://' in value:
                        continue
                    for base in bases:
                        candidate = (base / value).resolve()
                        if candidate in targets:
                            referenced.add(targets[candidate])
    return referenced


def maintain(run, close=False, stage='manual'):
    root, policy, state = _context(run)
    if not policy.get('enabled'):
        return {'state': 'disabled'}
    from . import retention
    from . import delivery_layout, project_storage
    if close and project_storage.authorized(root) and delivery_layout.settings(root).get('enabled'):
        # Managed expiry already has an independent, bounded delivery package.
        # Legacy preserve would add a permanent full-source copy in state.
        from . import learning, library
        with run_operation(run):
            require(not list((root / 'state/resources').glob('*.lock')), 'Heavy work is active')
            for job in (run / 'jobs').glob('*.json'):
                require(read_json(job).get('state') not in {'created', 'submitted', 'running', 'processing', 'queued'},
                        'Model task remains active; finish it before closing')
            delivery = read_json(run / 'outputs/delivery.json')
            require(file_hash(inside(run, delivery['video'])) == delivery['sha256'], 'Delivered video changed')
            package = library.export(run, root, delivery['sha256'])
            learning.audit(root)
            project_storage.note_closed(run)
            result = {'run':run.name, 'stage':stage, 'checked_at':utc_now(),
                      'state':'closed_pending_lifecycle', 'package':package,
                      'outputs':'Verified independent package; no permanent full-video recovery copy. '
                                'Lifecycle preserves records and original accounting before deleting the closed run.'}
            write_json(state / 'latest.json', result)
        return result
    result = {'run': run.name, 'stage': stage, 'checked_at': utc_now(), 'state': 'kept',
              'deleted_cache': [], 'removed_empty_directories': [], 'blockers': [],
              'outputs': 'Retention and latest-only expiry are handled by the workspace-authorized storage lifecycle'}
    with run_operation(run):
        result['blockers'] = retention.blockers(run)
        if list((root / 'state/resources').glob('*.lock')):
            result['blockers'].append('Heavy work is active')
        if any(p.name != run.name + '.lock' for p in (root / 'runs/.locks').glob('*.lock')):
            result['blockers'].append('Another run is active; reference inventory may be changing')
        # Pending financial/model evidence remains intact, including its directories.
        if not result['blockers']:
            if policy.get('automatic_empty_directories'):
                for directory in (run, root / 'work/runs' / run.name):
                    result['removed_empty_directories'] += _empty(root, directory)
            delivery_path = run / 'outputs/delivery.json'
            delivered = False
            if delivery_path.exists():
                delivery = read_json(delivery_path)
                video = inside(run, delivery['video'])
                delivered = video.is_file() and file_hash(video) == delivery['sha256']
                if not delivered:
                    result['blockers'].append('Delivered video is missing or changed')
            registry = state / 'scratch.json'
            terminal_stage = stage in ('manual', 'workflow.deliver', 'fast_delivery.deliver', 'finalization.finish')
            if delivered and terminal_stage and policy.get('automatic_registered_cache_after_delivery') and registry.exists():
                candidates = read_json(registry)['files']
                scan_errors = []
                referenced = _references(root, candidates, errors=scan_errors)
                if scan_errors:
                    result['reference_scan_errors'] = scan_errors
                    result['blockers'].append('Reference scan incomplete; all registered scratch retained')
                preview = {'files': candidates, 'referenced': sorted(referenced)}
                result['cache_preview_fingerprint'] = object_hash(preview)
                write_json(state / 'cache-preview.json', preview)
                for relative, expected in candidates.items():
                    path = _plain(root, root / relative)
                    require(path.is_relative_to(root / 'work/runs' / run.name), 'Invalid registered scratch target')
                    if not path.exists():
                        continue
                    if relative in referenced or file_hash(path) != expected['sha256']:
                        result['blockers'].append('Referenced or changed scratch: ' + relative)
                        continue
                    _plain(root, path).unlink()
                    result['deleted_cache'].append(relative)
                result['removed_empty_directories'] += _empty(root, root / 'work/runs' / run.name)
            if close and policy.get('close_run_after_preservation'):
                if not delivered:
                    result['blockers'].append('Complete translated delivery required before automatic run retirement')
                elif not result['blockers']:
                    retention.preserve(run, root)
                    preview = retention.delete(run, root)
                    write_json(state / 'run-preview.json', preview)
                    if preview['decision'] == 'ready':
                        result['retirement'] = retention.delete(run, root, execute=True, expected=preview['fingerprint'])
                        result['state'] = 'retired'
                    else:
                        result['blockers'] += preview['blockers']
        if result['blockers']:
            result['state'] = 'deferred'
        write_json(state / 'latest.json', result)
    return result


def after_stage(run, stage):
    """Housekeeping may defer but can never turn a produced video into a failure."""
    if not Path(run).exists():
        return
    try:
        root, policy, state = _context(run)
        if not policy.get('enabled'):
            return
        maintain(run, stage=stage)
    except (OSError, WorkflowError, ValueError, KeyError, TypeError) as exc:
        try:
            state = Path(run).parent.parent / 'state/maintenance' / Path(run).name
            write_json(state / 'latest.json', {'state': 'deferred', 'stage': stage,
                       'checked_at': utc_now(), 'reason': str(exc), 'delivery_unaffected': True})
        except OSError:
            import warnings
            warnings.warn('Maintenance receipt unavailable; generated delivery is unchanged', RuntimeWarning)
