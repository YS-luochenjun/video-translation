"""Bounded workspace compute and disk admission; never deletes data or steals locks."""
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from pathlib import Path
import shutil

from .common import ROOT, WorkflowError, lock, read_json, require, require_number

_held = ContextVar('local_resource_leases', default=frozenset())
HEAVY = {'workflow.analyze', 'workflow.render', 'cli.capture', 'visual_audit.generate',
         'library.export', 'local_audio.mix', 'asr.transcribe', 'typography.render'}


def settings(root):
    path = Path(root) / 'config/resources.local.json'
    value = {'max_heavy_jobs': 1, 'minimum_free_mib': 256}
    if path.exists():
        configured = read_json(path)
        require(set(configured) <= set(value), 'Unknown resource setting')
        value.update(configured)
    require(type(value['max_heavy_jobs']) is int and 1 <= value['max_heavy_jobs'] <= 8,
            'max_heavy_jobs must be between 1 and 8')
    require_number(value['minimum_free_mib'], 'minimum_free_mib', minimum=64)
    return value


def preflight(root, destination=None, required_bytes=0):
    root = Path(root).resolve()
    path = Path(destination or root).resolve()
    while not path.exists():
        path = path.parent
    require_number(required_bytes, 'required_bytes', minimum=0)
    minimum = int(settings(root)['minimum_free_mib'] * 1024**2)
    free = shutil.disk_usage(path).free
    require(free >= minimum + required_bytes,
            f'Insufficient disk space at {path}: free={free}, required={minimum + required_bytes}; '
            'preserve existing artifacts, free space or select a larger workspace and resume')
    return {'free_bytes': free, 'reserve_bytes': minimum, 'required_bytes': required_bytes}


@contextmanager
def heavy(run, stage, required_bytes=0):
    root = Path(run).resolve().parent.parent
    held = _held.get()
    preflight(root, run, required_bytes)
    if str(root) in held:
        yield
        return
    with ExitStack() as stack:
        acquired = False
        for slot in range(settings(root)['max_heavy_jobs']):
            path = root / 'state/resources' / f'heavy-{slot}.lock'
            try:
                stack.enter_context(lock(path))
                acquired = True
                break
            except WorkflowError:
                if not path.exists():
                    raise
        require(acquired, 'Local compute busy: another heavy job owns the workspace slot; '
                'use resources, then retry this same command. Never remove a live lock')
        token = _held.set(held | {str(root)})
        try:
            from .timing import measure
            with measure(run, 'resource.' + stage):
                yield
        finally:
            _held.reset(token)


@contextmanager
def admission(run, stage):
    if stage in HEAVY:
        with heavy(run, stage):
            yield
    else:
        yield


def status(root=ROOT):
    root = Path(root).resolve()
    locks = []
    for path in sorted((root / 'state/resources').glob('*.lock')):
        try:
            locks.append({'path': str(path), 'pid': path.read_text().strip()})
        except FileNotFoundError:
            continue
    return {'settings': settings(root), 'free_bytes': shutil.disk_usage(root).free,
            'locks': locks, 'automatic_cleanup': False,
            'scope': 'Workspace-managed entry points only; old ad-hoc scripts are not intercepted. '
                     'Locks survive process termination; verify the owner and journal before manual recovery.'}
