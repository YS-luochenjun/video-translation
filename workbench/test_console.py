"""Console authorization, project boundaries, artifact identity and durable dispatch."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
import http.client
import threading
from pathlib import Path

from console_data import ConsoleData
from console_dispatch import prepare, acknowledge


class ConsoleTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parents[1]/'work/test-tmp'
        parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)/'project';self.root.mkdir()
        self.home = Path(self.tmp.name)/'codex';self.home.mkdir()
        with sqlite3.connect(self.home/'state_5.sqlite') as db:
            db.execute('CREATE TABLE threads(id,name,title,cwd,archived,updated_at,created_at,rollout_path,source)')
            for n in range(17):
                db.execute('INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?)',
                           (f'thread-{n}', f'会话 {n}', f'原题 {n}', str(self.root), 0, n, 0, '', 'vscode'))
            db.execute('INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?)', ('outside', '其他项目', '', '/another', 0, 999, 0, '', 'vscode'))
        self.data = ConsoleData(self.root, codex_home=self.home)

    def put(self, path, value):
        p = self.root/path;p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(value, ensure_ascii=False));return p

    def fixture_artifact(self):
        self.put('state/fireplay/ABC-20261102-001/request.json', {'code': 'ABC-20261102-001',
                 'chat': {'threadId': 'thread-1'}, 'videos': [{'members': ['run-1']}]})
        p = self.root/'runs/run-1/assets/clean-base.jpg';p.parent.mkdir(parents=True);p.write_bytes(b'original image')
        return p

    def test_eight_per_page_search_all_and_project_isolation(self):
        self.assertEqual(len(self.data.overview()['sessions']), 8)
        self.assertEqual(self.data.overview()['total'], 17)
        self.assertEqual(len(self.data.overview(page=3)['sessions']), 1)
        self.assertEqual(self.data.overview(query='会话 0')['total'], 1)
        self.assertEqual(self.data.overview(page=900)['page'], 3)
        with self.assertRaises(ValueError):self.data.thread('outside')

    def test_missing_runtime_observation_is_never_idle(self):
        self.assertEqual(self.data.overview()['sessions'][0]['status'], 'unobserved')
        self.assertFalse(self.data.overview()['sessions'][0]['status_fresh'])

    def test_signed_queue_deduplicates_and_rejects_id_reuse(self):
        p = {'command_id': 'stable-command-0001', 'action': 'message', 'thread_id': 'thread-1', 'text': '继续当前任务'}
        first = self.data.enqueue(p)
        self.assertEqual(first, self.data.enqueue(p))
        with self.assertRaises(ValueError):self.data.enqueue({**p, 'text': '更改输入'})
        task = prepare(self.data)['commands'][0]
        self.assertEqual(task['args']['threadId'], 'thread-1')
        self.assertIn('stable-command-0001', task['args']['prompt'])
        self.assertEqual(task['tool'], 'send_message_to_thread')

    def test_unknown_is_not_automatically_redispatched(self):
        self.data.enqueue({'command_id': 'stable-command-0002', 'action': 'message', 'thread_id': 'thread-2', 'text': '检查'})
        self.assertEqual(len(prepare(self.data)['commands']), 1)
        second = prepare(self.data)
        self.assertEqual(second['commands'], [])
        self.assertEqual(second['unknown_do_not_resend'][0]['id'], 'stable-command-0002')
        acknowledge(self.data, 'stable-command-0002', {'native_receipt': 'verified'}, 'accepted')
        self.assertEqual(self.data.commands()[0]['status'], 'accepted')

    def test_tampered_queue_does_not_gain_user_authority(self):
        self.data.enqueue({'command_id': 'stable-command-0003', 'action': 'message', 'thread_id': 'thread-1', 'text': '原输入'})
        with self.data._db() as db:
            db.execute('UPDATE commands SET payload=?', (json.dumps({'action': 'message', 'thread_id': 'thread-1', 'text': '篡改'}),))
        self.assertEqual(prepare(self.data)['commands'], [])
        self.assertEqual(self.data.commands()[0]['status'], 'rejected')

    def test_artifact_node_ownership_hash_and_changed_version(self):
        p = self.fixture_artifact()
        rows = self.data.artifacts('run-1', [])
        self.assertEqual(rows[0]['node'], 'base')
        a = self.data.artifact('thread-1', 'run-1', rows[0]['id'])
        self.assertEqual(a['sha256'], hashlib.sha256(p.read_bytes()).hexdigest())
        with self.assertRaises(ValueError):self.data.artifact('thread-2', 'run-1', rows[0]['id'])
        p.write_bytes(b'changed image')
        with self.assertRaises(ValueError):
            self.data.enqueue({'command_id': 'stable-command-0004', 'action': 'message', 'thread_id': 'thread-1', 'text': '沿用这份',
                               'artifact': {'run_id': 'run-1', 'id': a['id'], 'sha256': a['sha256']}})

    def test_only_project_automations_are_exposed(self):
        folder = self.home/'automations/test';folder.mkdir(parents=True)
        p = folder/'automation.toml'
        p.write_text('id="test"\nname="本项目任务"\nstatus="ACTIVE"\ntarget_thread_id="thread-1"')
        self.assertEqual(len(self.data.automations()['automations']), 1)
        p.write_text('id="test"\nname="别的项目"\nstatus="ACTIVE"\ntarget_thread_id="outside"')
        self.assertEqual(self.data.automations()['automations'], [])

    def test_intake_has_one_active_command_for_exact_number(self):
        a = self.data.enqueue({'command_id': 'stable-intake-0001', 'action': 'intake', 'code': 'ABC-20261102-001'})
        b = self.data.enqueue({'command_id': 'stable-intake-0002', 'action': 'intake', 'code': 'ABC-20261102-001'})
        self.assertEqual(a['id'], b['id'])


class ConsoleHTTPTests(unittest.TestCase):
    setUp = ConsoleTests.setUp

    def server(self):
        from server import WorkbenchServer
        server = WorkbenchServer(('127.0.0.1', 0), self.root)
        server.console = self.data
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        return server

    def request(self, server, method, path, body=None, headers=None):
        c = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        c.request(method, path, body, headers or {})
        r = c.getresponse();result = (r.status, r.read());c.close();return result

    def test_command_requires_same_origin_and_server_token(self):
        server = self.server()
        body = json.dumps({'command_id': 'http-message-0001', 'action': 'message', 'thread_id': 'thread-1', 'text': '只读检查'})
        self.assertEqual(self.request(server, 'POST', '/api/console/command', body)[0], 403)
        headers = {'Content-Type': 'application/json', 'Origin': f'http://127.0.0.1:{server.server_port}', 'X-Ledger-Token': server.ledger_token}
        status, value = self.request(server, 'POST', '/api/console/command', body, headers)
        self.assertEqual(status, 200);self.assertEqual(json.loads(value)['status'], 'queued')
        self.assertEqual(self.request(server, 'POST', '/api/console/command', body, headers), (status, value))
        headers['Origin'] = 'https://example.com'
        self.assertEqual(self.request(server, 'POST', '/api/console/command', body, headers)[0], 403)

    def test_http_pages_and_unmatched_thread_access(self):
        server = self.server()
        status, body = self.request(server, 'GET', '/api/console/sessions?page=2')
        self.assertEqual(status, 200);self.assertEqual(len(json.loads(body)['sessions']), 8)
        self.assertEqual(self.request(server, 'GET', '/api/console/detail?id=outside')[0], 400)
        for path in ['/console', '/console/app.js', '/console/styles.css']:
            status, body = self.request(server, 'GET', path)
            self.assertEqual(status, 200);self.assertTrue(body)


if __name__ == '__main__':unittest.main(verbosity=2)
