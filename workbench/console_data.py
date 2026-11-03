"""Real project sessions, evidence and durable human UI commands.

Reads Codex's local metadata read-only. Runtime status comes only from timestamped
desktop-tool observations, never from a different app-server's notLoaded state.
The host dispatcher owns all desktop writes; this module never starts a model.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import threading
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from store import Store, clean, MEDIA
from collector import Ledger

PAGE_SIZE = 8
NODES = [('intake', '接单与范围'), ('analysis', '内容解析与源样式'), ('base', '底片与资产'),
         ('production', '译文、配音与字层'), ('review', '候选与实际审核'),
         ('output', '完整输出'), ('publication', '平台回传')]


def now():
    return datetime.now(timezone.utc).isoformat()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class ConsoleData:
    def __init__(self, root, store=None, codex_home=None):
        self.root = Path(root).resolve()
        self.store = store or Store(root)
        self.home = Path(codex_home or os.environ.get('CODEX_HOME') or Path.home()/'.codex')
        self.lock = threading.RLock()
        self.cache = {}
        self.folder = self.root/'state/console'

    def _cached(self, key, seconds, loader):
        with self.lock:
            prior = self.cache.get(key)
            if prior and time.monotonic()-prior[0] < seconds:
                return prior[1]
            value = loader()
            self.cache[key] = (time.monotonic(), value)
            return value

    def threads(self):
        def load():
            path = self.home/'state_5.sqlite'
            if not path.is_file():
                return []
            with sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=3) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute('SELECT id, name, title, cwd, archived, updated_at, created_at, rollout_path, source '
                                    'FROM threads WHERE cwd=? ORDER BY updated_at DESC, id', (str(self.root),)).fetchall()
            # Internal guardian/review workers do not appear as user-facing chats.
            return [dict(r) for r in rows if 'subagent' not in str(r['source']).lower()]
        return self._cached('threads', 3, load)

    def thread(self, identifier):
        result = next((r for r in self.threads() if r['id'] == identifier), None)
        if not result:
            raise ValueError('会话不属于当前项目')
        return result

    def requests(self):
        def load():
            result = {}
            for path in self.store.glob('state/fireplay', '*/request.json'):
                r = self.store.read(path)
                identifiers = {r.get('chat', {}).get('threadId')}
                identifiers.update(v.get('chat', {}).get('threadId') for v in r.get('videos', []))
                for tid in identifiers-{None}:
                    result.setdefault(tid, []).append(r)
            return result
        return self._cached('requests', 5, load)

    def ledger_rows(self):
        def load():
            if not (self.root/'state/ledger/ledger.sqlite3').exists():
                return []
            return Ledger(self.root).view()['requirements']
        return self._cached('ledger', 10, load)

    def observations(self):
        return self.store.read('state/console/host-snapshot.json')

    def overview(self, query='', state='all', page=1, archived=False):
        observations = self.observations()
        statuses = observations.get('threads', {})
        rows = []
        for t in self.threads():
            if bool(t['archived']) != archived:
                continue
            title = t.get('name') or t.get('title') or t['id']
            if query.casefold() not in title.casefold():
                continue
            o = statuses.get(t['id'], {})
            fresh = time.time()-o.get('observed_epoch', 0) < 130
            status = o.get('status', {}).get('type', 'unobserved') if fresh else 'unobserved'
            reqs = self.requests().get(t['id'], [])
            codes = [r.get('code') for r in reqs]
            ledger = [r for r in self.ledger_rows() if r.get('code') in codes]
            business = next((r for r in ledger if r.get('state') in ('blocked', 'working', 'waiting')), None)
            if business is None and ledger:
                business = ledger[0]
            business_state = (business or {}).get('state', 'unreported')
            if state == 'active' and status != 'active':
                continue
            if state == 'attention' and not (business_state in ('blocked', 'waiting') or any(r.get('blockers') for r in reqs)):
                continue
            rows.append({'id': t['id'], 'title': clean(title)[:180], 'hostId': 'local', 'status': status,
                         'status_observed_at': o.get('observed_at'), 'status_fresh': fresh,
                         'updated_at': t['updated_at'], 'created_at': t['created_at'], 'archived': bool(t['archived']),
                         'codes': codes, 'business_state': business_state,
                         'stage_counts': (business or {}).get('stage_counts', {}),
                         'output_count': (business or {}).get('output_count'), 'task_count': (business or {}).get('task_count'),
                         'blocked': bool(any(r.get('blockers') for r in reqs)),
                         'latest_eta': clean((business or {}).get('latest_eta'))})
        total = len(rows)
        pages = max(1, (total+PAGE_SIZE-1)//PAGE_SIZE)
        page = max(1, min(int(page), pages))
        return {'sessions': rows[(page-1)*PAGE_SIZE:page*PAGE_SIZE], 'total': total, 'page': page,
                'pages': pages, 'page_size': PAGE_SIZE, 'observed_at': now(),
                'host_snapshot_at': observations.get('observed_at'),
                'bridge': self.dispatch_status(), 'scope': str(self.root)}

    def run_ids(self, identifier):
        ids = set()
        for r in self.requests().get(identifier, []):
            for v in r.get('videos', []):
                chat = v.get('chat') or r.get('chat', {})
                if chat.get('threadId') == identifier:
                    ids.update(v.get('members') or [])
                    if v.get('pilot'):
                        ids.add(v['pilot'])
        for r in self.ledger_rows():
            if any((t.get('threadId') or t.get('id')) == identifier for t in r.get('threads', [])):
                try:
                    for task in Ledger(self.root).detail(r['id'])['tasks']:
                        ids.update(task.get('runs', []))
                except (OSError, ValueError, KeyError):
                    pass
        return sorted(i for i in ids if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,180}', i))

    def versions(self):
        return self._cached('versions', 15, lambda: self.store.versions([]))

    def detail(self, identifier, run_id=None):
        t = self.thread(identifier)
        ids = self.run_ids(identifier)
        if run_id and run_id not in ids:
            raise ValueError('制作任务与会话不匹配')
        runs = []
        for rid in ids:
            req = self.store.read(f'runs/{rid}/inputs/request.json')
            matching = [v for v in self.versions() if v.get('origin_run_id') == rid]
            runs.append({'id': rid, 'locale': req.get('target_language') or (matching[-1].get('target_language') if matching else None)})
        selected = run_id or (ids[0] if ids else None)
        task = None
        artifacts = []
        if selected:
            matching = [v for v in self.versions() if v.get('origin_run_id') == selected]
            try:
                task = self.store._task(selected, matching, full=False)
                artifacts = self.artifacts(selected, matching)
            except (OSError, ValueError, KeyError):
                task = {'id': selected, 'state_label': '现场或交付包暂不可读', 'state': 'unavailable'}
        codes = [r.get('code') for r in self.requests().get(identifier, [])]
        ledger = [r for r in self.ledger_rows() if r.get('code') in codes]
        public_ledger = [clean({k: r.get(k) for k in ('id', 'code', 'title', 'state', 'stage_counts', 'blockers',
                          'received_at', 'first_started_at', 'last_activity_at', 'latest_eta', 'complete_at',
                          'task_count', 'output_count', 'quality_count', 'claim', 'executors', 'agent_health', 'external')}) for r in ledger]
        nodes = []
        for nid, name in NODES:
            own = [a for a in artifacts if a['node'] == nid]
            nodes.append({'id': nid, 'title': name, 'artifact_count': len(own),
                          'state': 'recorded' if own else 'unrecorded'})
        return {'thread': {'id': t['id'], 'title': clean(t.get('name') or t.get('title') or t['id']), 'archived': bool(t['archived'])},
                'runs': runs, 'selected_run': selected, 'task': task, 'artifacts': artifacts, 'nodes': nodes,
                'requirements': public_ledger, 'messages': self.messages(t),
                'commands': self.commands(identifier), 'budget': self.budgets(identifier), 'observed_at': now()}

    def budgets(self, identifier):
        ids = set()
        for r in self.requests().get(identifier, []):
            b = r.get('budget')
            if isinstance(b, str): ids.add(b)
            elif isinstance(b, dict): ids.add(b.get('id') or b.get('budget_id'))
        codes = {r.get('code') for r in self.requests().get(identifier, [])}
        for r in self.ledger_rows():
            if r.get('code') in codes: ids.update(r.get('budget_ids', []))
        rows = []
        for bid in ids-{None}:
            if not re.fullmatch(r'[A-Za-z0-9_.-]+', bid): continue
            b = self.store.read(f'state/budgets/{bid}.json')
            reservations = b.get('reservations', {})
            reservations = list(reservations.values()) if isinstance(reservations, dict) else reservations
            actual = [r.get('actual_credits') for r in reservations if isinstance(r, dict)]
            rows.append({'id': bid, 'limit': b.get('credit_limit'),
                         'known_actual': sum(v for v in actual if isinstance(v, (int, float))),
                         'unknown_count': sum(v is None for v in actual)})
        return rows

    def messages(self, t):
        host = self.observations().get('threads', {}).get(t['id'], {})
        if host.get('messages'):
            return host['messages'][-30:]
        # Text-only fallback. Never serialize tool calls, tool outputs or images.
        p = Path(t.get('rollout_path') or '')
        if not p.is_absolute() or not any(p.resolve().is_relative_to(self.home/area) for area in ('sessions', 'archived_sessions')):
            return []
        result = []
        try:
            with p.open('rb') as stream:
                stream.seek(max(0, p.stat().st_size-2*1024*1024))
                lines = stream.read().splitlines()
            for line in lines:
                if len(line) > 512*1024: continue
                try: record = json.loads(line)
                except ValueError: continue
                payload = record.get('payload', {})
                if record.get('type') != 'response_item' or payload.get('type') != 'message' or payload.get('role') not in ('user', 'assistant'):
                    continue
                text = '\n'.join(c.get('text', '') for c in payload.get('content', []) if c.get('type') in ('input_text', 'output_text'))
                if text.startswith(('<environment_context', '# AGENTS.md', '<permissions')): continue
                if text: result.append({'role': payload['role'], 'text': clean(text), 'at': record.get('timestamp'), 'source': '本机已保存正文'})
        except OSError:
            pass
        return result[-24:]

    def artifacts(self, run_id, versions):
        prefixes = [f'runs/{run_id}']
        prefixes.extend(v['package'] for v in versions if not v.get('expired'))
        paths = []
        for prefix in prefixes:
            try:
                for p in self.store.path(prefix).rglob('*'):
                    rel = p.relative_to(self.root).as_posix()
                    if p.is_file() and p.suffix.lower() in MEDIA | {'.json', '.md', '.txt'}:
                        # Keep credentials and raw request/response envelopes out of previews.
                        if any(s in rel.lower() for s in ('authorization', 'credentials', '/jobs/', 'raw-response', 'raw-request', '/logs/', 'upload-payload')): continue
                        if p.suffix.lower() in {'.json', '.md', '.txt'} and not any(s in rel for s in ('analysis/inventory', 'analysis/media', 'style', '/review/', '/outputs/', '/manifest.json')): continue
                        self.store.path(rel)
                        paths.append((p.stat().st_mtime, rel))
            except (OSError, ValueError):
                continue
        # Per-node retention prevents abundant review frames hiding all source/output assets.
        rows, counts = [], {}
        for modified, rel in sorted(set(paths), reverse=True):
            low = rel.lower();suffix = Path(rel).suffix.lower()
            if '/inputs/source.' in low or '/analysis/' in low and not any(s in low for s in ('base', 'clean', 'tts', 'audio')):
                node = 'analysis'
            elif any(s in low for s in ('clean', 'base', 'erase', 'restor', 'textless')): node = 'base'
            elif '/review/' in low or 'quality' in low: node = 'review'
            elif '/outputs/' in low or Path(rel).name == 'final.mp4': node = 'output'
            else: node = 'production'
            counts[node] = counts.get(node, 0)+1
            if counts[node] > 40: continue
            kind = 'image' if suffix in {'.png', '.jpg', '.jpeg', '.webp'} else 'video' if suffix in {'.mp4', '.mov', '.webm'} else 'audio' if suffix in {'.wav', '.mp3', '.m4a'} else 'document'
            rows.append({'id': fingerprint(rel)[:24], 'run_id': run_id, 'path': rel, 'name': Path(rel).name,
                         'node': node, 'kind': kind, 'modified_at': datetime.fromtimestamp(modified, timezone.utc).isoformat(),
                         'url': '/api/media?path='+quote(rel, safe='') if kind != 'document' else None,
                         'version_note': '历史交付包' if any(rel.startswith(v['package']+'/') for v in versions[:-1]) else '现场 / 最新包；以审核绑定为准'})
        return rows

    def artifact(self, thread_id, run_id, identifier):
        self.thread(thread_id)
        if run_id not in self.run_ids(thread_id): raise ValueError('任务不属于当前会话')
        rows = self.artifacts(run_id, [v for v in self.versions() if v.get('origin_run_id') == run_id])
        a = next((a for a in rows if a['id'] == identifier), None)
        if not a: raise FileNotFoundError('产物已不存在或已到期')
        path = self.store.path(a['path'])
        value = {**a, 'sha256': self.store.sha(a['path']), 'bytes': path.stat().st_size}
        if a['kind'] == 'document':
            if path.stat().st_size > 1024*1024: raise ValueError('文档过大，请查看原会话')
            if path.suffix.lower() == '.json': value['text'] = json.dumps(clean(json.loads(path.read_text())), ensure_ascii=False, indent=2)
            else: value['text'] = clean(path.read_text())
        return value

    def automations(self):
        tids = {t['id'] for t in self.threads()}
        result = []
        for path in sorted((self.home/'automations').glob('*/automation.toml')):
            try: a = tomllib.loads(path.read_text())
            except (OSError, ValueError): continue
            if a.get('target_thread_id') not in tids: continue
            result.append({k: a.get(k) for k in ('id', 'name', 'kind', 'status', 'rrule', 'target_thread_id', 'last_run_at', 'next_run_at', 'updated_at')})
        return {'automations': result, 'observed_at': now(), 'bridge': self.dispatch_status()}

    def _db(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.folder/'commands.sqlite3', timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute('CREATE TABLE IF NOT EXISTS commands (id TEXT PRIMARY KEY, digest TEXT NOT NULL, action TEXT NOT NULL, '
                     'thread_id TEXT, payload TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, receipt TEXT)')
        return conn

    def dispatch_status(self):
        p = self.store.read('state/console/dispatcher.json')
        fresh = time.time()-p.get('observed_epoch', 0) < 150
        return {'online': bool(fresh and p.get('enabled')), 'observed_at': p.get('observed_at'),
                'mode': 'desktop_host_queue', 'latency_note': '宿主每分钟处理；本地产物每5秒刷新'}

    def enqueue(self, payload):
        cid = payload.get('command_id', '')
        if not re.fullmatch(r'[A-Za-z0-9_-]{12,100}', cid): raise ValueError('缺少有效指令ID')
        action = payload.get('action')
        if action not in {'message', 'intake', 'summarize', 'automation'}: raise ValueError('不支持的操作')
        tid = payload.get('thread_id')
        if action == 'message':
            t = self.thread(tid)
            if t['archived']: raise ValueError('归档会话只读，请先在宿主明确恢复')
            if not isinstance(payload.get('text'), str) or not 0 < len(payload['text'].strip()) <= 12000: raise ValueError('指令不能为空或超过12000字')
            if payload.get('artifact'):
                ref = payload['artifact'];actual = self.artifact(tid, ref.get('run_id'), ref.get('id'))
                if actual['sha256'] != ref.get('sha256'): raise ValueError('产物版本已变化，请重新查看后再反馈')
        elif action == 'intake':
            if not re.fullmatch(r'[A-Z]{2,8}-\d{8}-\d{3}', payload.get('code', '')): raise ValueError('需求编号格式不正确')
            if len(payload.get('note', '')) > 3000: raise ValueError('补充说明过长')
        elif action == 'automation':
            if not any(a['id'] == payload.get('automation_id') for a in self.automations()['automations']): raise ValueError('任务不属于本项目')
            if payload.get('operation') not in {'run', 'pause', 'resume'}: raise ValueError('未知调度操作')
        content = {k: v for k, v in payload.items() if k != 'command_id' and not k.startswith('_')}
        digest = fingerprint(content)
        with self.lock, self._db() as conn:
            prior = conn.execute('SELECT * FROM commands WHERE id=?', (cid,)).fetchone()
            if prior:
                if prior['digest'] != digest: raise ValueError('同一指令ID不能更改内容')
                return self._command(prior)
            if action == 'intake':
                for row in conn.execute("SELECT * FROM commands WHERE action='intake' AND status IN ('queued','dispatching','unknown','accepted')"):
                    if json.loads(row['payload']).get('code') == payload['code']:
                        return self._command(row)
            content['_ui_signature'] = hmac.new(self._secret(), (cid+digest).encode(), hashlib.sha256).hexdigest()
            conn.execute('INSERT INTO commands VALUES (?,?,?,?,?,?,?,?,?)',
                         (cid, digest, action, tid, json.dumps(content, ensure_ascii=False), 'queued', now(), now(), None))
            return self._command(conn.execute('SELECT * FROM commands WHERE id=?', (cid,)).fetchone())

    def _secret(self):
        path = self.folder/'ui-signing-key'
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return path.read_bytes()
        with os.fdopen(fd, 'wb') as stream:
            key = os.urandom(32)
            stream.write(key)
        return key

    @staticmethod
    def _command(row):
        return {'id': row['id'], 'action': row['action'], 'thread_id': row['thread_id'], 'status': row['status'],
                'created_at': row['created_at'], 'updated_at': row['updated_at'],
                'receipt': clean(json.loads(row['receipt'])) if row['receipt'] else None}

    def commands(self, thread_id=None):
        if not (self.folder/'commands.sqlite3').exists(): return []
        with self._db() as conn:
            rows = conn.execute('SELECT * FROM commands '+('WHERE thread_id=? ' if thread_id else '')+'ORDER BY created_at DESC LIMIT 30',
                                (thread_id,) if thread_id else ()).fetchall()
        return [self._command(row) for row in rows]
