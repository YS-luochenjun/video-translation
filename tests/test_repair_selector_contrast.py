import unittest

import cv2
import numpy as np

from video_localizer.common import WorkflowError
from video_localizer.repair_masks import select


class RepairSelectorContrastTests(unittest.TestCase):
    def test_bright_letter_is_selected_without_flat_bright_skin(self):
        frame = np.full((80, 120, 3), 205, np.uint8)
        frame[20:50, 30:34] = 245
        region = np.full((80, 120), 255, np.uint8)
        selector = {'hsv_ranges': [[[0, 0, 180], [179, 80, 255]]],
                    'top_hat': {'kernel': 17, 'minimum': 18}}
        mask = select(frame, region, selector, cv2, np)
        self.assertTrue(np.all(mask[23:47, 30:34] == 255))
        self.assertFalse(np.any(mask[:, 60:]))
        region[:, :32] = 0
        self.assertFalse(np.any(select(frame, region, selector, cv2, np)[:, :32]))

    def test_invalid_contrast_settings_are_rejected(self):
        frame = np.zeros((20, 20, 3), np.uint8)
        region = np.full((20, 20), 255, np.uint8)
        for contrast in [{'kernel': 16, 'minimum': 10}, {'kernel': 17, 'minimum': 0},
                         {'kernel': 17}, {'kernel': 17, 'minimum': 10, 'automatic': True}]:
            with self.subTest(contrast=contrast), self.assertRaises(WorkflowError):
                select(frame, region, {'hsv_ranges': [[[0, 0, 0], [179, 255, 255]]],
                                      'top_hat': contrast}, cv2, np)
