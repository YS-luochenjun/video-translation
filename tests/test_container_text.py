import tempfile
import unittest
from pathlib import Path

from video_localizer.common import WorkflowError
from video_localizer.container_text import protected_patch_filters, render


class ContainerTextTests(unittest.TestCase):
    def setUp(self):
        from PIL import ImageFont
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.font = Path(self.folder.name) / 'test-font.ttf'
        self.font.write_bytes(ImageFont.load_default().path.getvalue())

    def test_patch_protection_uses_patch_local_intersection(self):
        self.assertEqual(protected_patch_filters([122, 202, 236, 62], [[34, 142, 177, 70]]),
                         ['drawbox=x=0:y=0:w=89:h=10:color=black:t=fill'])
        self.assertEqual(protected_patch_filters([122, 202, 236, 62], [[0, 0, 20, 20]]), [])

    def test_left_alignment_transparency_and_avatar_guard(self):
        from PIL import Image
        font = self.font
        spec = {'size': [160, 90], 'protected_regions': [[0, 30, 30, 30]], 'blocks': [
            {'id': 'reply', 'container': [0, 0, 160, 90], 'box': [35, 10, 120, 28],
             'lines': ['Reply', 'Name'], 'font': str(font), 'font_size': 12,
             'min_font_size': 12, 'align': 'left'},
            {'id': 'body', 'container': [0, 0, 160, 90], 'box': [35, 45, 120, 30],
             'lines': ['Easy'], 'font': str(font), 'font_size': 18,
             'min_font_size': 18, 'align': 'left'}]}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'text.png'
            report = render(spec, path)
            self.assertTrue(all(box[0] == 35 for b in report['blocks'] for box in b['glyph_boxes']))
            with Image.open(path) as im:
                self.assertEqual(im.getpixel((10, 40))[3], 0)
                self.assertEqual(im.getpixel((159, 89))[3], 0)
            spec['blocks'][1]['box'] = [10, 35, 100, 30]
            with self.assertRaises(WorkflowError):
                render(spec, path)

    def test_unreadable_copy_is_rejected_instead_of_silently_shrunk(self):
        font = self.font
        spec = {'size': [100, 30], 'blocks': [
            {'id': 'body', 'container': [0, 0, 100, 30], 'box': [0, 0, 15, 15],
             'lines': ['This cannot fit'], 'font': str(font), 'font_size': 14, 'min_font_size': 14}]}
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(WorkflowError):
                render(spec, Path(folder) / 'text.png')
