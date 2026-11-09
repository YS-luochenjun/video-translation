"""Synthetic native-time composition, independent of paid model results."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

from video_localizer import media
from video_localizer.common import WorkflowError, file_hash, write_json

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('packed_regions', ROOT/'bin/compose_packed_regions.py')
module = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(module)
except ImportError:
    module = None


@unittest.skipIf(module is None, 'Vision dependencies required')
class RegionCompositionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT/'work/test-tmp')
        self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name)
        (self.run/'analysis').mkdir()
        for name, color in [('source.mp4', 'red'), ('proposal.mp4', 'blue')]:
            media.ffmpeg(['-f', 'lavfi', '-i', f'color=c={color}:s=64x48:r=30',
                          '-frames:v', '6', '-c:v', 'libx264', self.run/name])
        write_json(self.run/'run.json', {'source': 'source.mp4'})
        write_json(self.run/'analysis/media.json', {'width':64, 'height':48, 'fps':30})
        self.recipe = {'source_sha256':file_hash(self.run/'source.mp4'), 'frames':6,
                       'output':'outputs/composed.mp4', 'regions':[
            {'source_frames':[0,6], 'asset':{'path':'proposal.mp4', 'sha256':file_hash(self.run/'proposal.mp4')},
             'proposal_crop':[0,0,64,48], 'proposal_start_frame':0,
             'destination':[0,0,64,48], 'mask_bbox':[8,8,12,12]}]}

    def execute(self):
        write_json(self.run/'recipe.json', self.recipe)
        return module.execute(self.run, 'recipe.json')

    def test_native_full_length_output_preserves_review_boundary_and_existing_file(self):
        value = self.execute()
        result = media.probe(self.run/'outputs/composed.mp4')
        self.assertAlmostEqual(result['duration'], .2, places=2)
        self.assertEqual(result['fps'], 30)
        self.assertFalse(value['approved_for_reuse'])
        self.assertFalse(value['contains_target_typography'])
        with self.assertRaisesRegex(WorkflowError, 'existing outputs'):
            self.execute()

    def test_partial_frame_count_cannot_be_called_full_source_composition(self):
        self.recipe['frames'] = 5
        self.recipe['regions'][0]['source_frames'] = [0,5]
        with self.assertRaisesRegex(WorkflowError, 'full frame count'):
            self.execute()

    def test_actual_proposal_rate_is_verified_instead_of_trusting_recipe(self):
        media.ffmpeg(['-f','lavfi','-i','color=c=blue:s=64x48:r=24','-frames:v','6',
                      '-c:v','libx264',self.run/'proposal.mp4'])
        self.recipe['regions'][0]['asset']['sha256'] = file_hash(self.run/'proposal.mp4')
        with self.assertRaisesRegex(WorkflowError, 'Proposal must use'):
            self.execute()

    def test_source_flat_mask_cannot_escape_frame(self):
        self.recipe['regions'][0].update(method='source_flat_surface', mask_bbox=[-1,0,12,12])
        with self.assertRaisesRegex(WorkflowError, 'mask out of bounds'):
            self.execute()
