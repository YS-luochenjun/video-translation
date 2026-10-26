import copy
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_localizer import media, repair
from video_localizer.common import WorkflowError, file_hash, read_json, write_json

PROJECT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg needed')
class IncrementalRepairTests(unittest.TestCase):
    def setUp(self):
        (PROJECT/'work/test-tmp').mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=PROJECT/'work/test-tmp')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.run = self.root/'runs/fixture'
        self.run.mkdir(parents=True)
        media.ffmpeg(['-f','lavfi','-i','testsrc2=size=64x48:rate=10:duration=0.6',
                      '-c:v','ffv1',self.run/'source.mkv'])
        sha = file_hash(self.run/'source.mkv')
        write_json(self.run/'run.json', {'source':'source.mkv','source_sha256':sha})
        self.recipe = {'source_sha256':sha,'shots':[{'id':'s','start':0,'end':.6}],
            'operations':[{'method':'telea','shot':'s','start':.1,'end':.5,
                           'reason':'synthetic regression','bbox':[8,8,24,16]}]}

    def execute(self, name, recipe=None):
        write_json(self.run/f'{name}.json', recipe or self.recipe)
        return repair.execute(self.run, f'{name}.json')

    def pixels(self, result):
        return media.command(['ffmpeg','-v','error','-i',str(self.run/result['output']['path']),
                              '-f','framemd5','-']).stdout.splitlines()[10:]

    def test_boundary_edit_recomputes_only_affected_frame_and_matches_fresh(self):
        first = self.execute('one')
        self.recipe['operations'][0]['start'] = .2
        second = self.execute('two')
        self.assertEqual(second['incremental']['reused_frames'], 5)
        self.assertEqual(second['incremental']['computed_frames'], 1)
        self.assertFalse(second['approved_for_reuse'])
        self.assertEqual(file_hash(self.run/first['output']['path']), first['output']['sha256'])
        # A different run has no previous repair to borrow.
        original = self.run
        other = self.root/'runs/fresh'; other.mkdir()
        shutil.copyfile(original/'source.mkv', other/'source.mkv')
        shutil.copyfile(original/'run.json', other/'run.json')
        self.run = other
        fresh = self.execute('fresh')
        fresh_pixels = self.pixels(fresh)
        self.run = original
        self.assertEqual(self.pixels(second), fresh_pixels)

    def test_changed_parameters_invalidate_active_frames_only(self):
        self.execute('one')
        self.recipe['operations'][0]['bbox'] = [9,8,24,16]
        second = self.execute('two')
        self.assertEqual(second['incremental']['reused_frames'], 2)
        self.assertEqual(second['incremental']['computed_frames'], 4)

    def test_poisson_patch_is_explicit_experimental_and_keeps_protected_pixels(self):
        self.recipe['proposal_video'] = {'path':'source.mkv','sha256':file_hash(self.run/'source.mkv')}
        self.recipe['operations'][0].update(method='poisson_patch', experimental=True,
                                             protected_regions=[[14,12,4,4]])
        first = self.execute('poisson')
        self.assertFalse(first['automatic_pass'])
        self.assertEqual(first['incremental']['computed_frames'],6)
        self.assertTrue(self.execute('poisson')['reused'])
        self.recipe['operations'][0]['experimental'] = False
        with self.assertRaisesRegex(WorkflowError,'experimental'):
            self.execute('unapproved-method')

    def test_missing_old_master_recomputes_but_corruption_is_rejected(self):
        first = self.execute('one')
        output = self.run/first['output']['path']
        output.write_bytes(b'corrupt')
        self.recipe['operations'][0]['start'] = .2
        with self.assertRaisesRegex(WorkflowError, 'changed'):
            self.execute('two')
        output.unlink()
        second = self.execute('three')
        self.assertEqual(second['incremental']['reused_frames'], 0)

    def test_source_restore_and_horizontal_fill_preserve_protected_pixels(self):
        self.recipe['operations'] = [
            {'method':'horizontal_fill','shot':'s','start':0,'end':.6,'reason':'clean margins',
             'bbox':[0,8,64,16],'left_columns':[0,4],'right_columns':[60,64],
             'protected_regions':[[12,12,4,4]]}]
        result = self.execute('rows')
        from video_localizer.runtime import vision_path
        sys.path.insert(0, str(vision_path(PROJECT)))
        import cv2
        import numpy as np
        a = cv2.VideoCapture(str(self.run/'source.mkv'))
        b = cv2.VideoCapture(str(self.run/result['output']['path']))
        try:
            for _ in range(6):
                _, source = a.read(); _, actual = b.read()
                expected = source.copy()
                w = np.linspace(0,1,64)[None,:,None]
                expected[8:24] = np.rint(source[8:24,:4].mean(1)[:,None,:]*(1-w)
                    + source[8:24,60:].mean(1)[:,None,:]*w).astype(np.uint8)
                expected[12:16,12:16] = source[12:16,12:16]
                self.assertTrue(np.array_equal(expected, actual))
        finally:
            a.release(); b.release()

    def test_explicit_frame_boundary_avoids_rounded_container_timestamps(self):
        self.recipe['operations'][0]['frame_interval']=[1,5]
        self.recipe['operations'][0]['start']=.10001
        self.execute('one')
        self.recipe['operations'][0]['frame_interval']=[2,5]
        second=self.execute('two')
        self.assertEqual(second['incremental']['reused_frames'],5)
        self.recipe['operations'][0]['frame_interval']=[2,7]
        with self.assertRaisesRegex(WorkflowError,'coverage'):
            self.execute('invalid')

    def test_engine_and_source_change_invalidate_all_frames(self):
        self.execute('one')
        self.recipe['operations'][0]['reason']='same pixels, different explanation'
        with patch.object(repair,'_engine',return_value={'different':'decoder'}):
            second=self.execute('engine')
        self.assertEqual(second['incremental']['reused_frames'],0)
        media.ffmpeg(['-f','lavfi','-i','color=red:size=64x48:rate=10:duration=0.6',
                      '-c:v','ffv1',self.run/'source.mkv'])
        sha=file_hash(self.run/'source.mkv')
        write_json(self.run/'run.json',{'source':'source.mkv','source_sha256':sha})
        self.recipe['source_sha256']=sha
        third=self.execute('source')
        self.assertEqual(third['incremental']['reused_frames'],0)

    def test_changed_donor_invalidates_active_frames_and_index_tamper_blocks(self):
        self.recipe['operations'][0].update(method='temporal_frame',donor_time=0)
        self.execute('one')
        self.recipe['operations'][0]['donor_time']=.5
        second=self.execute('two')
        self.assertEqual(second['incremental']['reused_frames'],2)
        (self.run/second['frame_index']['path']).write_text('[]')
        self.recipe['operations'][0]['start']=.2
        with self.assertRaisesRegex(WorkflowError,'index changed'):
            self.execute('tampered')

    def test_expired_exact_checkpoint_rebuilds_without_overwriting_history(self):
        first=self.execute('one')
        old_record=self.run/first['output']['path']
        old_record=old_record.parent/'preparation.json'
        digest=file_hash(old_record)
        (self.run/first['output']['path']).unlink()
        second=self.execute('one')
        self.assertNotEqual(first['output']['path'],second['output']['path'])
        self.assertEqual(file_hash(old_record),digest)
        self.assertEqual(second['incremental']['reused_frames'],0)
