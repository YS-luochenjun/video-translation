from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import threading
import time
from functools import partial, wraps
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[2]
ROOT = Path(os.environ.get("VIDEO_LOCALIZER_WORKSPACE", str(CODE_ROOT))).expanduser().resolve()
from .runtime import configure as configure_runtime
configure_runtime(CODE_ROOT)
_operations = threading.local()
STORAGE_WAIT_SECONDS = 45


class WorkflowError(Exception):
    pass


def operation_hash(path, cache):
    """Read each hard-linked file once within ONE locked verification operation.

    No persistent mtime-based trust: callers start with an empty cache each time.
    """
    stat = Path(path).stat()
    key = (stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)
    if key not in cache:
        cache[key] = file_hash(path)
    return cache[key]


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path):
    path = Path(path)
    with path.open(encoding="utf-8-sig") as stream:
        try:
            return json.load(stream)
        except json.JSONDecodeError as exc:
            # Keep the exception type for existing fail-closed callers. Identify
            # the broken record without printing its potentially private bytes.
            raise json.JSONDecodeError(
                f"Invalid JSON in {path}: {exc.msg}", exc.doc, exc.pos
            ) from exc


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replace keeps a killed process from leaving a truncated journal.
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        # Windows scanners/readers can briefly deny replacement even after the
        # writer closes. Keep the old journal intact and retry the same bytes;
        # permanent access errors still propagate without deleting the target.
        for attempt in range(5):
            try:
                os.replace(temporary, path)
                break
            except PermissionError as exc:
                if getattr(exc, 'winerror', None) not in (5, 32, 33) or attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def object_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode()).hexdigest()


def inside(root, relative):
    root = Path(root).resolve()
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root):
        raise WorkflowError("Path must stay within its run/workspace directory")
    return candidate


def get_run(name):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", name):
        raise WorkflowError("Run id must contain only letters, numbers, underscores, hyphens")
    run = inside(ROOT / "runs", name)
    if not (run / "run.json").exists():
        raise WorkflowError(f"Unknown run: {name}")
    return run


def require_number(value, label, minimum=0, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise WorkflowError(f"{label}: expected a finite number")
    if value < minimum or (maximum is not None and value > maximum):
        raise WorkflowError(f"{label}: out of range")
    return value


def require(condition, message):
    if not condition:
        raise WorkflowError(message)


@contextmanager
def lock(path, *, wait_seconds=0):
    """Cross-process exclusion. A crash intentionally leaves a visible recovery gate."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = None
    while True:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError as exc:
            if not wait_seconds:
                raise WorkflowError(f"Operation locked: {path.name}; inspect journal before recovery") from exc
            now = time.monotonic()
            if deadline is None:
                deadline = now + wait_seconds
            remaining = deadline - now
            if remaining <= 0:
                raise WorkflowError(f"Operation locked: {path.name}; bounded wait ended; "
                                    "resume the same operation after checking the owner and journal") from exc
            time.sleep(min(1, remaining))
    try:
        os.write(descriptor, str(os.getpid()).encode())
        os.close(descriptor)
        yield
    finally:
        path.unlink(missing_ok=True)


@contextmanager
def storage_admission(root, operation_lock, *, wait_seconds=None):
    storage_lock = root / 'state/project-storage.lock'
    wait_seconds = STORAGE_WAIT_SECONDS if wait_seconds is None else wait_seconds
    deadline = None
    while True:
        if not storage_lock.exists():
            with lock(operation_lock):
                if not storage_lock.exists():
                    yield
                    return
        now = time.monotonic()
        if deadline is None:
            deadline = now + wait_seconds
        remaining = deadline - now
        if remaining <= 0:
            raise WorkflowError('Project storage maintenance is active; operation did not start. '
                                'Resume the same command when the maintenance receipt completes')
        time.sleep(min(1, remaining))


@contextmanager
def run_operation(run, *, resume=True, storage_wait_seconds=None):
    """Serialize run access with sweeps; only production work revokes closure."""
    run = Path(run).resolve()
    root = run.parent.parent
    path = run.parent / ".locks" / (run.name + ".lock")
    held = getattr(_operations, "held", set())
    if path in held:
        yield
        return
    with storage_admission(root, path, wait_seconds=storage_wait_seconds):
        require(run.is_dir(), "Run was removed or does not exist")
        if resume:
            closed = root / 'state/storage-closed' / (run.name + '.json')
            activity = root / 'state/storage-activity' / (run.name + '.json')
            previous = read_json(activity) if activity.exists() else {}
            record = {'last_operation_at': utc_now()}
            if closed.exists():
                record['previous_close'] = read_json(closed)
            elif 'previous_close' in previous:
                record['previous_close'] = previous['previous_close']
            write_json(activity, record)
            closed.unlink(missing_ok=True)
        _operations.held = held | {path}
        try:
            yield
        finally:
            _operations.held = held


def guarded(function=None, *, resume=True):
    if function is None:
        return partial(guarded, resume=resume)

    @wraps(function)
    def invoke(run, *args, **kwargs):
        from .budgets import operation
        operation_path = Path(run).resolve().parent / '.locks' / (Path(run).name + '.lock')
        outermost = operation_path not in getattr(_operations, 'held', set())
        provider_operation = function.__name__ in ('submit', 'poll', 'poll_batch', 'analyze_audio')
        with run_operation(run, resume=resume), operation():
            from .timing import measure
            from .resources import admission
            stage = function.__module__.rsplit('.', 1)[-1] + '.' + function.__name__
            with measure(run, stage), admission(run, stage):
                try:
                    result = function(run, *args, **kwargs)
                finally:
                    if provider_operation:
                        from .batches import sync
                        # Reservations remain conservative if settlement fails; the next
                        # reserve refreshes all journals before admitting further work.
                        try:
                            sync(run)
                        except (OSError, WorkflowError, KeyError, ValueError):
                            import warnings
                            warnings.warn('Request settlement pending; inspect budget-status before further spending', RuntimeWarning)
            if outermost and not stage.startswith('retention.'):
                from .maintenance import after_stage
                after_stage(run, stage)
        return result
    return invoke


def load_key():
    value = os.environ.get("KIE_API_KEY", "")
    if not value and (ROOT / ".env").exists():
        for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
            if line.startswith("KIE_API_KEY="):
                value = line.split("=", 1)[1].strip().strip("\"'")
    require(bool(value), "KIE_API_KEY is missing; set the environment variable or local .env")
    return value

