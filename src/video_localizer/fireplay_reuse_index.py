"""Small, rebuildable lookup index over verified Fireplay delivery records."""
from contextlib import closing, contextmanager
from pathlib import Path
import re
import sqlite3
from time import time

from . import fireplay
from .common import WorkflowError, object_hash, read_json
from .fireplay_submission import _canonical_materials, bound_materials


MISS_LIFETIME = {'quick': 300, 'full': 900}
INDEX_REFRESH_SECONDS = 60


def database_path(root):
    return Path(root) / 'state/fireplay-reuse/discovery.sqlite3'


@contextmanager
def _database(root):
    path = database_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=.4)) as database:
        database.row_factory = sqlite3.Row
        database.executescript("""
            CREATE TABLE IF NOT EXISTS indexed_requests (code TEXT PRIMARY KEY, signature TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS checkpoints (name TEXT PRIMARY KEY, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS assets (
                code TEXT NOT NULL, requirement_id TEXT NOT NULL, video_index INTEGER NOT NULL,
                source_sha256 TEXT NOT NULL, source_youtube_id TEXT, locale TEXT NOT NULL,
                material_id TEXT NOT NULL, delivery_sha256 TEXT NOT NULL, delivery_youtube_id TEXT,
                PRIMARY KEY (code, video_index, locale, material_id)
            );
            CREATE INDEX IF NOT EXISTS assets_source ON assets (source_sha256);
            CREATE INDEX IF NOT EXISTS assets_youtube ON assets (source_youtube_id);
            CREATE INDEX IF NOT EXISTS assets_delivery ON assets (delivery_sha256);
            CREATE INDEX IF NOT EXISTS assets_material ON assets (material_id);
            CREATE TABLE IF NOT EXISTS misses (identity TEXT PRIMARY KEY, expires REAL NOT NULL);
        """)
        with database:
            if 'delivery_youtube_id' not in {row['name'] for row in database.execute('PRAGMA table_info(assets)')}:
                database.execute('BEGIN IMMEDIATE')
                if 'delivery_youtube_id' not in {row['name'] for row in database.execute('PRAGMA table_info(assets)')}:
                    database.execute('ALTER TABLE assets ADD COLUMN delivery_youtube_id TEXT')
                    database.execute('DELETE FROM indexed_requests')
                    database.execute("DELETE FROM checkpoints WHERE name = 'all_requests'")
            database.execute('CREATE INDEX IF NOT EXISTS assets_delivery_youtube ON assets(delivery_youtube_id)')
        with database:
            yield database


def _sha256(value):
    return isinstance(value, str) and re.fullmatch(r'[a-f0-9]{64}', value) is not None


def _delivery_youtube_ids(folder, box):
    bind = box.get('operations', {}).get('bind', {})
    receipt_path = folder / 'receipts' / f"{box['video_index']}-bind.json"
    if bind.get('state') != 'verified' or not receipt_path.is_file():
        return {}
    try:
        receipt = read_json(receipt_path)
        verification = fireplay.payload(receipt['verification'])
    except (OSError, ValueError, KeyError, TypeError, WorkflowError):
        return {}
    if (object_hash(receipt) != bind.get('receipt_sha256') or verification.get('view') != 'delivery'
            or object_hash(verification) != bind['result'].get('verification_sha256')):
        return {}
    rows = [row for row in verification.get('items', []) if row.get('id') == box['requirement_id']]
    if len(rows) != 1 or rows[0].get('materialSelection', {}).get('status') == 'waiting_selection':
        return {}
    links = {}
    for material in rows[0].get('materials', []):
        url = material.get('videoUrl')
        if (material.get('type') != 'video' or not fireplay._uuid(material.get('id'))
                or not isinstance(url, str)):
            continue
        try:
            video_id = fireplay.youtube_id(url)
        except ValueError:
            continue
        if video_id:
            links[material['id']] = video_id
    return links


def _completion_youtube_ids(folder, request):
    path = folder / 'completion-check.json'
    if not path.is_file():
        return {}
    try:
        completion = read_json(path)
        if (completion.get('requirement_id') != request['requirement_id']
                or completion.get('content_version') != request['content_version']
                or not _sha256(completion.get('verification_sha256'))):
            return {}
        return {(row['video_index'], row['material_id'], row['locale'], row['sha256']): row['delivery_youtube_id']
                for row in completion.get('verified', [])
                if isinstance(row.get('delivery_youtube_id'), str)
                and re.fullmatch(r'[A-Za-z0-9_-]{11}', row['delivery_youtube_id'])}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def _rows(folder, root):
    request = read_json(folder / 'request.json')
    requirement_id = request.get('requirement_id')
    if request.get('code') != folder.name or not fireplay._uuid(requirement_id):
        return []
    if request.get('snapshot', {}).get('row', {}).get('status') in {'rejected', 'ai_rejected'}:
        return []
    completion_ids = _completion_youtube_ids(folder, request)
    rows = []
    for video in request.get('videos', []):
        index = video['index']
        source_hash = (video.get('source') or {}).get('sha256')
        if not _sha256(source_hash):
            continue
        outbox = folder / f'return-{index}.json'
        delivery_youtube_ids = {}
        if outbox.is_file():
            box = read_json(outbox)
            bound = box.get('operations', {}).get('bind', {}).get('result', {}).get('material_ids')
            if (box.get('requirement_id') != requirement_id or box.get('video_index') != index
                    or box.get('content_version') != request.get('content_version') or not isinstance(bound, list)):
                continue
            delivered = _canonical_materials(box)
            if delivered:
                delivery_youtube_ids = _delivery_youtube_ids(folder, box)
        else:
            delivered = bound_materials(request, video, root)
        for item in delivered:
            locale, material_id, digest = item['locale'], item['material_id'], item.get('sha256')
            if locale not in video['targets'] or not _sha256(digest):
                continue
            delivery_id = completion_ids.get((index, material_id, locale, digest)) or delivery_youtube_ids.get(material_id)
            rows.append((folder.name, requirement_id, index, source_hash, video.get('youtube_video_id'),
                         locale, material_id, digest, delivery_id))
    return rows


def _sync(database, folder, root):
    paths = [folder / 'request.json', folder / 'completion-check.json',
             *folder.glob('return-*.json'), *folder.glob('user-approved-return-*.json'),
             *folder.glob('receipts/*-bind.json'),
             folder / 'user-directed-submission/submission-final.json', *folder.glob('*/verified-*-materials.json')]
    signature = []
    for path in sorted(paths):
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        signature.append((path.relative_to(folder).as_posix(), stat.st_ino, stat.st_mtime_ns, stat.st_size))
    digest = object_hash(signature)
    previous = database.execute('SELECT signature FROM indexed_requests WHERE code = ?', (folder.name,)).fetchone()
    if previous and previous['signature'] == digest:
        return
    try:
        rows = _rows(folder, root)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        rows = []
    database.execute('DELETE FROM assets WHERE code = ?', (folder.name,))
    database.executemany('INSERT OR IGNORE INTO assets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', rows)
    database.execute('INSERT OR REPLACE INTO indexed_requests VALUES (?, ?)', (folder.name, digest))


def _refresh(database, root):
    refreshed = database.execute("SELECT updated FROM checkpoints WHERE name = 'all_requests'").fetchone()
    if refreshed and time() - refreshed['updated'] < INDEX_REFRESH_SECONDS:
        return
    database.execute('BEGIN IMMEDIATE')
    refreshed = database.execute("SELECT updated FROM checkpoints WHERE name = 'all_requests'").fetchone()
    if refreshed and time() - refreshed['updated'] < INDEX_REFRESH_SECONDS:
        return
    folders = {path.parent.name: path.parent for path in (Path(root) / 'state/fireplay').glob('*/request.json')}
    for folder in folders.values():
        _sync(database, folder, root)
    for old in database.execute('SELECT code FROM indexed_requests').fetchall():
        if old['code'] not in folders:
            database.execute('DELETE FROM assets WHERE code = ?', (old['code'],))
            database.execute('DELETE FROM indexed_requests WHERE code = ?', (old['code'],))
    database.execute("INSERT OR REPLACE INTO checkpoints VALUES ('all_requests', ?)", (time(),))
    database.execute('DELETE FROM misses WHERE expires <= ?', (time(),))


def refresh_request(code, root):
    try:
        with _database(root) as database:
            database.execute('BEGIN IMMEDIATE')
            _sync(database, fireplay._folder(code, root), root)
    except (OSError, sqlite3.Error):
        return False
    return True


def discover(record, video, root):
    source = video['source']['sha256']
    youtube_id = video.get('youtube_video_id')
    material_id = (video.get('resolved') or {}).get('material_id')
    matches = []
    try:
        with _database(root) as database:
            _refresh(database, root)
            rows = database.execute("""
                SELECT * FROM assets WHERE requirement_id != ?
                AND (source_sha256 = ? OR source_youtube_id = ? OR delivery_sha256 = ? OR material_id = ?
                     OR delivery_youtube_id = ?)
                ORDER BY code DESC, video_index, locale, material_id
            """, (record['requirement_id'], source, youtube_id, source, material_id, youtube_id))
            for row in rows:
                if row['source_sha256'] == source or (youtube_id and row['source_youtube_id'] == youtube_id):
                    if row['locale'] in video['targets']:
                        matches.append({**dict(row), 'relation': 'source'})
                if not row['source_youtube_id']:
                    continue
                if row['delivery_sha256'] == source or row['material_id'] == material_id:
                    matches.append({**dict(row), 'relation': 'delivery'})
                elif youtube_id and row['delivery_youtube_id'] == youtube_id:
                    matches.append({**dict(row), 'relation': 'delivery', 'matched_delivery_youtube_id': youtube_id})
    except (OSError, sqlite3.Error):
        return [], 'unavailable'
    return matches, 'ready'


def miss_identity(record, video, profile):
    summary = record.get('snapshot', {}).get('raw', {}).get('summary') or {}
    operator = fireplay.payload(summary).get('operator')
    department = record.get('snapshot', {}).get('row', {}).get('deptId')
    if not isinstance(operator, str) or not operator.strip() or not department:
        return None, None
    identity = object_hash({'operator': operator, 'department': department, 'scope': 'all',
                            'profile': profile, 'source_sha256': video['source']['sha256'],
                            'youtube_id': video.get('youtube_video_id'),
                            'material_id': (video.get('resolved') or {}).get('material_id')})
    return identity, operator


def cached_miss(identity, root):
    if not identity or not database_path(root).is_file():
        return None
    try:
        with _database(root) as database:
            row = database.execute('SELECT expires FROM misses WHERE identity = ? AND expires > ?',
                                   (identity, time())).fetchone()
            return row['expires'] if row else None
    except (OSError, sqlite3.Error):
        return None


def remember_miss(identity, profile, root):
    try:
        with _database(root) as database:
            database.execute('DELETE FROM misses WHERE expires <= ?', (time(),))
            database.execute('INSERT OR REPLACE INTO misses VALUES (?, ?)',
                             (identity, time() + MISS_LIFETIME[profile]))
    except (OSError, sqlite3.Error):
        return
