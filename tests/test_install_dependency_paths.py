import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_localizer.common import WorkflowError

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('dependency_path_installer', PROJECT / 'bin/install_dependencies.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallDependencyPathsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / 'code'
        requirements = self.root / 'bin/requirements'
        requirements.mkdir(parents=True)
        for group in ('core', 'vision', 'asr', 'separation'):
            (requirements / f'{group}.txt').write_text(f'{group}-fixture==1.0\n', encoding='utf-8')
        for target, value in (('registered_models', []), ('selected', 'small'),
                              ('policy', {'audio_analysis': 'remote', 'tts': 'remote', 'video': 'remote'})):
            mocked = patch.object(installer, target, return_value=value)
            mocked.start()
            self.addCleanup(mocked.stop)
        for name, value in (('prefix', str(self.root / '.venv')),
                            ('executable', str(self.root / '.venv/bin/python'))):
            mocked = patch.object(sys, name, value)
            mocked.start()
            self.addCleanup(mocked.stop)

    def plan(self):
        return installer.installation_plan(self.root)

    def test_core_uses_target_interpreter_purelib_for_each_layout(self):
        for directory in ('.venv/Lib/site-packages', '.venv/lib/python3.12/site-packages',
                          '.venv/lib64/python3.13/site-packages'):
            with self.subTest(directory=directory), \
                    patch('sysconfig.get_path', return_value=str(self.root / directory)) as get_path:
                plan = self.plan()
                self.assertEqual(plan['dependencies'][0]['directory'], directory)
                get_path.assert_called_once_with('purelib')
                self.assertEqual([(row['group'], row['directory']) for row in plan['dependencies'][1:]],
                                 [('vision', '.runtime/deps/vision'), ('asr', '.runtime/deps/asr'),
                                  ('separation', '.runtime/deps/separation')])
        self.assertFalse((self.root / '.venv').exists())
        self.assertFalse((self.root / '.runtime').exists())

    def test_foreign_interpreter_is_rejected_before_any_installation(self):
        foreign = Path(self.temp.name) / 'host'
        original_plan = installer.installation_plan
        with patch.object(installer, 'ROOT', self.root), \
                patch.object(installer, 'installation_plan', side_effect=lambda: original_plan(self.root)), \
                patch.object(sys, 'prefix', str(foreign)), \
                patch('sysconfig.get_path', return_value=str(foreign / 'site-packages')), \
                patch.object(installer.subprocess, 'run') as command, \
                patch.object(installer.model_cache, 'ensure') as download, \
                patch.object(installer, 'write_json') as write, \
                patch.object(sys, 'argv', ['install_dependencies.py', '--uv', 'fixture-uv']):
            with self.assertRaisesRegex(WorkflowError, 'interpreter|Python'):
                installer.main()
        command.assert_not_called()
        download.assert_not_called()
        write.assert_not_called()

    def test_host_interpreter_inside_code_root_is_still_rejected(self):
        with patch.object(sys, 'prefix', str(self.root)), \
                patch('sysconfig.get_path', return_value=str(self.root / 'lib/site-packages')):
            with self.assertRaisesRegex(WorkflowError, 'interpreter|Python'):
                self.plan()

    def test_external_or_non_venv_purelib_is_rejected_even_when_missing(self):
        for directory in (Path(self.temp.name) / 'host/site-packages',
                          self.root / 'lib/site-packages'):
            with self.subTest(directory=directory), \
                    patch('sysconfig.get_path', return_value=str(directory)):
                with self.assertRaises(WorkflowError):
                    self.plan()
                self.assertFalse(directory.exists())

    def test_plan_only_reads_layout_without_installing_or_creating_targets(self):
        directory = '.venv/lib/python3.12/site-packages'
        original_plan = installer.installation_plan
        with patch.object(installer, 'installation_plan', side_effect=lambda: original_plan(self.root)), \
                patch('sysconfig.get_path', return_value=str(self.root / directory)), \
                patch.object(installer.subprocess, 'run') as command, \
                patch.object(installer.model_cache, 'ensure') as download, \
                patch.object(installer, 'install_model') as models, \
                patch.object(installer, 'write_json') as write, \
                patch.object(sys, 'argv', ['install_dependencies.py', '--plan']), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            installer.main()
        self.assertEqual(json.loads(output.getvalue())['dependencies'][0]['directory'], directory)
        for operation in (command, download, models, write):
            operation.assert_not_called()
        self.assertFalse((self.root / '.venv').exists())
        self.assertFalse((self.root / '.runtime').exists())

    def test_external_executable_is_rejected_even_with_project_prefix(self):
        with patch.object(sys, 'executable', str(Path(self.temp.name) / 'host/python')), \
                patch('sysconfig.get_path', return_value=str(self.root / '.venv/lib/site-packages')):
            with self.assertRaisesRegex(WorkflowError, 'executable'):
                self.plan()

    def test_external_venv_and_purelib_links_are_rejected_without_symlink_privileges(self):
        original_resolve = Path.resolve
        for linked in (self.root / '.venv', self.root / '.venv/lib/site-packages'):
            external = Path(self.temp.name).resolve() / 'external'

            def resolve(path, *args, **kwargs):
                return external if path == linked else original_resolve(path, *args, **kwargs)

            with self.subTest(linked=linked), \
                    patch.object(Path, 'resolve', autospec=True, side_effect=resolve), \
                    patch('sysconfig.get_path', return_value=str(self.root / '.venv/lib/site-packages')):
                with self.assertRaisesRegex(WorkflowError, 'External'):
                    self.plan()

    def test_existing_external_non_core_link_still_blocks_installation(self):
        linked = self.root / '.runtime/deps/vision'
        linked.mkdir(parents=True)
        original_resolve = Path.resolve
        external = Path(self.temp.name).resolve() / 'external'
        original_plan = installer.installation_plan

        def resolve(path, *args, **kwargs):
            return external if path == linked else original_resolve(path, *args, **kwargs)

        with patch.object(installer, 'ROOT', self.root), \
                patch.object(installer, 'installation_plan', side_effect=lambda: original_plan(self.root)), \
                patch('sysconfig.get_path', return_value=str(self.root / '.venv/lib/site-packages')), \
                patch.object(Path, 'resolve', autospec=True, side_effect=resolve), \
                patch.object(installer, 'installed', return_value=True), \
                patch.object(installer.subprocess, 'run') as command, \
                patch.object(installer.model_cache, 'ensure') as download, \
                patch.object(sys, 'argv', ['install_dependencies.py', '--uv', 'fixture-uv']):
            with self.assertRaisesRegex(RuntimeError, 'External dependency link'):
                installer.main()
        command.assert_not_called()
        download.assert_not_called()

    def test_install_and_verification_use_same_actual_core_directory(self):
        directory = self.root / '.venv/lib/python3.12/site-packages'
        original_plan = installer.installation_plan
        with patch.object(installer, 'ROOT', self.root), \
                patch.object(installer, 'installation_plan', side_effect=lambda: original_plan(self.root)), \
                patch('sysconfig.get_path', return_value=str(directory)), \
                patch.object(installer, 'installed', side_effect=[False, True] * 4) as installed, \
                patch.object(installer.subprocess, 'run') as command, \
                patch.object(installer.model_cache, 'ensure', return_value=(self.root / '.runtime/model', {})), \
                patch.object(installer, 'write_json'), \
                patch.object(sys, 'argv', ['install_dependencies.py', '--uv', 'fixture-uv']), \
                patch.object(sys, 'path', list(sys.path)), \
                contextlib.redirect_stdout(io.StringIO()):
            installer.main()
        self.assertEqual(installed.call_args_list[0].args[1], directory)
        self.assertEqual(installed.call_args_list[1].args[1], directory)
        commands = [call.args[0] for call in command.call_args_list]
        self.assertEqual(len(commands), 4)
        self.assertNotIn('--target', commands[0])
        self.assertEqual(commands[0][commands[0].index('--python') + 1], sys.executable)
        for group, arguments in zip(('vision', 'asr', 'separation'), commands[1:]):
            self.assertEqual(arguments[arguments.index('--target') + 1], str(self.root / f'.runtime/deps/{group}'))
            self.assertIn('--upgrade', arguments)


if __name__ == '__main__':
    unittest.main()
