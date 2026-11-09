import unittest

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = np = None

from video_localizer.repair_masks import select
from video_localizer.common import WorkflowError


@unittest.skipIf(cv2 is None, 'Native vision dependencies required')
class CaptionOutlineSelectorTests(unittest.TestCase):
    def test_outline_qualifies_glyph_but_preserves_unrelated_white_art(self):
        frame = np.full((100,150,3),35,np.uint8)
        cv2.rectangle(frame,(10,10),(60,80),(220,245,0),-1)
        cv2.rectangle(frame,(15,15),(55,75),(255,255,255),-1)
        cv2.rectangle(frame,(90,20),(130,75),(255,255,255),-1)
        region = np.full((100,150),255,np.uint8)
        mask = select(frame,region,{'hsv_ranges':[[[0,0,210],[179,60,255]]],
                      'near_hsv_ranges':[[[75,130,110],[99,255,255]]],
                      'near_radius':8,'fill_holes':True,'dilate':2},cv2,np)
        self.assertEqual(mask[45,35],255)
        self.assertEqual(mask[45,110],0)
        self.assertEqual(mask[5,5],0)

    def test_nearby_settings_remain_explicit_and_bounded(self):
        frame=np.zeros((8,8,3),np.uint8)
        region=np.full((8,8),255,np.uint8)
        for extra in [{'near_radius':8},{'near_hsv_ranges':[[[0,0,0],[180,255,255]]]},
                      {'near_hsv_ranges':[[[0,0,0],[179,255,255]]],'near_radius':65}]:
            with self.assertRaises(WorkflowError):
                select(frame,region,{'hsv_ranges':[[[0,0,0],[179,255,255]]],**extra},cv2,np)
