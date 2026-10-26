"""Loopback-only, GET/HEAD-only workbench. Python standard library, no installs."""
from __future__ import annotations

import argparse
import json
import mimetypes
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from store import Store

STATIC = Path(__file__).resolve().parent / 'static'


class WorkbenchServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, root):
        self.store = Store(root)
        self.cache = None
        self.cache_at = 0
        self.cache_lock = threading.Lock()
        super().__init__(address, Handler)

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
            static = {'/': 'index.html', '/app.js': 'app.js', '/styles.css': 'styles.css', '/tokens.css': 'tokens.css'}
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
    parser = argparse.ArgumentParser(description='视频本地化工作台（本机只读）')
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
