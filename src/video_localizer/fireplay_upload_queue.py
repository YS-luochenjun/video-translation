"""Track independent external media writes without limiting concurrency."""
from pathlib import Path

from .common import ROOT, lock, read_json, utc_now, write_json


def _path(root=ROOT):
    return Path(root) / 'state/fireplay/upload-queue.json'


def _empty():
    return {'schema_version': 2, 'max_active': None, 'entries': [], 'updated_at': utc_now()}


def _load(root):
    path = _path(root)
    data = read_json(path) if path.exists() else _empty()
    data.update(schema_version=2, max_active=None)
    for entry in data.get('entries', []):
        if entry.get('state') == 'queued':
            entry.update(state='ready', ready_reason='local_upload_limit_removed')
    return data


def migrate(root=ROOT):
    path = _path(root)
    with lock(path.with_suffix('.lock')):
        data = _load(root)
        data['updated_at'] = utc_now()
        write_json(path, data)


def _key(code, index, operation_id):
    return f'{code}:{index}:{operation_id}'


def acquire(code, index, operation_id, package, root=ROOT):
    """Register an upload and permit it independently of other operations."""
    path = _path(root)
    key = _key(code, index, operation_id)
    with lock(path.with_suffix('.lock')):
        data = _load(root)
        entries = data.setdefault('entries', [])
        for entry in entries:
            if entry.get('state') == 'active':
                active_path = Path(root) / entry.get('outbox', '')
                outbox = read_json(active_path) if active_path.is_file() else {}
                active_op = outbox.get('operations', {}).get(entry['operation_id'], {})
                if active_op.get('state') in ('verified', 'retryable_conflict'):
                    entry.update(state='completed', completed_at=utc_now(),
                                 completion_reason=active_op.get('state'))
                elif outbox.get('deferred_uploads', {}).get(entry.get('locale'), {}).get('operation_id') == entry['operation_id']:
                    entry.update(state='completed', completed_at=utc_now(),
                                 completion_reason='deferred_unknown_upload')
        current = next((entry for entry in entries if entry.get('key') == key
                        and entry.get('state') in ('ready', 'active')), None)
        if current:
            if current.get('state') == 'active':
                return {'acquired': True, 'state': 'active', 'key': key, 'position': 0}
        else:
            current = {'key': key, 'code': code, 'index': index, 'operation_id': operation_id,
                       'package_sha256': package.get('sha256'), 'locale': package.get('locale'),
                       'outbox': package.get('outbox', ''), 'state': 'ready',
                       'registered_at': utc_now()}
            entries.append(current)
        current.update(state='active', started_at=utc_now())
        data['updated_at'] = utc_now()
        write_json(path, data)
        return {'acquired': True, 'state': 'active', 'key': key, 'position': 0}


def release(code, index, operation_id, reason, root=ROOT):
    path = _path(root)
    key = _key(code, index, operation_id)
    with lock(path.with_suffix('.lock')):
        data = _load(root)
        for entry in data.setdefault('entries', []):
            if entry.get('key') == key and entry.get('state') in ('ready', 'active'):
                entry.update(state='completed', completed_at=utc_now(), completion_reason=reason)
        data['updated_at'] = utc_now()
        write_json(path, data)


def status(root=ROOT):
    data = _load(root)
    return {'max_active': None,
            'active': [entry for entry in data.get('entries', []) if entry.get('state') == 'active'],
            'queued': [],
            'ready': [entry for entry in data.get('entries', []) if entry.get('state') == 'ready'],
            'updated_at': data.get('updated_at')}
