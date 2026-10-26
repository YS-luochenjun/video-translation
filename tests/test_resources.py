import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from video_localizer import common, model_cache, resources
from video_localizer.common import WorkflowError, write_json


class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.run = self.root / 'runs/fixture'
        self.run.mkdir(parents=True)

    def test_busy_is_recoverable_without_removing_owner_lock(self):
        owner = self.root / 'state/resources/heavy-0.lock'
        with common.lock(owner):
            with self.assertRaisesRegex(WorkflowError, 'compute busy'):
                with resources.heavy(self.run, 'test'):
                    self.fail('Must not start expensive work')
            self.assertTrue(owner.exists())
        with resources.heavy(self.run, 'test'):
            with resources.heavy(self.run, 'nested'):
                self.assertTrue(owner.exists())
        self.assertFalse(owner.exists())

    def test_low_space_stops_before_work_and_preserves_existing_outputs(self):
        artifact = self.run / 'retained.mp4'
        artifact.write_bytes(b'old output')
        with patch.object(resources.shutil, 'disk_usage', return_value=SimpleNamespace(free=1024)):
            with self.assertRaisesRegex(WorkflowError, 'Insufficient disk'):
                with resources.heavy(self.run, 'test'):
                    self.fail('Must not start')
        self.assertEqual(artifact.read_bytes(), b'old output')

    def test_model_resume_does_not_download_complete_model_again(self):
        def download(repo, local_dir, **kwargs):
            for name in ('model.bin', 'config.json', 'tokenizer.json', 'vocabulary.txt'):
                (Path(local_dir) / name).write_bytes(name.encode())
        downloader = Mock(side_effect=download)
        with patch.object(model_cache, 'preflight'):
            directory, assets = model_cache.ensure('small', True, self.root, downloader)
            self.assertEqual(model_cache.ensure('small', True, self.root, downloader)[1], assets)
        self.assertEqual(downloader.call_count, 1)
        (directory / 'tokenizer.json').write_bytes(b'changed')
        with self.assertRaisesRegex(WorkflowError, 'changed since installation'):
            model_cache.ensure('small', True, self.root, downloader)

    def test_partial_download_has_no_success_receipt_and_can_resume(self):
        def broken(repo, local_dir, **kwargs):
            (Path(local_dir) / 'model.bin').write_bytes(b'partial')
            raise OSError('interrupted fixture')
        with patch.object(model_cache, 'preflight'), self.assertRaises(OSError):
            model_cache.ensure('small', True, self.root, broken)
        directory = self.root / '.runtime/models/asr/small'
        self.assertFalse((directory / 'localizer-complete.json').exists())
        self.assertFalse((directory / '.localizer-download.lock').exists())
        with self.assertRaisesRegex(WorkflowError, 'missing'):
            model_cache.ensure('small', False, self.root)
