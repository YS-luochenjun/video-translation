"""Meaningful safety, state and HTTP contracts against disposable workspaces."""
import hashlib
import http.client
import json
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from contextlib import closing
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from server import WorkbenchServer
from store import Store
from console_data import ConsoleData
from retry_activity_view import cached_summary, counts_for, import_failures, import_retries, read_page, view
from video_localizer.kie import ApiError, KieClient
from video_localizer.ledger import Ledger
from video_localizer.retry_activity import database, observed_job, record, timestamp


def sha(data):
    return hashlib.sha256(data).hexdigest()


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        # Tests never construct fixtures inside real production directories.
        temporary = Path(__file__).resolve().parents[1] / 'work/test-tmp'
        temporary.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='workbench-', dir=temporary)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root)
        self.put('AGENTS.md', b'fixture')

    def put(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())

    def run_fixture(self, name='video-a'):
        base = 'runs/' + name
        self.put(base + '/run.json', {'id': name, 'source': 'inputs/source.mp4', 'source_sha256': sha(b'source')})
        self.put(base + '/inputs/request.json', {'target_language': 'es', 'brief': 'Translate'})
        self.put(base + '/inputs/source.mp4', b'source')
        self.put(base + '/analysis/inventory.json', {'coverage': {}, 'text_instances': []})
        return base

    def test_kie_records_each_attempt_and_preserves_no_write_retry(self):
        run = self.root / 'runs' / 'video-a'
        opener = Mock()
        opener.open.side_effect = [
            HTTPError('https://api.kie.ai', 503, 'secret-message', {}, BytesIO(b'{}')),
            TimeoutError('secret-message'),
            BytesIO(b'{"code":200,"data":{"state":"success"}}'),
            HTTPError('https://api.kie.ai', 503, 'secret-message', {}, BytesIO(b'{}')),
        ]
        client = KieClient(key='secret-key', opener=opener)
        with patch('video_localizer.timing.current_run', return_value=run), \
                patch('video_localizer.budgets.authorize_request'), patch('video_localizer.kie.time.sleep'):
            self.assertEqual(client.status('secret-provider-id'), {'state': 'success'})
            with self.assertRaises(ApiError) as raised:
                client._request('https://api.kie.ai/api/v1/jobs/createTask', {'secret-payload': True})
        self.assertTrue(raised.exception.ambiguous)
        self.assertEqual(opener.open.call_count, 4)
        with closing(database(self.root)) as connection:
            events = read_page(connection, {}, '')['events']
        self.assertEqual(len(events), 4)
        self.assertNotIn('secret', json.dumps(events))
        retries = {event['attempt']: event for event in events if event['kind'] == 'retry'}
        self.assertEqual({index: event['outcome'] for index, event in retries.items()}, {1: 'failed', 2: 'success'})
        self.assertEqual(retries[2]['reason'], 'transport')

    def test_retry_history_paginates_and_only_imports_project_host_events(self):
        home = self.root / 'codex-fixture'
        home.mkdir()
        moment = int(time.time())
        with closing(sqlite3.connect(home / 'logs_2.sqlite')) as logs, logs:
            logs.execute('CREATE TABLE logs(id INTEGER PRIMARY KEY, ts, ts_nanos, feedback_log_body, thread_id, level, target)')
            for index in range(35):
                logs.execute('INSERT INTO logs VALUES(?,?,?,?,?,?,?)', (
                    index+1, moment, 0, 'retrying sampling request (1/5 in 0.1s) secret-message',
                    'project-thread', 'WARN', 'codex_core::responses_retry'))
            logs.execute("INSERT INTO logs VALUES(99,?,0,'retrying sampling request (1/5 in 0.1s)',"
                         "'other-thread','WARN','codex_core::responses_retry')", (moment,))
        with closing(sqlite3.connect(home / 'thread_history_1.sqlite')) as turns, turns:
            turns.execute('CREATE TABLE thread_turns(thread_id,turn_id,status,completed_at)')
            turns.execute("INSERT INTO thread_turns VALUES('project-thread','turn-1','failed',?)", (moment,))
        threads = {'project-thread': '测试会话'}
        with closing(database(self.root)) as connection:
            for _ in range(2):
                import_retries(home, connection, threads)
                import_failures(home, connection, threads)
            page = read_page(connection, threads, '')
            older = read_page(connection, threads, page['next_cursor'])
            self.assertEqual(read_page(connection, threads, None), {})
        events = page['events'] + older['events']
        self.assertEqual(len(page['events']), 30)
        self.assertEqual(len({event['id'] for event in events}), 36)
        self.assertEqual(sum(event['kind'] == 'failure' for event in events), 1)
        self.assertEqual({event['session'] for event in events}, {'测试会话'})
        self.assertNotIn('secret', json.dumps(events))

    def test_kie_job_retry_updates_outcome_without_duplicating_attempt(self):
        identifier = 'a' * 64
        path = self.root / 'runs' / 'video-a' / 'jobs' / f'{identifier}.json'
        job = {'id': identifier, 'created_at': '2026-11-24T08:00:00Z', 'retry_of': 'b' * 64,
               'retry_attempt': 2, 'state': 'preparing'}
        observed_job(path, job)
        observed_job(path, {**job, 'state': 'submitted'})
        with closing(database(self.root)) as connection:
            events = read_page(connection, {}, '')['events']
        self.assertEqual([(event['attempt'], event['outcome']) for event in events], [(2, 'submitted')])

    def test_retry_counts_are_requirement_scoped_and_exclude_preparation(self):
        first, second = 'fireplay:test-first', 'fireplay:test-second'
        first_code, second_code = 'ABC-20261124-001', 'ABC-20261124-002'
        ledger = Ledger(self.root)
        with ledger.connection(write=True) as db:
            for identifier, code, thread in ((first, first_code, 'thread-first'), (second, second_code, 'thread-second')):
                db.execute('INSERT INTO requirements VALUES(?,?,?)', (identifier, 1, json.dumps({
                    'code': code, 'threads': [{'threadId': thread}],
                })))
            db.execute('INSERT INTO tasks VALUES(?,?,?,?,?)', ('task-1', first, 'video:1', 'ja',
                                                               json.dumps({'runs': ['run-first']})))
        base = {'at': timestamp('2026-11-24T08:00:00Z'), 'kind': 'retry', 'attempt': 1}
        record(self.root, [
            {**base, 'id': 'log-one', 'source': 'codex', 'thread': 'thread-first'},
            {**base, 'id': 'log-two', 'source': 'codex', 'thread': 'thread-second'},
            {**base, 'id': 'log-unowned', 'source': 'codex', 'thread': 'thread-unowned'},
            {**base, 'id': 'kie-one', 'source': 'kie', 'run': 'run-first'},
        ])
        directory = f'state/fireplay/{first_code}'
        timeout = {'timeout_evidence': 'local-receipt', 'previous_operation': {
            'dispatched_at': '2026-11-24T08:00:00Z', 'state': 'unknown'}}
        outbox = {'requirement_id': 'test-first', 'code': first_code, 'video_index': 2,
                  'packages': [{'locale': 'ja'}], 'upload_attempts': {'upload-1': [timeout]}, 'operations': {}}
        self.put(directory + '/return-2.json', outbox)
        console = ConsoleData(self.root, codex_home=self.root / 'host-fixture')
        self.assertEqual(counts_for(cached_summary(console, ledger)[2], first),
                         {'codex': 1, 'kie': 1, 'fireplay': 0})
        upload = {'dispatched_at': '2026-11-24T08:01:00Z', 'attempt': 2, 'state': 'unknown'}
        outbox['operations']['upload-1'] = upload
        self.put(directory + '/return-revisions/return-2-old.json', outbox)
        outbox['operations']['upload-1'] = {**upload, 'state': 'verified'}
        self.put(directory + '/return-2.json', outbox)
        console.cache.clear()
        page = view(console, ledger, first)
        self.assertEqual(page['counts'], {'codex': 1, 'kie': 1, 'fireplay': 1})
        self.assertEqual({event['source'] for event in page['events']}, {'codex', 'kie', 'fireplay'})
        self.assertEqual(next(event for event in page['events'] if event['source'] == 'fireplay')['outcome'], 'success')
        self.assertEqual([event['id'] for event in view(console, ledger, second)['events']], ['log-two'])
        with ledger.connection(write=True) as db:
            db.execute('DELETE FROM tasks')
        console.cache.clear()
        self.assertEqual(view(console, ledger, first)['counts']['kie'], 1)

    def test_codex_counts_sent_followups_and_applied_handoffs_before_upload(self):
        code, requirement = 'ABC-20261124-001', 'fixture-requirement'
        identifier = 'fireplay:' + requirement
        folder = f'state/fireplay/{code}'
        predecessor, successor = 'old-thread', 'new-thread'
        handoff = folder + '/chat-handoff.json'
        identity = {'code': code, 'requirement_id': requirement, 'content_version': 'version'}
        chat = {'threadId': successor, 'predecessor_thread_id': predecessor, 'migration_receipt': handoff}
        self.put(folder + '/request.json', {**identity, 'chat': chat, 'videos': [{'index': 1, 'chat': chat}]})
        self.put(handoff, {**identity, 'status': 'READY', 'recorded_at': '2026-11-24T08:03:00Z',
                           'replacements': [{'code': code, 'old_thread_id': predecessor, 'new_thread_id': successor}]})
        self.put(folder + '/completion-check.json', {**identity, 'complete': True, 'expected_count': 1,
                                                      'verified_count': 1, 'platform_read_at': '2026-11-24T08:05:00Z'})
        task = {'code': code, 'video_index': 1, 'threadId': predecessor, 'key': 'original', 'missing_locales': ['ja']}
        confirmed = {'task': task, 'state': 'sent', 'dispatched_at': '2026-11-24T08:01:00Z',
                     'receipt': {'threadId': predecessor}}
        signals = 'state/fireplay/monitor/signals'
        self.put(signals + '/original.json', confirmed)
        self.put(signals + '/history/original/1.json', confirmed)
        self.put(signals + '/unknown.json', {**confirmed, 'state': 'unknown', 'task': {**task, 'key': 'unknown'}})
        self.put(signals + '/check.json', {**confirmed, 'task': {**task, 'key': 'check', 'missing_locales': []}})
        self.put(signals + '/late.json', {**confirmed, 'dispatched_at': '2026-11-24T08:06:00Z',
                                        'task': {**task, 'key': 'late'}})
        ledger = Ledger(self.root)
        with ledger.connection(write=True) as connection:
            connection.execute('INSERT INTO requirements VALUES(?,?,?)',
                               (identifier, 1, json.dumps({'code': code, 'threads': [{'threadId': successor}]})))
        console = ConsoleData(self.root, codex_home=self.root / 'host-fixture')
        page = view(console, ledger, identifier)
        self.assertEqual(page['counts'], {'codex': 2, 'kie': 0, 'fireplay': 0})
        self.assertEqual([(event['operation'], event['thread']) for event in page['events']],
                         [('owner_handoff', successor), ('owner_followup', predecessor)])
        console.cache.clear()
        self.assertEqual(view(console, ledger, identifier), page)

    def test_fireplay_binding_retry_uses_verified_receipts_and_counts_the_batch_once(self):
        requirement = 'test-first'
        identifier = 'fireplay:' + requirement
        directory = 'state/fireplay/ABC-20261125-001/receipts'
        prior = f'{directory}/2-bind-{"a" * 64}.json'
        self.put(prior, {'response': {'success': False, 'http_status': 502}})
        prior_operation = {
            'id': 'bind', 'tool': 'requirement_bind_materials', 'state': 'unknown',
            'dispatched_at': '2026-11-25T08:53:23Z', 'last_observed_receipt': prior,
            'arguments': {'items': [{'requirement_id': requirement, 'material_ids': ['existing', 'new-one', 'new-two']}]},
        }
        dispatch = {
            'dispatched_at': '2026-11-25T09:03:38Z', 'prior_operation': prior_operation,
            'prior_receipt_sha256': self.store.sha(prior),
            'arguments': {'items': [{'requirement_id': requirement, 'material_ids': ['new-one', 'new-two']}]},
        }
        self.put(f'{directory}/2-bind-user-retry-dispatch.json', dispatch)
        ledger = Ledger(self.root)
        console = ConsoleData(self.root, codex_home=self.root / 'host-fixture')
        self.assertEqual(view(console, ledger, identifier)['counts']['fireplay'], 0)
        receipt = {'dispatch': dispatch, 'response': {'results': [{'success': True}]}}
        self.put(f'{directory}/2-bind-{"b" * 64}.json', receipt)
        console.cache.clear()
        self.assertEqual(view(console, ledger, identifier)['events'][0]['outcome'], 'unknown')
        receipt['verification'] = {
            'serverTime': '2026-11-25T09:04:06Z',
            'items': [{'id': requirement, 'materials': [{'id': value} for value in ('existing', 'new-one', 'new-two')]}],
        }
        self.put(f'{directory}/2-bind-{"c" * 64}.json', receipt)
        self.put(f'{directory}/2-bind.json', receipt)
        console.cache.clear()
        page = view(console, ledger, identifier)
        self.assertEqual(page['counts']['fireplay'], 1)
        self.assertEqual(len(page['events']), 1)
        event = page['events'][0]
        self.assertEqual((event['operation'], event['reason'], event['outcome'], event['video_index']),
                         ('bind', 'http_502', 'success', 2))
        self.assertEqual(view(console, ledger, 'fireplay:test-second')['events'], [])

    def delivery(self, name='video-a', status='delivered_with_issues'):
        folder = 'outputs/source/es/version-' + name
        video = b'encoded translation'
        self.put(folder + '/final.mp4', video)
        metadata = {'source_sha256': sha(b'source'), 'target_language': 'es', 'origin_run_id': name,
                    'video_sha256': sha(video), 'status': status, 'technical_decision': 'pass' if status == 'delivered' else 'revise'}
        self.put(folder + '/manifest.json', {'kind': 'delivery', 'metadata': metadata})
        manifest_sha = self.store.sha(folder + '/manifest.json')
        entry = {**{k: v for k, v in metadata.items() if k != 'technical_decision'}, 'package': folder,
                 'manifest_sha256': manifest_sha, 'archived_at': '2026-10-23T08:00:00+00:00'}
        self.put('outputs/index.json', {'entries': [entry]})
        return folder

    def test_managed_index_authoritative_expired_and_hidden_boundary(self):
        import shutil
        folder = self.delivery(status='delivered')
        entry = self.store.read('outputs/index.json')['entries'][0]
        managed = 'outputs/.packages/REQ/es/task/version'
        (self.root/managed).parent.mkdir(parents=True)
        shutil.move(self.root/folder, self.root/managed)
        entry['package'] = managed
        self.put('state/delivery-index.json', {'entries': [entry]})
        rows = self.store.versions([])
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['usable'])
        self.assertEqual(self.store.media(managed+'/final.mp4'), self.root/managed/'final.mp4')
        for name in ['outputs/.other/video.mp4', 'outputs/.packages/../secret.mp4',
                     'outputs/.packages/.secret/file.mp4', 'state/.credentials/video.mp4']:
            with self.assertRaises(ValueError):
                self.store.path(name)
        entry['expired_at'] = '2026-11-01T00:00:00Z'
        self.put('state/delivery-index.json', {'entries': [entry]})
        shutil.rmtree(self.root/managed)
        # Stale legacy index cannot revive an expired entry.
        task = self.store.snapshot()['tasks'][0]
        self.assertEqual(task['state'], 'expired')
        self.assertFalse(task['output_available'])
        self.assertEqual(task['quality_state'], 'reference')
        self.put('knowledge/local/quality-holds/' + sha(b'source') + '/' + sha(b'encoded translation') + '/index.json', {'entries': []})
        self.assertEqual(self.store.snapshot()['tasks'][0]['quality_state'], 'hold')
        warnings = []
        self.put('state/delivery-index.json', b'{')
        self.assertEqual(self.store.versions(warnings), [])
        self.assertTrue(warnings)

    def test_retired_run_stays_visible_and_issues_never_become_pass(self):
        self.delivery()
        result = self.store.snapshot()
        self.assertEqual(result['stats']['tasks'], 1)
        task = result['tasks'][0]
        self.assertTrue(task['archived'])
        self.assertTrue(task['output_available'])
        self.assertEqual(task['state'], 'delivered_with_issues')
        self.assertEqual(task['quality_state'], 'issues')
        self.assertEqual(self.store.detail('video-a')['versions'][0]['media']['integrity'], 'matched')

    def test_video_or_manifest_tampering_cannot_keep_green_status(self):
        folder = self.delivery(status='delivered')
        self.assertEqual(self.store.snapshot()['tasks'][0]['quality_state'], 'pass')
        self.put(folder + '/final.mp4', b'changed')
        self.assertEqual(self.store.snapshot()['tasks'][0]['quality_state'], 'invalid')
        self.put(folder + '/final.mp4', b'encoded translation')
        self.put(folder + '/manifest.json', {'kind': 'delivery', 'metadata': {}})
        self.assertEqual(self.store.snapshot()['tasks'][0]['quality_state'], 'invalid')

    def test_quality_hold_overrides_historical_pass(self):
        self.delivery(status='delivered')
        self.put('knowledge/local/quality-holds/' + sha(b'source') + '/' + sha(b'encoded translation') + '/index.json', {'entries': []})
        self.assertEqual(self.store.snapshot()['tasks'][0]['quality_state'], 'hold')

    def test_new_candidate_does_not_inherit_old_archive_approval(self):
        self.delivery(status='delivered')
        base = self.run_fixture()
        self.put(base + '/plan.json', {'id': 'new-plan'})
        self.put(base + '/outputs/new.mp4', b'new candidate')
        self.put(base + '/outputs/candidate.json', {'path': 'outputs/new.mp4', 'sha256': sha(b'new candidate'), 'plan_id': 'new-plan'})
        import os
        # Explicitly later than the archive; no wall-clock dependency.
        os.utime(self.root / base / 'outputs/candidate.json', (1900000000, 1900000000))
        task = self.store.detail('video-a')
        self.assertEqual(task['state'], 'needs_review')
        self.assertEqual(task['quality_state'], 'not_reviewed')
        self.assertTrue(task['output']['path'].endswith('new.mp4'))

    def test_corrupt_task_isolated_and_new_task_appears_without_restart(self):
        self.run_fixture()
        self.put('runs/broken/run.json', b'{')
        result = self.store.snapshot()
        self.assertEqual(len(result['tasks']), 2)
        broken = next(t for t in result['tasks'] if t['id'] == 'broken')
        self.assertTrue(broken['warnings'])
        self.run_fixture('video-b')
        self.assertEqual(len(self.store.snapshot()['tasks']), 3)

    def test_missing_coverage_is_not_pass_and_no_read_creates_files(self):
        base = self.run_fixture()
        self.put(base + '/analysis/codex/results/record.json', {'stage': 'recognize', 'report': {'knowledge_read': ['knowledge/rules/a.md']}})
        self.put('knowledge/index.json', {'entries': [{'id': 'a', 'path': 'knowledge/rules/a.md', 'status': 'active'}]})
        self.put('knowledge/rules/a.md', b'Method')
        before = {p.relative_to(self.root).as_posix(): sha(p.read_bytes()) for p in self.root.rglob('*') if p.is_file()}
        self.store.snapshot()
        value = self.store.detail('video-a')
        self.store.knowledge()
        self.store.document('knowledge/rules/a.md')
        after = {p.relative_to(self.root).as_posix(): sha(p.read_bytes()) for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(value['quality_state'], 'not_reviewed')
        self.assertEqual(value['state'], 'awaiting_agent_inventory')
        self.assertEqual(value['knowledge_usage'], [])
        self.assertEqual(value['codex_results'][0]['knowledge_read'], ['knowledge/rules/a.md'])

    def test_stale_review_or_inventory_does_not_appear_as_current_pass(self):
        base = self.run_fixture()
        self.put(base + '/outputs/candidate.mp4', b'candidate')
        self.put(base + '/outputs/candidate.json', {'path': 'outputs/candidate.mp4', 'sha256': sha(b'candidate'), 'plan_id': 'p'})
        self.put(base + '/plan.json', {'id': 'p', 'inventory_sha256': sha(b'other inventory')})
        self.put(base + '/outputs/quality.json', {'decision': 'pass', 'plan_id': 'p', 'video_sha256': sha(b'candidate')})
        self.assertEqual(self.store.detail('video-a')['quality_state'], 'stale')

    def test_paths_secrets_and_signed_urls_are_not_exposed(self):
        self.put('.env', b'KIE_API_KEY=private')
        self.put('knowledge/candidates/a.json', {'api_key': 'secret', 'url': 'https://example.com/a?token=secret'})
        for path in ('../.env', '.env', 'config/model-routing.json', 'knowledge/../../.env', 'C:/secret'):
            with self.assertRaises(ValueError):
                self.store.document(path)
        doc = self.store.document('knowledge/candidates/a.json')
        self.assertNotIn('secret', doc['text'])
        with self.assertRaises(ValueError):
            self.store.media('knowledge/candidates/a.json')

    def start_server(self):
        server = WorkbenchServer(('127.0.0.1', 0), self.root)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def test_http_get_head_range_and_read_only_methods(self):
        base = self.run_fixture()
        server = self.start_server()
        client = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        self.addCleanup(client.close)
        url = '/api/media?path=' + base + '/inputs/source.mp4'
        client.request('GET', url, headers={'Range': 'bytes=1-3'})
        response = client.getresponse()
        self.assertEqual(response.status, 206)
        self.assertEqual(response.getheader('Content-Range'), 'bytes 1-3/6')
        self.assertEqual(response.read(), b'our')
        client.request('HEAD', url)
        response = client.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.read(), b'')
        client.request('GET', url, headers={'Range': 'bytes=99-'})
        response = client.getresponse()
        self.assertEqual(response.status, 416)
        response.read()
        client.request('GET', '/api/media?path=.env')
        response = client.getresponse()
        self.assertEqual(response.status, 400)
        response.read()
        client.request('GET', '/api/snapshot', headers={'Host': 'evil.example'})
        response = client.getresponse()
        self.assertEqual(response.status, 403)
        response.read()
        client.request('POST', '/api/task', body='{}')
        response = client.getresponse()
        self.assertEqual(response.status, 405)
        response.read()


if __name__ == '__main__':
    unittest.main(verbosity=2)
