import copy
import subprocess
import tempfile
import unittest
from pathlib import Path

from video_localizer.common import WorkflowError
from video_localizer.local_repair import prepare


class LocalRepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.spec = {'size': [64, 64], 'region': [16, 16, 32, 32], 'fps': 10,
                     'source_frames': 10, 'intervals': [[2, 6]], 'feather': 0,
                     'protected_regions': [[16, 16, 8, 8]],
                     'clips': [{'path': 'reviewed-clip.mp4', 'source_frames': [2, 6],
                                'actual_frames': 4, 'fps': 10}]}

    def test_mask_is_opaque_inside_and_protected_after_feathering(self):
        from PIL import Image
        self.spec['feather'] = 3
        prepare(self.spec, self.folder)
        with Image.open(self.folder / 'mask.png') as im:
            self.assertEqual(im.getpixel((16, 16)), 255)
            self.assertEqual(im.getpixel((6, 6)), 0)
            self.assertLess(im.getpixel((31, 31)), 255)

    def test_rejects_gaps_overlap_and_short_or_retimed_clips(self):
        for change in ('gap', 'overlap', 'short', 'fps', 'odd_crop'):
            spec = copy.deepcopy(self.spec)
            if change == 'gap':
                spec['intervals'] = [[1, 6]]
            elif change == 'overlap':
                spec['clips'].append(copy.deepcopy(spec['clips'][0]))
            elif change == 'short':
                spec['clips'][0]['actual_frames'] = 3
            elif change == 'fps':
                spec['clips'][0]['fps'] = 12
            else:
                spec['region'][0] = 15
            with self.subTest(change=change), self.assertRaises(WorkflowError):
                prepare(spec, self.folder)

    def test_real_ffmpeg_preserves_protection_native_window_and_full_opacity(self):
        import shutil
        ffmpeg = Path(__file__).resolve().parents[1] / '.runtime/ffmpeg/bin/ffmpeg'
        executable = str(ffmpeg) if ffmpeg.exists() else shutil.which('ffmpeg')
        if not executable:
            self.skipTest('FFmpeg unavailable')
        prepare(self.spec, self.folder)
        graph = (self.folder / 'filter.txt').read_text()
        result = subprocess.run([executable, '-v', 'error', '-f', 'lavfi', '-i',
            'color=red:s=64x64:r=10:d=1', '-f', 'lavfi', '-i', 'color=blue:s=64x64:r=10:d=0.4',
            '-loop', '1', '-i', str(self.folder / 'mask.png'), '-filter_complex', graph,
            '-map', '[v]', '-frames:v', '10', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'],
            capture_output=True, check=True)
        self.assertEqual(len(result.stdout), 10*64*64*3)
        def pixel(frame, x, y):
            offset = (frame*64*64+y*64+x)*3
            return result.stdout[offset:offset+3]
        for frame in range(10):
            self.assertGreater(pixel(frame, 18, 18)[0], 240)  # protected object
            self.assertGreater(pixel(frame, 4, 4)[0], 240)    # outside repair
            channel = 2 if 2 <= frame < 6 else 0
            self.assertGreater(pixel(frame, 30, 30)[channel], 240)
