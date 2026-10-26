import contextlib
import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from video_localizer import local_tts, model_cache, runtime
from video_localizer.common import WorkflowError, read_json, write_json

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('model_policy_installer', PROJECT / 'bin/install_dependencies.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class ModelInstallationPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.record = {'id': 'uvr-inst-hq3', 'path': '.runtime/models/separation/uvr.onnx',
                       'url': 'https://example.invalid/uvr.onnx',
                       'sha256': hashlib.sha256(b'fixture model').hexdigest()}
        write_json(self.root / 'config/local-models.json', {'schema_version': 1, 'models': [self.record]})

    @staticmethod
    def download_fixture(repo, local_dir, **kwargs):
        for name in ('model.bin', 'config.json', 'tokenizer.json', 'vocabulary.txt'):
            (Path(local_dir) / name).write_bytes(name.encode())

    def test_retired_asr_cannot_download_or_create_model_directory(self):
        downloader = Mock(side_effect=self.download_fixture)
        with patch.object(model_cache, 'preflight'):
            for size in ('base', 'large', '../base'):
                with self.subTest(size=size), self.assertRaises(WorkflowError):
                    model_cache.ensure(size, download=True, root=self.root, downloader=downloader)
        downloader.assert_not_called()
        self.assertFalse((self.root / '.runtime').exists())

    def test_default_asr_download_is_small_and_complete_assets_are_reused(self):
        downloader = Mock(side_effect=self.download_fixture)
        with patch.object(model_cache, 'preflight'):
            directory, assets = model_cache.ensure(download=True, root=self.root, downloader=downloader)
            self.assertEqual(directory.name, 'small')
            self.assertEqual(downloader.call_args.args[0], 'Systran/faster-whisper-small')
            self.assertEqual(model_cache.ensure(download=True, root=self.root, downloader=downloader)[1], assets)
        self.assertEqual(downloader.call_count, 1)

    def test_historical_asr_integrity_can_be_read_without_reenabling_installation(self):
        directory = self.root / '.runtime/models/asr/base'
        directory.mkdir(parents=True)
        self.download_fixture('', directory)
        before = {p.name: p.read_bytes() for p in directory.iterdir()}
        with patch.object(model_cache, 'lock', side_effect=AssertionError('read-only verification')):
            self.assertEqual(set(model_cache.verify(directory)), set(before))
            with self.assertRaises(WorkflowError):
                model_cache.ensure('base', download=True, root=self.root)
        self.assertEqual(before, {p.name: p.read_bytes() for p in directory.iterdir()})

    def test_generic_downloader_rejects_retired_or_unregistered_assets_before_io(self):
        opener = Mock(return_value=io.BytesIO(b'fixture model'))
        for changes in ({'id': 'lama'}, {'id': 'piper-en-lessac'}, {'id': 'rapidocr'},
                        {'path': '.runtime/models/inpaint/lama.onnx'},
                        {'url': 'https://example.invalid/another-model'}):
            with self.subTest(changes=changes), self.assertRaises(WorkflowError):
                installer.install_model({**self.record, **changes}, self.root, opener)
        opener.assert_not_called()
        self.assertFalse((self.root / '.runtime').exists())

    def test_install_plan_rejects_a_retired_model_added_to_manifest(self):
        write_json(self.root / 'config/local-models.json', {'schema_version': 1,
                   'models': [self.record, {**self.record, 'id': 'lama'}]})
        with self.assertRaises(WorkflowError):
            installer.installation_plan(self.root)
        self.assertFalse((self.root / '.runtime').exists())

    def test_stale_policy_cannot_reenable_retired_installers(self):
        policy = read_json(PROJECT / 'config/model-routing.json')
        policy.update(asr='base', separation='lama')
        write_json(self.root / 'config/model-routing.json', policy)
        write_json(self.root / 'config/local-models.json', {'schema_version': 1,
                   'models': [{**self.record, 'id': 'lama'}]})
        with self.assertRaises(WorkflowError):
            installer.installation_plan(self.root)
        with self.assertRaises(WorkflowError):
            model_cache.ensure(download=True, root=self.root)
        self.assertFalse((self.root / '.runtime').exists())

    def test_public_plan_lists_only_current_local_models_without_installing(self):
        with patch.object(installer.subprocess, 'run') as command, \
                patch.object(installer.model_cache, 'ensure') as download, \
                patch.object(installer, 'install_model') as install, \
                patch('sys.argv', ['install_dependencies.py', '--plan']), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            installer.main()
        plan = json.loads(output.getvalue())
        self.assertEqual(plan['asr'], 'small')
        self.assertEqual([row['id'] for row in plan['models']], ['uvr-inst-hq3'])
        self.assertEqual([row['group'] for row in plan['dependencies']], ['core', 'vision', 'asr', 'separation'])
        self.assertTrue(all((PROJECT / row['requirements']).is_file() for row in plan['dependencies']))
        command.assert_not_called()
        download.assert_not_called()
        install.assert_not_called()

    def test_retired_voice_install_has_no_cli_or_python_entry(self):
        self.assertFalse(hasattr(local_tts, 'install'))
        result = subprocess.run([sys.executable, str(PROJECT / 'bin/va.py'), 'voice-install', 'piper-en-lessac',
                                 str(self.root / 'not-a-package')], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 2)
        self.assertIn('invalid choice', result.stderr)

    def test_installer_model_override_is_rejected_by_argument_parser(self):
        result = subprocess.run([sys.executable, str(PROJECT / 'bin/install_dependencies.py'),
                                 '--plan', '--asr-models', 'base'], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 2)
        self.assertIn('unrecognized arguments', result.stderr)

    @unittest.skipUnless(shutil.which('pwsh') or shutil.which('powershell'), 'PowerShell required')
    def test_setup_rejects_removed_model_parameter_before_running_installer(self):
        setup = self.root / 'setup.ps1'
        shutil.copyfile(PROJECT / 'bin/setup.ps1', setup)
        result = subprocess.run([shutil.which('pwsh') or shutil.which('powershell'), '-NoProfile',
                                 '-NonInteractive', '-File', str(setup), '-AsrModels', 'base'],
                                capture_output=True, text=True, encoding='utf-8', errors='replace')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('AsrModels', result.stderr)
        self.assertFalse((self.root / '.runtime').exists())

    def test_vision_dependencies_do_not_fall_back_to_retired_ocr_installation(self):
        (self.root / '.runtime/deps/ocr/cv2').mkdir(parents=True)
        self.assertEqual(runtime.vision_path(self.root), self.root / '.runtime/deps/vision')
        self.assertFalse((self.root / '.runtime/deps/vision').exists())


if __name__ == '__main__':
    unittest.main()
