"""A cached plugin must bind the intended project after moving machines."""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('console_plugin_workspace',
        ROOT/'plugins/session-console/workspace.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ConsolePluginWorkspaceTests(unittest.TestCase):
    def test_source_checkout_and_explicit_cached_plugin_binding(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'work/test-tmp') as temporary:
            checkout = Path(temporary)/'moved project'
            (checkout/'workbench').mkdir(parents=True)
            (checkout/'AGENTS.md').write_text('Project instructions')
            (checkout/'workbench/console_data.py').touch()
            plugin = checkout/'plugins/session-console'
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(module.workspace_root(plugin), checkout)
                with self.assertRaisesRegex(RuntimeError, 'VIDEO_LOCALIZER_WORKSPACE'):
                    module.workspace_root(Path(temporary)/'cache/plugin/0.3.0')
            with patch.dict(os.environ, {'VIDEO_LOCALIZER_WORKSPACE': str(checkout)}):
                self.assertEqual(module.workspace_root(Path(temporary)/'cache/plugin/0.3.0'), checkout)

    def test_invalid_explicit_binding_never_falls_back_to_another_project(self):
        with patch.dict(os.environ, {'VIDEO_LOCALIZER_WORKSPACE': str(ROOT/'work/nonexistent-project')}):
            with self.assertRaisesRegex(RuntimeError, 'VIDEO_LOCALIZER_WORKSPACE'):
                module.workspace_root(ROOT/'plugins/session-console')
