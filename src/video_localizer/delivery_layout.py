"""Human-facing final files, with separately retained immutable recovery packages."""
import os
import re
import shutil
from pathlib import Path

from .common import file_hash, inside, read_json, require


def settings(root):
    path = Path(root) / 'config/delivery-policy.json'
    if not path.exists():
        return {'enabled': False}
    value = read_json(path)
    require(value.get('layout') == 'requirement-language-task' and value.get('retention_days') == 14,
            'Use the approved delivery layout and maximum14-day retention')
    require(value.get('package_root') == 'outputs/.packages' and value.get('catalog') == 'state/delivery-index.json',
            'Internal packages/catalog must use their fixed managed locations')
    return value


def name(value):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(value)).strip().rstrip('.')[:160]
    require(value and value not in {'.', '..'} and not value.startswith('.'), 'Invalid delivery folder name')
    return value


def catalog(root):
    root = Path(root)
    current = root / 'state/delivery-index.json'
    return current if settings(root).get('enabled') or current.exists() else root / 'outputs/index.json'


def identity(run):
    root = run.parent.parent
    request = read_json(run / 'inputs/request.json')
    source = read_json(run / 'run.json')
    pointer = run / 'inputs/fireplay.json'
    fireplay = read_json(pointer) if pointer.exists() else {}
    code = fireplay.get('requirement_code') or fireplay.get('code') or request.get('requirement_code')
    if not code:
        match = re.match(r'^([A-Z]+-\d{8}-\d+)(?:-|$)', run.name)
        code = match[1] if match else None
    mapped = root / 'state/delivery-folders.json'
    mapping = read_json(mapped).get('sources', {}) if mapped.exists() else {}
    requirement = request.get('requirement_name') or code or mapping.get(source['source_sha256']) or Path(source.get('source_name',source['source'])).stem
    index = fireplay.get('video_index') or fireplay.get('video') or request.get('video_index')
    if isinstance(index, dict):
        index = index.get('index')
    if index is None and code:
        suffix = run.name[len(code):]
        match = re.match(r'^-(\d+)-', suffix)
        index = match[1] if match else None
    stem = Path(source.get('source_name', source['source'])).stem
    task = request.get('task_name') or (f'原片-{index}' if index is not None else
             stem if stem not in {'source', requirement} else '原片-1')
    return {'requirement_name': name(requirement), 'task_name': name(task),
            'target_language': name(request['target_language']),
            'keep_multiple_versions': request.get('keep_multiple_versions') is True}


def present(root, entry, final):
    """Atomically replace only the final view; never link to a mutable run."""
    folder = inside(root, f"outputs/{entry['requirement_name']}/{entry['target_language']}/{entry['task_name']}")
    if entry.get('keep_multiple_versions'):
        folder = folder / entry['video_sha256'][:16]
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / 'final.mp4'
    temporary = folder / '.final.pending'
    temporary.unlink(missing_ok=True)
    try:
        try:
            os.link(final, temporary)
        except OSError:
            shutil.copyfile(final, temporary)
        require(file_hash(temporary) == entry['video_sha256'], 'Final view differs from immutable package')
        temporary.replace(target)
    finally:
        # POSIX rename between two links to the same inode is a no-op: remove
        # its remaining temporary name on idempotent re-export as well.
        temporary.unlink(missing_ok=True)
    return target.relative_to(root).as_posix()
