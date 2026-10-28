"""A real still reference must survive validation, upload and journaled reuse."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from video_localizer import media, model_tasks, workflow
from video_localizer.common import WorkflowError, file_hash, read_json, write_json

TEMP = Path(__file__).resolve().parents[1] / 'work/test-tmp'
TEMP.mkdir(parents=True, exist_ok=True)


class WanReferenceAssetTests(unittest.TestCase):
    def setUp(self):
        from workspace_fixture import isolate_mock_provider
        isolate_mock_provider(self)
        self.temp = tempfile.TemporaryDirectory(dir=TEMP)
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)
        inputs = self.run / 'inputs'
        inputs.mkdir()
        self.video = inputs / 'source.mp4'
        media.ffmpeg(['-f', 'lavfi', '-i', 'color=c=blue:s=320x240:r=10:d=2',
                      '-c:v', 'libx264', '-pix_fmt', 'yuv420p', self.video])
        self.image = inputs / 'reference.png'
        Image.new('RGB', (320, 240), 'blue').save(self.image)
        write_json(self.run / 'run.json', {'source': 'inputs/source.mp4', 'source_sha256': file_hash(self.video)})
        self.data = {'source_sha256': file_hash(self.video), 'purpose': 'Synthetic Wan image reference regression',
                     'source_interval': [0, 2], 'estimated_credits': 32,
                     'assets': {'video': {'path': 'inputs/source.mp4', 'sha256': file_hash(self.video)},
                                'image': {'path': 'inputs/reference.png', 'sha256': file_hash(self.image)}},
                     'payload': {'model': 'wan/2-7-videoedit', 'input': {
                         'video_url': 'ASSET:video', 'reference_image': 'ASSET:image',
                         'prompt': 'Keep source motion; reference shows only the target background.',
                         'duration': 0, 'audio_setting': 'origin', 'prompt_extend': False}}}
        self.save()

    def save(self):
        write_json(self.run / 'inputs/task.json', self.data)

    def test_still_upload_and_single_creation_with_real_video_validation(self):
        uploads, calls = [], []
        class Client:
            def credits(self): return 1000
            def upload(self, path):
                uploads.append(path)
                return 'https://example.org/' + path.name
            def create(self, payload):
                calls.append(copy.deepcopy(payload))
                return 'synthetic-wan-reference-task'
        with patch.object(workflow, 'execution_limits', return_value={
                'max_paid_jobs_per_run': 10, 'max_estimated_credits_per_run': 60}):
            first = model_tasks.submit(self.run, 'inputs/task.json', Client())
            again = model_tasks.submit(self.run, 'inputs/task.json', Client())
        self.assertEqual(uploads, [self.video, self.image])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['input']['reference_image'], 'https://example.org/reference.png')
        self.assertEqual(calls[0]['input']['video_url'], 'https://example.org/source.mp4')
        self.assertEqual(calls[0]['input']['duration'], 0)
        self.assertTrue(again['reused'])
        self.assertEqual(first['task_id'], again['task_id'])
        job = read_json(self.run / 'jobs' / (first['job'] + '.json'))
        self.assertEqual(job['state'], 'submitted')

    def test_changed_or_corrupt_image_rejected_before_submission(self):
        self.image.write_bytes(b'not a png')
        with self.assertRaisesRegex(WorkflowError, 'asset missing or changed'):
            model_tasks.packet(self.run, 'inputs/task.json')
        self.data['assets']['image']['sha256'] = file_hash(self.image)
        self.save()
        with self.assertRaisesRegex(WorkflowError, 'reference image cannot be decoded'):
            model_tasks.packet(self.run, 'inputs/task.json')
        self.assertFalse(list((self.run / 'jobs').glob('*.json')))

    def test_reference_does_not_relax_video_duration(self):
        self.data['source_interval'] = [0, 3]
        self.save()
        with self.assertRaisesRegex(WorkflowError, 'clip duration differs'):
            model_tasks.packet(self.run, 'inputs/task.json')

    def test_reference_placeholder_requires_bound_image(self):
        del self.data['assets']['image']
        self.save()
        with self.assertRaisesRegex(WorkflowError, 'bound image asset'):
            model_tasks.packet(self.run, 'inputs/task.json')

    def test_unbound_extra_asset_cannot_be_uploaded(self):
        self.data['assets']['extra'] = self.data['assets'].pop('image')
        del self.data['payload']['input']['reference_image']
        self.save()
        with self.assertRaisesRegex(WorkflowError, 'unsupported or unbound'):
            model_tasks.packet(self.run, 'inputs/task.json')
