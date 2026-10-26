import tempfile
import os
import importlib.util
import hashlib
import io
import unittest
from pathlib import Path
from unittest.mock import patch

from video_localizer import model_cache, runtime
from video_localizer.common import WorkflowError, write_json


class ProjectRuntimeTests(unittest.TestCase):
    def test_caches_and_media_path_stay_in_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.runtime/ffmpeg/bin').mkdir(parents=True)
            with patch.dict(os.environ, {'HF_HOME': 'outside', 'PATH': 'old-tools'}), patch.object(tempfile, 'tempdir', None):
                runtime.configure(root)
                self.assertTrue(Path(os.environ['HF_HOME']).is_relative_to(root))
                self.assertTrue(Path(tempfile.gettempdir()).is_relative_to(root))
                self.assertEqual(os.environ['PATH'].split(os.pathsep)[0], str(root / '.runtime/ffmpeg/bin'))

    def test_model_download_is_hash_checked_and_existing_model_is_not_overwritten(self):
        spec = importlib.util.spec_from_file_location('install_dependencies', Path(__file__).resolve().parents[1] / 'bin/install_dependencies.py')
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = {'id': 'uvr-inst-hq3', 'path': '.runtime/models/separation/test.onnx', 'url': 'https://example.invalid/model', 'sha256': hashlib.sha256(b'expected model').hexdigest()}
            write_json(root / 'config/local-models.json', {'schema_version': 1, 'models': [record]})
            with self.assertRaisesRegex(WorkflowError, 'hash mismatch'):
                installer.install_model(record, root, opener=lambda *a, **k: io.BytesIO(b'wrong model'))
            self.assertFalse((root / record['path']).exists())
            installer.install_model(record, root, opener=lambda *a, **k: io.BytesIO(b'expected model'))
            installer.install_model(record, root, opener=lambda *a, **k: self.fail('Must reuse installed model'))
            (root / record['path']).write_bytes(b'changed')
            with self.assertRaisesRegex(WorkflowError, 'differs'):
                installer.install_model(record, root)

    def test_complete_asr_model_can_be_used_without_writing_download_lock(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'work/test-tmp') as tmp:
            root = Path(tmp)
            model = root / '.runtime/models/asr/small'
            model.mkdir(parents=True)
            for name in ('model.bin', 'config.json', 'tokenizer.json', 'vocabulary.txt'):
                (model / name).write_bytes(name.encode())
            with patch.object(model_cache, 'lock', side_effect=PermissionError('read-only installed model')):
                directory, hashes = model_cache.ensure('small', False, root)
            self.assertEqual(directory, model)
            self.assertEqual(set(hashes), {'model.bin', 'config.json', 'tokenizer.json', 'vocabulary.txt'})
            self.assertFalse((model / '.localizer-download.lock').exists())


if __name__ == '__main__':
    unittest.main()
