import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from video_localizer import budgets, model_tasks
from video_localizer.common import WorkflowError, file_hash, object_hash, read_json, write_json
from video_localizer.kie import ApiError


class ModelTaskUploadRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'work/test-tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = self.root / 'original.mp4'
        source.write_bytes(b'synthetic video fixture')
        self.run = self.root / 'runs/fixture'
        self.run.mkdir(parents=True)
        (self.run / 'source.mp4').write_bytes(source.read_bytes())
        write_json(self.run / 'run.json', {'source': 'source.mp4', 'source_sha256': file_hash(source)})
        self.scope = budgets.open_request({'authority': 'user', 'authorization_ref': 'fixture:human',
            'user_request': 'Synthetic recovery verification', 'mode': 'first',
            'source': str(source), 'targets': ['ar']}, self.root)['id']
        self.packet = {'source_sha256': file_hash(source), 'purpose': 'fixture', 'estimated_credits': 32,
            'assets': {'video': {'path': 'source.mp4', 'sha256': file_hash(source)}},
            'payload': {'model': 'wan/2-7-videoedit', 'input': {'video_url': 'ASSET:video'}}}
        self.digest = object_hash(self.packet)
        operation = budgets.operation()
        operation.__enter__()
        self.addCleanup(operation.__exit__, None, None, None)
        budgets.reserve(self.run, self.digest, 32)
        self.path = self.run / 'jobs' / (self.digest + '.json')
        self.old = {'id': self.digest, 'state': 'failed', 'estimated_credits': 32,
                    'error': 'KIE transport/response failure (URLError)', 'credits_consumed': None}
        write_json(self.path, self.old)
        self.client = Mock()
        self.client.credits.return_value = 100
        self.client.upload.return_value = 'https://example.test/actual-upload.mp4'
        def create(payload):
            budgets.authorize_request('https://api.kie.ai/api/v1/jobs/createTask', payload)
            return 'fixture-task'
        self.client.create.side_effect = create
        self.patch = patch.object(model_tasks, 'packet', return_value=self.packet)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_same_reservation_and_snapshot_then_idempotent(self):
        with self.assertRaisesRegex(WorkflowError, 'explicit upload recovery'):
            model_tasks.submit(self.run, 'packet.json', self.client)
        result = model_tasks.submit(self.run, 'packet.json', self.client, retry_upload=True)
        self.assertEqual(result['job'], self.digest)
        self.assertEqual(result['task_id'], 'fixture-task')
        self.assertEqual(self.client.create.call_args.args[0]['input']['video_url'], self.client.upload.return_value)
        job = read_json(self.path)
        self.assertEqual(read_json(self.run / job['upload_retry_history'][0]['path']), self.old)
        self.assertTrue(model_tasks.submit(self.run, 'packet.json', self.client, retry_upload=True)['reused'])
        self.assertEqual(self.client.create.call_count, 1)
        status = budgets.status(self.scope, self.root)
        self.assertEqual(len(status['reservations']), 1)
        self.assertEqual(status['reserved_or_billed_credits'], 32)

    def test_dispatch_without_task_id_blocks_before_upload(self):
        budgets.authorize_request('https://api.kie.ai/api/v1/jobs/createTask', self.packet['payload'])
        with self.assertRaisesRegex(WorkflowError, 'may have been dispatched'):
            model_tasks.submit(self.run, 'packet.json', self.client, retry_upload=True)
        self.client.upload.assert_not_called()
        self.client.create.assert_not_called()
        self.assertEqual(read_json(self.path), self.old)

    def test_ambiguous_or_known_task_only_reused(self):
        for state, task in [('ambiguous', None), ('failed', 'known-task')]:
            write_json(self.path, {**self.old, 'state': state, 'task_id': task})
            self.assertTrue(model_tasks.submit(self.run, 'packet.json', self.client, retry_upload=True)['reused'])
        self.client.upload.assert_not_called()
        self.client.create.assert_not_called()

    def test_two_pre_dispatch_recoveries_preserve_failures_and_stop(self):
        self.client.credits.side_effect = ApiError('KIE transport/response failure (URLError)')
        for _ in range(2):
            with self.assertRaises(ApiError):
                model_tasks.submit(self.run, 'packet.json', self.client, retry_upload=True)
        with self.assertRaisesRegex(WorkflowError, 'recovery limit'):
            model_tasks.submit(self.run, 'packet.json', self.client, retry_upload=True)
        self.assertEqual(len(read_json(self.path)['upload_retry_history']), 2)
        self.client.create.assert_not_called()
