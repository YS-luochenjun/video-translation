import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from video_localizer import media, model_tasks, workflow, wan3
from video_localizer.common import WorkflowError, file_hash, read_json, write_json
from workspace_fixture import isolate_mock_provider


class Wan3Tests(unittest.TestCase):
    def setUp(self):
        isolate_mock_provider(self)
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'work/test-tmp')
        self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name)
        self.video = self.run / 'source.mp4'
        media.ffmpeg(['-f', 'lavfi', '-i', 'color=c=blue:s=320x240:r=10:d=2',
                      '-c:v', 'libx264', '-pix_fmt', 'yuv420p', self.video])
        self.image = self.run / 'reference.png'
        Image.new('RGB', (320, 240), 'blue').save(self.image)
        write_json(self.run / 'run.json', {'source': 'source.mp4', 'source_sha256': file_hash(self.video)})
        self.data = {'source_sha256': file_hash(self.video), 'purpose': 'Synthetic Wan3 reference editing regression',
                     'source_interval': [0, 2], 'estimated_credits': 64,
                     'assets': {'video': {'path': 'source.mp4', 'sha256': file_hash(self.video)},
                                'image': {'path': 'reference.png', 'sha256': file_hash(self.image)}},
                     'payload': {'model': wan3.MODEL, 'input': wan3.inputs('Erase lettering only.', 2, reference=True)}}

    def packet(self):
        write_json(self.run / 'task.json', self.data)
        return model_tasks.packet(self.run, 'task.json')

    def test_reference_upload_payload_and_idempotent_submission(self):
        uploads, calls = [], []
        class Client:
            def credits(self): return 1000
            def upload(self, path):
                uploads.append(path)
                return 'https://example.org/' + path.name
            def create(self, payload):
                calls.append(copy.deepcopy(payload))
                return 'synthetic-wan3-task'
        self.packet()
        with patch.object(workflow, 'execution_limits', return_value={
                'max_paid_jobs_per_run': 10, 'max_estimated_credits_per_run': 100}):
            first = model_tasks.submit(self.run, 'task.json', Client())
            again = model_tasks.submit(self.run, 'task.json', Client())
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(uploads), 2)
        value = calls[0]['input']
        self.assertEqual(value['reference_video_urls'], ['https://example.org/source.mp4'])
        self.assertEqual(value['reference_image_urls'], ['https://example.org/reference.png'])
        self.assertEqual(value['resolution'], '720P')
        self.assertFalse(value['audio'])
        self.assertEqual(first['task_id'], again['task_id'])
        self.assertTrue(again['reused'])

    def test_underreserved_reference_duration_rejected(self):
        self.data['estimated_credits'] = 32
        with self.assertRaises(WorkflowError): self.packet()

    def test_legacy_and_unbounded_duration_rejected(self):
        for value in (0, -1, True, 5):
            self.data['payload']['input']['duration'] = value
            with self.subTest(value=value), self.assertRaises(WorkflowError): self.packet()

    def test_old_fields_cannot_be_forwarded(self):
        self.data['payload']['input']['audio_setting'] = 'origin'
        with self.assertRaisesRegex(WorkflowError, 'Unsupported Wan 3.0'): self.packet()

    def test_transparent_reference_rejected(self):
        Image.new('RGBA', (320, 240), (0, 0, 255, 0)).save(self.image)
        self.data['assets']['image']['sha256'] = file_hash(self.image)
        with self.assertRaisesRegex(WorkflowError, 'transparency'): self.packet()

    def test_no_extra_unbound_asset_and_no_generated_audio(self):
        self.data['payload']['input'].pop('reference_image_urls')
        with self.assertRaisesRegex(WorkflowError, 'unbound'): self.packet()
        self.data['assets'].pop('image')
        self.packet()
        self.data['payload']['input']['audio'] = True
        with self.assertRaisesRegex(WorkflowError, 'silent'): self.packet()

    def test_current_default_and_old_task_readable(self):
        from video_localizer.model_routing import selected, require_remote_task
        self.assertEqual(selected('video'), wan3.MODEL)
        require_remote_task(wan3.MODEL)
        with self.assertRaises(WorkflowError): require_remote_task('wan/2-7-videoedit')
