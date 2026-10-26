"""Meaningful safety, state and HTTP contracts against disposable workspaces."""
import hashlib
import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from server import WorkbenchServer
from store import Store


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
