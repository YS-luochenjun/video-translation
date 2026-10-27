"""Loopback workbench and resident evidence collector; bounded ledger writes only."""
from __future__ import annotations

import argparse
import json
import mimetypes
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from store import Store
from collector import Collector
from video_localizer.ledger import Conflict

STATIC = Path(__file__).resolve().parent / 'static'


class WorkbenchServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, root):
        self.store = Store(root)
        self.cache = None
        self.cache_at = 0
        self.cache_lock = threading.Lock()
        self.ledger_token = secrets.token_urlsafe(32)
        self.collector = Collector(root, self.store)
        super().__init__(address, Handler)
        self.collector.start()

    def server_close(self):
        self.collector.close()
        super().server_close()

    def snapshot(self):
        with self.cache_lock:
            if self.cache is None or time.monotonic() - self.cache_at > 2:
                self.cache = self.store.snapshot()
                self.cache_at = time.monotonic()
            return self.cache


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'LocalizationWorkbench/1'

    def log_message(self, fmt, *args):
        # Request paths may contain private task names. Keep normal requests quiet.
        pass

    def send_headers(self, code, length, mime='application/json; charset=utf-8', extra=None):
        self.send_response(code)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(length))
        self.send_header('Cache-Control', 'no-store')
        if self.close_connection:
            self.send_header('Connection','close')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()

    def json(self, code, value, head=False):
        body = json.dumps(value, ensure_ascii=False).encode('utf-8')
        self.send_headers(code, len(body))
        if not head:
            self.wfile.write(body)

    def do_GET(self):
        self.route()

    def do_HEAD(self):
        self.route(head=True)

    def do_POST(self):
        if urlsplit(self.path).path == '/api/ledger/action':
            return self.ledger_action()
        # Drain small rejected request bodies before closing: unread bytes can
        # cause Windows to reset the socket before the client receives the 405.
        try:
            length = max(0, int(self.headers.get('Content-Length', '0')))
        except ValueError:
            length = 0
        self.rfile.read(min(length, 65536))
        self.json(405, {'error': '此工作台只读取记录，不提供制作、修改或清理接口。'})
        self.close_connection = True

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST

    def ledger_action(self):
        self.close_connection = True
        try:
            expected = {f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'}
            host = self.headers.get('Host')
            if 'http://'+str(host) not in expected or self.headers.get('Origin') not in expected:
                raise PermissionError('跨站请求不允许')
            if not secrets.compare_digest(self.headers.get('X-Ledger-Token',''), self.server.ledger_token):
                raise PermissionError('请刷新工作台后重试')
            if self.headers.get_content_type() != 'application/json':
                raise ValueError('只接收 JSON')
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 32768:
                raise ValueError('请求过大或为空')
            payload = json.loads(self.rfile.read(length))
            action, spec = payload['action'], payload['data']
            if action == 'link':
                task = self.server.store.detail(spec.get('run_id'))
                if task.get('target_language') != spec.get('locale') or task.get('source_sha256') != spec.get('source_sha256'):
                    raise ValueError('任务的真实语言或源哈希不匹配')
            result = self.server.collector.ledger.action(action, spec, payload['operation_id'], payload.get('expected_revision'))
            return self.json(200, result)
        except PermissionError as exc:
            self.json(403, {'error': str(exc)})
        except Conflict as exc:
            self.json(409, {'error': str(exc)})
        except (ValueError, KeyError, TypeError):
            self.json(400, {'error': '输入不完整、时间范围不合法或关联证据不匹配；请核对后重试。'})
        except Exception:
            self.json(503, {'error': '台账暂不可写，请保留输入稍后重试。'})
        finally:
            self.close_connection = True

    def route(self, head=False):
        try:
            expected = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
            if self.headers.get('Host') not in expected:
                return self.json(403, {'error': '只接受本机访问'}, head)
            origin = self.headers.get('Origin')
            if origin and origin not in {'http://' + host for host in expected}:
                return self.json(403, {'error': '跨站请求不允许'}, head)
            url = urlsplit(self.path)
            args = parse_qs(url.query)
            arg = lambda key: args.get(key, [''])[0]
            store = self.server.store
            if url.path == '/api/ledger':
                result = self.server.collector.view()
                rows = result['requirements']
                result['unlinked_total'] = sum(not r.get('countable') for r in rows)
                query = arg('q').lower()
                state, locale, owner = arg('state'), arg('locale'), arg('owner').lower()
                if query:
                    rows = [r for r in rows if query in json.dumps([r['code'],r['title'],r.get('threads'),r.get('videos')],ensure_ascii=False).lower()]
                if state and state != 'all':
                    rows = [r for r in rows if (r.get('overdue') if state=='overdue' else not r.get('countable') if state=='unlinked' else r['state']==state)]
                elif state != 'unlinked':
                    rows = [r for r in rows if r.get('countable') is not False]
                if locale:
                    rows = [r for r in rows if any(locale in v['targets'] for v in r['videos'])]
                if owner:
                    rows = [r for r in rows if owner in json.dumps([r.get('claim'),r.get('threads')],ensure_ascii=False).lower()]
                days = int(arg('days') or 14)
                if days not in {7,14,30,90}: raise ValueError('Invalid period')
                result.update(requirements=rows, metrics=self.server.collector.ledger.metrics(rows,days=days), total_rows=len(result['requirements']), csrf_token=self.server.ledger_token)
                from store import clean
                token = result.pop('csrf_token')
                return self.json(200, {**clean(result), 'csrf_token': token}, head)
            if url.path == '/api/ledger/detail':
                from store import clean
                return self.json(200, clean(self.server.collector.ledger.detail(arg('id'))), head)
            if url.path == '/api/snapshot':
                return self.json(200, self.server.snapshot(), head)
            if url.path == '/api/task':
                return self.json(200, store.detail(arg('id')), head)
            if url.path == '/api/knowledge':
                return self.json(200, store.knowledge(), head)
            if url.path == '/api/document':
                return self.json(200, store.document(arg('path')), head)
            if url.path == '/api/media':
                return self.file(store.media(arg('path')), head)
            static = {'/': 'index.html', '/app.js': 'app.js', '/ledger.js': 'ledger.js', '/ledger.css': 'ledger.css', '/styles.css': 'styles.css', '/tokens.css': 'tokens.css'}
            if url.path in static:
                return self.file(STATIC / static[url.path], head)
            return self.json(404, {'error': '入口不存在'}, head)
        except FileNotFoundError:
            self.json(404, {'error': '文件或任务已不存在；稍后刷新查看最新记录。'}, head)
        except (ValueError, KeyError):
            self.json(400, {'error': '请求路径或记录不符合读取范围。'}, head)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except OSError:
            self.json(503, {'error': '记录暂时无法读取；请稍后刷新。'}, head)
        except Exception:
            self.json(500, {'error': '记录格式暂不兼容；其他任务仍可独立查看。'}, head)

    def file(self, path, head=False):
        with path.open('rb') as stream:
            length = path.stat().st_size
            start, end, code = 0, length - 1, 200
            extra = {'Accept-Ranges': 'bytes'}
            value = self.headers.get('Range')
            if value:
                match = re.fullmatch(r'bytes=(\d*)-(\d*)', value)
                if not match or not any(match.groups()) or length == 0:
                    return self.send_headers(416, 0, extra={'Content-Range': f'bytes */{length}'})
                first, last = match.groups()
                if first:
                    start = int(first)
                    end = min(int(last), end) if last else end
                else:
                    size = int(last)
                    start = max(0, length - size)
                if start > end or start >= length or (not first and int(last) == 0):
                    return self.send_headers(416, 0, extra={'Content-Range': f'bytes */{length}'})
                code = 206
                extra['Content-Range'] = f'bytes {start}-{end}/{length}'
            count = max(0, end - start + 1)
            mime = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
            if path.suffix == '.js':
                mime = 'text/javascript'
            if mime.startswith('text/'):
                mime += '; charset=utf-8'
            self.send_headers(code, count, mime, extra)
            if head:
                return
            stream.seek(start)
            remaining = count
            while remaining:
                part = stream.read(min(256 * 1024, remaining))
                if not part:
                    break
                self.wfile.write(part)
                remaining -= len(part)


def main():
    parser = argparse.ArgumentParser(description='视频本地化工作台与需求台账（本机）')
    parser.add_argument('--port', type=int, default=8768)
    parser.add_argument('--workspace', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    if not (args.workspace / 'AGENTS.md').is_file():
        parser.error('Workspace must contain AGENTS.md')
    with WorkbenchServer(('127.0.0.1', args.port), args.workspace) as server:
        print(f'Workbench ready: http://127.0.0.1:{server.server_port}', flush=True)
        try:
            server.serve_forever(poll_interval=.5)
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
