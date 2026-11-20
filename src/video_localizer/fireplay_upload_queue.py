"""Serialize external media writes and keep blocked uploads resumable."""
from pathlib import Path

from .common import ROOT, lock, read_json, utc_now, write_json


def _path(root=ROOT):
    return Path(root) / 'state/fireplay/upload-queue.json'


def _empty():
    return {'schema_version': 1, 'max_active': 1, 'entries': [], 'updated_at': utc_now()}


def _load(root):
    path = _path(root)
    return read_json(path) if path.exists() else _empty()


def _key(code, index, operation_id):
    return f'{code}:{index}:{operation_id}'


def acquire(code, index, operation_id, package, root=ROOT):
    """Join the FIFO queue and acquire the single external upload slot if free."""
    path = _path(root)
    key = _key(code, index, operation_id)
    with lock(path.with_suffix('.lock')):
        data = _load(root)
        entries = data.setdefault('entries', [])
        for entry in entries:
            if entry.get('state') == 'active':
                active_path = Path(root) / entry.get('outbox', '')
                active_op = read_json(active_path).get('operations', {}).get(entry['operation_id'], {}) if active_path.is_file() else {}
                if active_op.get('state') in ('verified', 'retryable_conflict'):
                    entry.update(state='completed', completed_at=utc_now(),
                                 completion_reason=active_op.get('state'))
        current = next((entry for entry in entries if entry.get('key') == key
                        and entry.get('state') in ('queued', 'active')), None)
        active = next((entry for entry in entries if entry.get('state') == 'active'), None)
        if current:
            if current.get('state') == 'active':
                return {'acquired': True, 'state': 'active', 'key': key, 'position': 0}
        else:
            current = {'key': key, 'code': code, 'index': index, 'operation_id': operation_id,
                       'package_sha256': package.get('sha256'), 'locale': package.get('locale'),
                       'outbox': package.get('outbox', ''), 'state': 'queued',
                       'queued_at': utc_now()}
            entries.append(current)
        queued = [entry for entry in entries if entry.get('state') == 'queued']
        if active or queued[0].get('key') != key:
            current['state'] = 'queued'
            data['updated_at'] = utc_now()
            write_json(path, data)
            return {'acquired': False, 'state': 'queued', 'key': key,
                    'position': next(i for i, entry in enumerate(queued, 1) if entry.get('key') == key),
                    'active': active.get('key') if active else None}
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
            if entry.get('key') == key and entry.get('state') in ('queued', 'active'):
                entry.update(state='completed', completed_at=utc_now(), completion_reason=reason)
        data['updated_at'] = utc_now()
        write_json(path, data)


def status(root=ROOT):
    data = _load(root)
    return {'max_active': data.get('max_active', 1),
            'active': [entry for entry in data.get('entries', []) if entry.get('state') == 'active'],
            'queued': [entry for entry in data.get('entries', []) if entry.get('state') == 'queued'],
            'updated_at': data.get('updated_at')}
