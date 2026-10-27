from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
import numpy as np
from PIL import Image
from video_localizer.alpha_assets import sanitize
from video_localizer.common import WorkflowError


class AlphaAssetTests(unittest.TestCase):
    def test_hidden_cleanup_preserves_low_alpha_edges_and_input(self):
        raw = np.array([[[255, 100, 20, 0], [80, 160, 250, 1],
                         [200, 40, 60, 127], [255, 255, 255, 255]]], dtype=np.uint8)
        original = Image.fromarray(raw)
        clean, record = sanitize(original)
        result = np.array(clean)
        np.testing.assert_array_equal(np.array(original), raw)
        np.testing.assert_array_equal(result[:, 1:], raw[:, 1:])
        np.testing.assert_array_equal(result[:, :, 3], raw[:, :, 3])
        self.assertEqual(result[0, 0].tolist(), [0, 0, 0, 0])
        self.assertEqual(record['cleared_hidden_rgb_pixels'], 1)

    def test_tight_crop_preserves_soft_support_and_original_anchor(self):
        raw = np.full((12, 18, 4), [90, 70, 50, 0], dtype=np.uint8)
        raw[3:8, 5:12, 3] = 1
        raw[4:7, 6:11, 3] = 255
        original = Image.fromarray(raw)
        crop, record = sanitize(original, crop=True, padding=1)
        self.assertEqual(record['origin'], [4, 2])
        self.assertEqual(record['visible_bbox'], [5, 3, 12, 8])
        self.assertEqual(crop.size, (9, 7))
        restored = Image.new('RGBA', original.size)
        restored.paste(crop, tuple(record['origin']))  # No mask: retain alpha exactly.
        clean, _ = sanitize(original)
        np.testing.assert_array_equal(np.array(restored), np.array(clean))
        self.assertNotEqual(crop.size, original.size)

    def test_empty_layer_keeps_canvas_and_unsupported_inputs_fail(self):
        image = Image.new('RGBA', (4, 7), (255, 0, 0, 0))
        clean, record = sanitize(image, crop=True)
        self.assertTrue(record['empty_foreground'])
        self.assertEqual(clean.size, image.size)
        self.assertFalse(np.any(np.array(clean)))
        for kwargs in [{'padding': -1}, {'padding': True}, {'crop': 'yes'}]:
            with self.assertRaises(WorkflowError): sanitize(image, **kwargs)
        with self.assertRaises(WorkflowError): sanitize(image.convert('RGB'))


if __name__ == '__main__':
    unittest.main()
