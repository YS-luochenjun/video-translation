import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from video_localizer import readiness
from video_localizer.common import WorkflowError


class ReadinessTests(unittest.TestCase):
    def test_missing_fonts_and_removed_option_are_reported(self):
        with patch('video_localizer.layout.sys.platform', 'test'), tempfile.TemporaryDirectory() as directory, patch.object(readiness.media, 'command', return_value=SimpleNamespace(stdout='-version', stderr='')):
            result = readiness.inspect(Path(directory))
        self.assertEqual(result['status'], 'attention')
        self.assertEqual(result['fonts']['arial.ttf'], 'missing')
        self.assertFalse(result['reference_composite']['filter_complex_supported'])

    def test_supported_option_and_invalid_font_are_distinguished(self):
        with patch('video_localizer.layout.sys.platform', 'test'), tempfile.TemporaryDirectory() as directory:
            font = Path(directory) / 'assets/fonts/arial.ttf'
            font.parent.mkdir(parents=True)
            font.write_bytes(b'not a font')
            with patch.object(readiness.media, 'command', return_value=SimpleNamespace(stdout='-filter_complex filename  graph from file\n', stderr='')):
                result = readiness.inspect(Path(directory))
        self.assertTrue(result['reference_composite']['filter_complex_supported'])
        self.assertEqual(result['fonts']['arial.ttf'], 'invalid')

    def test_probe_failure_is_unknown_not_supported(self):
        with patch('video_localizer.layout.sys.platform', 'test'), tempfile.TemporaryDirectory() as directory, patch.object(readiness.media, 'command', side_effect=WorkflowError('unavailable')):
            result = readiness.inspect(Path(directory))
        self.assertIsNone(result['reference_composite']['filter_complex_supported'])
        self.assertEqual(result['status'], 'attention')
