import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from video_localizer import media
from video_localizer.common import WorkflowError, file_hash, read_json, write_json


PROJECT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('source_ui_glyph_repair', PROJECT/'bin/repair_source_ui_glyphs.py')
REPAIR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPAIR)


class SourceGlyphDonorTests(unittest.TestCase):
    def test_affine_uses_real_features_and_preserves_outside_crop(self):
        random = np.random.default_rng(17)
        original = random.integers(0, 256, (280, 320, 3), dtype=np.uint8)
        original = cv2.GaussianBlur(original, (3, 3), 0)
        matrix = np.float32([[1, 0, 6], [0, 1, 4]])
        donor = cv2.warpAffine(original, matrix, (320, 280), borderMode=cv2.BORDER_REFLECT101)
        damaged = original.copy()
        damaged[110:135, 100:175] = 255
        mask = np.zeros((280, 320), np.uint8)
        mask[105:140, 95:180] = 255
        result = REPAIR.registered_donor(damaged, donor, mask, [20, 20, 280, 240], cv2, np, 'source_affine')
        self.assertLess(float(np.abs(result[mask > 0].astype(float)-original[mask > 0]).mean()), 3)
        self.assertTrue(np.array_equal(result[:20], damaged[:20]))
        self.assertTrue(np.array_equal(result[:, :20], damaged[:, :20]))

    def test_unproven_motion_and_unknown_projection_are_rejected(self):
        original = np.zeros((96, 96, 3), np.uint8)
        mask = np.zeros((96, 96), np.uint8)
        with self.assertRaisesRegex(WorkflowError, 'registration matches'):
            REPAIR.registered_donor(original, original, mask, [0, 0, 96, 96], cv2, np, 'source_affine')
        with self.assertRaisesRegex(WorkflowError, 'Unsupported donor projection'):
            REPAIR.registered_donor(original, original, mask, [0, 0, 96, 96], cv2, np, 'unproven')

    def test_source_anchor_can_register_a_featureless_clean_donor(self):
        random = np.random.default_rng(29)
        original = cv2.GaussianBlur(random.integers(0, 256, (280, 320, 3), dtype=np.uint8), (3, 3), 0)
        matrix = np.float32([[1, 0, 6], [0, 1, 4]])
        anchor = cv2.warpAffine(original, matrix, (320, 280), borderMode=cv2.BORDER_REFLECT101)
        clean = np.full_like(anchor, 80)
        mask = np.zeros((280, 320), np.uint8)
        mask[105:140, 95:180] = 255
        result = REPAIR.registered_donor(original, clean, mask, [20, 20, 280, 240], cv2, np,
                                         'source_affine', registration_reference=anchor)
        self.assertTrue(np.all(result[mask > 0] == 80))
        self.assertTrue(np.array_equal(result[:20], original[:20]))

    def test_two_native_frames_keep_dimensions_when_clone_mutates_its_mask(self):
        with tempfile.TemporaryDirectory(dir=PROJECT/'work/test-tmp') as temporary:
            root = Path(temporary)
            run = root/'runs/native-donor-fixture'
            run.mkdir(parents=True)
            source = run/'source.mp4'
            media.ffmpeg(['-f','lavfi','-i','color=c=0x202040:s=96x96:r=30:d=0.067',
                          '-vf','drawbox=x=30:y=30:w=12:h=12:color=white:t=fill',
                          '-frames:v','2','-c:v','libx264','-pix_fmt','yuv420p',source])
            cv2.imwrite(str(run/'donor.png'),np.full((96,96,3),80,np.uint8))
            source_asset = {'path':'source.mp4','sha256':file_hash(source)}
            recipe = {'source':source_asset,'base_video':source_asset,'width':96,'height':96,'fps':30,'frames':2,
                      'output':'output.mp4','inspection_frames':[0,1], 'regions':[
                          {'id':'glyph','source_frames':[0,2],'polygon':[[20,20],[55,20],[55,55],[20,55]],
                           'selector':{'hsv_ranges':[[[0,0,210],[179,60,255]]],'dilate':2},
                           'donor':{'path':'donor.png','sha256':file_hash(run/'donor.png')},
                           'registration_bbox':[0,0,96,96],'blend':'poisson'}]}
            write_json(run/'recipe.json',recipe)

            def mutate_mask(donor, original, supplied_mask, center, mode):
                supplied_mask[:] = 0
                return donor

            with patch.object(REPAIR,'ROOT',root), patch.object(cv2,'seamlessClone',side_effect=mutate_mask):
                result = REPAIR.execute(run,'recipe.json')
            self.assertEqual(result['native_frames'],2)
            self.assertEqual(len(result['inspection_frames']),2)
            for snapshot in result['inspection_frames']:
                self.assertEqual(cv2.imread(str(run/snapshot['path'])).shape,(96,96,3))
            self.assertEqual(read_json(root/'state/repair-trials/native-donor-fixture.json')['attempts'][0]['state'],'completed')

    def test_optical_flow_tracks_native_anchor_instead_of_clean_artwork(self):
        original = np.full((96, 96, 3), 180, np.uint8)
        anchor = np.full_like(original, 100)
        donor = np.full_like(original, 40)
        mask = np.zeros((96, 96), np.uint8)
        mask[30:50, 30:50] = 255
        observed = {}

        class Flow:
            def calc(self, target, reference, previous):
                observed['reference'] = reference.copy()
                return np.zeros((96, 96, 2), np.float32)

        with patch.object(cv2, 'DISOpticalFlow_create', return_value=Flow()):
            result = REPAIR.registered_donor(original, donor, mask, [0, 0, 96, 96], cv2, np,
                                             registration_reference=anchor)
        self.assertTrue(np.all(observed['reference'] == 100))
        self.assertTrue(np.all(result == 40))

    def test_streamed_source_panel_reconstruction_preserves_foreground_and_base(self):
        with tempfile.TemporaryDirectory(dir=PROJECT/'work/test-tmp') as temporary:
            root = Path(temporary)
            run = root/'runs/native-panel-fixture'
            run.mkdir(parents=True)
            source = run/'source.mp4'
            base = run/'base.mp4'
            media.ffmpeg(['-f','lavfi','-i','color=c=yellow:s=96x96:r=30:d=0.067',
                          '-vf','drawbox=x=30:y=30:w=12:h=12:color=black:t=fill,drawbox=x=60:y=60:w=12:h=12:color=red:t=fill',
                          '-frames:v','2','-c:v','libx264','-pix_fmt','yuv420p',source])
            media.ffmpeg(['-f','lavfi','-i','color=c=blue:s=96x96:r=30:d=0.067',
                          '-frames:v','2','-c:v','libx264','-pix_fmt','yuv420p',base])
            selector = {'hsv_ranges': [[[0,0,0],[179,255,255]]]}
            recipe = {
                'source': {'path':'source.mp4','sha256':file_hash(source)},
                'base_video': {'path':'base.mp4','sha256':file_hash(base)},
                'width':96,'height':96,'fps':30,'frames':2,'output':'output.mp4','inspection_frames':[0,1],
                'regions': [
                    {'id':'source-panel','source_frames':[0,2],'polygon':[[20,20],[80,20],[80,80],[20,80]],
                     'selector':selector,'repair_method':'source_restore','bbox':[20,20,61,61]},
                    {'id':'native-glyph','source_frames':[0,2],'polygon':[[28,28],[44,28],[44,44],[28,44]],
                     'selector':selector,'repair_method':'horizontal_fill','bbox':[28,28,17,17],
                     'left_columns':[20,25],'right_columns':[48,53]},
                ],
            }
            write_json(run/'recipe.json',recipe)
            with patch.object(REPAIR,'ROOT',root):
                result = REPAIR.execute(run,'recipe.json')
            source_reader = cv2.VideoCapture(str(source))
            base_reader = cv2.VideoCapture(str(base))
            for snapshot in result['inspection_frames']:
                valid_source, original = source_reader.read()
                valid_base, baseline = base_reader.read()
                self.assertTrue(valid_source and valid_base)
                image = cv2.imread(str(run/snapshot['path']))
                self.assertTrue(np.array_equal(image[:20],baseline[:20]))
                self.assertTrue(np.array_equal(image[60:72,60:72],original[60:72,60:72]))
                self.assertGreater(float(image[32:40,32:40,1].mean()),200)
            source_reader.release()
            base_reader.release()


if __name__ == '__main__':
    unittest.main()
