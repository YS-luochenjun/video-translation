import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from video_localizer import layout


class FontResolutionTests(unittest.TestCase):
    def test_project_font_precedes_system_font(self):
        with tempfile.TemporaryDirectory() as directory:
            font = Path(directory) / 'assets/fonts/arialbd.ttf'
            font.parent.mkdir(parents=True)
            font.write_bytes(b'fixture')
            with patch.object(layout.sys, 'platform', 'darwin'):
                self.assertEqual(layout.measurement_font(directory, 'Arial', True), font)

    def test_mac_arial_resolves_exact_regular_and_bold_faces(self):
        with patch.object(layout.sys, 'platform', 'darwin'), patch.object(Path, 'is_file', lambda p: str(p).startswith('/System/Library/Fonts/Supplemental/')):
            self.assertEqual(layout.measurement_font('/fixture', 'Arial').name, 'Arial.ttf')
            self.assertEqual(layout.measurement_font('/fixture', 'Arial', True).name, 'Arial Bold.ttf')
            self.assertEqual(layout.measurement_font('/fixture', 'Microsoft YaHei'), Path('/fixture/assets/fonts/msyh.ttc'))

    def test_windows_font_path_and_missing_face_remain_explicit(self):
        with patch.object(layout.sys, 'platform', 'win32'), patch.dict(layout.os.environ, {'WINDIR': '/fixture/windows'}), patch.object(Path, 'is_file', lambda p: p == Path('/fixture/windows/Fonts/arial.ttf')):
            self.assertEqual(layout.measurement_font('/fixture', 'Arial'), Path('/fixture/windows/Fonts/arial.ttf'))
            self.assertEqual(layout.measurement_font('/fixture', 'Arial', True), Path('/fixture/assets/fonts/arialbd.ttf'))
