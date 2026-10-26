import sys
import unittest
from pathlib import Path

from video_localizer.runtime import vision_path
sys.path.insert(0, str(vision_path(Path(__file__).resolve().parents[1])))
import cv2
import numpy as np

from video_localizer import repair, repair_masks
from video_localizer.common import WorkflowError


class RepairSelectorTests(unittest.TestCase):
    def test_explicit_white_components_and_protection_never_escape_region(self):
        frame = np.zeros((80,100,3),np.uint8)
        frame[10:30,10:20] = 255
        frame[10:30,40:50] = 255
        frame[10,70] = 255
        op = {'method':'telea','bbox':[5,5,80,40],
              'mask_selector':{'hsv_ranges':[[[0,0,210],[179,60,255]]],
                               'components':{'area':[20,300]},'dilate':2},
              'protected_selectors':[{'bbox':[35,5,20,30],
                 'selector':{'hsv_ranges':[[[0,0,210],[179,60,255]]],'dilate':2}}]}
        mask = repair._mask(frame,op,0,cv2,np)
        self.assertGreater(np.count_nonzero(mask[:,5:30]),0)
        self.assertEqual(np.count_nonzero(mask[:,35:]),0)
        self.assertEqual(np.count_nonzero(mask[50:]),0)

    def test_invalid_selector_and_unknown_settings_reject(self):
        frame = np.zeros((16,16,3),np.uint8)
        region = np.ones((16,16),np.uint8)*255
        for spec in [{'hsv_ranges':[[[0,0,0],[180,255,255]]]},
                     {'hsv_ranges':[[[0,0,0],[179,255,255]]],'dilate':100},
                     {'hsv_ranges':[[[0,0,0],[179,255,255]]],'guess':True}]:
            with self.assertRaises(WorkflowError): repair_masks.select(frame,region,spec,cv2,np)

    def test_legacy_lama_recipe_is_rejected_before_model_execution(self):
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / 'recipe.json').write_text('{}', encoding='utf-8')
            recipe = {'operations': [{'method': 'lama'}]}
            with patch.object(repair, '_load', return_value=(recipe, run / 'source.mp4')), \
                    patch.object(repair, '_execute') as execute:
                with self.assertRaisesRegex(WorkflowError, 'LaMa inference is retired'):
                    repair.execute(run, 'recipe.json')
                execute.assert_not_called()
