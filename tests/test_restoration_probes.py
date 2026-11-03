"""Evidence-binding regression tests; synthetic pictures do not prove real erasure."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_localizer import fast_delivery, media, quality_holds, restoration_probes as probes, text_restoration, work_packet
from video_localizer.common import WorkflowError, file_hash, read_json, write_json

PROJECT = Path(__file__).resolve().parents[1]


class RestorationProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=PROJECT/'work/test-tmp')
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)/'runs/restoration-fixture'
        self.run.mkdir(parents=True)

    def asset(self, path):
        return {'path': path, 'sha256': file_hash(self.run/path)}

    def test_native_boundaries_include_ghost_outside_target_window(self):
        item = {'id':'cta', 'start':.5, 'end':1, 'source_interval':[.2,.8],
                'source_ghost_interval':[.8,1.2]}
        self.assertEqual(probes.sample_frames(item, [n/10 for n in range(15)]), [1,2,4,7,8,9,11,12])

    def test_base_gaps_and_changed_dependencies_are_rejected(self):
        (self.run/'base.mkv').write_bytes(b'explicit fixture')
        asset = self.asset('base.mkv')
        base = {'segments':[{'start_frame':0,'end_frame':12,'asset_start_frame':0,'asset':asset}]}
        probes.validate_base(self.run, base, [asset])
        base['segments'][0]['start_frame'] = 1
        with self.assertRaisesRegex(WorkflowError, 'contiguous'):
            probes.validate_base(self.run, base, [asset])
        base['segments'][0]['start_frame'] = 0
        (self.run/'base.mkv').write_bytes(b'changed')
        with self.assertRaisesRegex(WorkflowError, 'dependency'):
            probes.validate_base(self.run, base, [asset])

    def fixture(self, fps=10):
        for name,color in [('source.mp4','blue'),('base1.mkv','green'),('base2.mkv','red'),('target.mp4','yellow')]:
            media.ffmpeg(['-f','lavfi','-i',f'color=c={color}:s=80x96:r={fps}:d=1',
                          '-c:v','libx264','-pix_fmt','yuv420p',self.run/name])
        write_json(self.run/'run.json', {'source':'source.mp4','source_sha256':file_hash(self.run/'source.mp4')})
        write_json(self.run/'inputs/request.json', {'text_restoration_contract_version':2})
        self.inv = {'text_instances':[{'id':'cta','start':.1,'end':.9,'bbox':[10,10,60,40],
            'display':{'bbox':[5,50,70,30]}, 'action':'reference_plate',
            'restoration':{'method':'same_source_donor','reason':'synthetic evidence binding only',
                           'evidence':[self.asset('base1.mkv')]}}]}
        write_json(self.run/'analysis/inventory.json', self.inv)
        self.candidate = {**self.asset('target.mp4'),'plan_id':'fixture'}
        self.plan = {'id':'fixture','restoration_probe_contract':1,'assets':[self.asset('base1.mkv'),self.asset('base2.mkv')],
            'restoration_base':{'segments':[
                {'start_frame':0,'end_frame':fps//2,'asset_start_frame':0,'asset':self.asset('base1.mkv')},
                {'start_frame':fps//2,'end_frame':fps,'asset_start_frame':fps//2,'asset':self.asset('base2.mkv')}]}}
        write_json(self.run/'plan.json', self.plan)

    def capture(self):
        result = probes.generate(self.run,self.candidate,self.plan)
        folder = (self.run/result['manifest']).parent
        capture = {'video_sha256':self.candidate['sha256'],'restoration_probes':result,
                   'files':{p.relative_to(self.run).as_posix():file_hash(p) for p in folder.iterdir()}}
        capture['files']['base1.mkv'] = file_hash(self.run/'base1.mkv')
        write_json(self.run/'review/capture.json',capture)
        return result,capture

    def test_actual_three_way_frames_mapping_reuse_and_review_binding(self):
        self.fixture()
        result,capture = self.capture()
        manifest = read_json(self.run/result['manifest'])
        self.assertEqual([r['source_frame'] for r in manifest['rows']], [0,1,4,8,9])
        self.assertEqual(manifest['rows'][-1]['base_asset'],self.asset('base2.mkv'))
        from PIL import Image
        with Image.open((self.run/result['manifest']).parent/manifest['rows'][-1]['image']) as image:
            w = image.width//3
            self.assertGreater(image.getpixel((w+10,10))[0], 200)  # actual red second base
            self.assertGreater(image.getpixel((2*w+10,10))[1], 200)  # actual yellow target
        self.assertFalse(result['automatic_pass'])
        with patch.object(media,'ffmpeg',side_effect=AssertionError('unchanged capture must reuse')):
            self.assertTrue(probes.generate(self.run,self.candidate,self.plan)['reused'])
        row = {'id':'cta','decision':'pass','visible_coverup':False,'source_text_removed':True,
               'background_continuity':True,'motion_preserved':True,'observation':'Synthetic contract fixture only',
               'evidence':[self.asset('base1.mkv')]}
        review = {'text_restoration_review':[row]}
        self.assertIn('clean_base_instance_unreviewed:cta',
                      text_restoration.review_failures(self.run,self.inv,review,self.candidate))
        coverage = probes.review_coverage(self.run,self.candidate,capture)
        row['clean_base_evidence'] = [{'path':p,'sha256':h} for p,h in sorted(coverage['cta'])]
        self.assertEqual(text_restoration.review_failures(self.run,self.inv,review,self.candidate),[])
        row['clean_base_evidence'].pop()
        self.assertIn('clean_base_instance_unreviewed:cta',
                      text_restoration.review_failures(self.run,self.inv,review,self.candidate))

    def test_changed_strip_cannot_reuse_or_review(self):
        self.fixture()
        result,capture = self.capture()
        folder = (self.run/result['manifest']).parent
        name = read_json(self.run/result['manifest'])['rows'][0]['image']
        (folder/name).write_bytes(b'changed evidence')
        with self.assertRaisesRegex(WorkflowError,'evidence changed'):
            probes.generate(self.run,self.candidate,self.plan)
        with self.assertRaisesRegex(WorkflowError,'strip changed'):
            probes.review_coverage(self.run,self.candidate,capture)

    def test_missing_base_never_becomes_automatic_pass(self):
        write_json(self.run/'analysis/inventory.json', {'text_instances':[{'id':'t','action':'model_edit'}]})
        result = probes.generate(self.run,{}, {})
        self.assertEqual(result['state'],'missing_clean_base')
        self.assertFalse(result['automatic_pass'])

    def test_wrong_base_frame_range_rejected_before_evidence(self):
        self.fixture()
        self.plan['restoration_base']['segments'][1]['asset_start_frame'] = 9
        with self.assertRaisesRegex(WorkflowError,'mapping changed'):
            probes.generate(self.run,self.candidate,self.plan)

    def test_native_30fps_matroska_millisecond_rounding_is_not_retiming(self):
        self.fixture(fps=30)
        result,_ = self.capture()
        rows = read_json(self.run/result['manifest'])['rows']
        self.assertEqual([r['source_frame'] for r in rows],[2,3,14,26,27])
        self.assertFalse(result['automatic_pass'])

    def test_more_than100_sparse_native_frames_do_not_overflow_ffmpeg_parser(self):
        path = self.run/'sparse.mp4'
        media.ffmpeg(['-f','lavfi','-i','color=c=blue:s=80x96:r=30:d=8','-c:v','libx264',path])
        numbers = list(range(0,240,2))
        files = probes._extract_sparse(path,numbers,[0,0,80,96],self.run/'sparse-frames')
        self.assertEqual(sorted(files),numbers)

    def test_new_language_movie_cannot_quality_pass_using_exact_held_base_bytes(self):
        self.fixture()
        root = self.run.parent.parent
        write_json(self.run/'review/observation.json',{'observation':'Explicit synthetic quality-hold fixture'})
        relative = lambda path: path.relative_to(root).as_posix()
        source = self.run/'source.mp4'
        held = self.run/'base1.mkv'
        evidence = self.run/'review/observation.json'
        spec = {'id':'held-base-fixture','source':{'path':relative(source),'sha256':file_hash(source)},
            'asset':{'path':relative(held),'sha256':file_hash(held)},'asset_kind':'neutral_master',
            'reason':'Synthetic held base must remain held across a new target movie hash',
            'reported_by':'fixture only','evidence':[{'path':relative(evidence),'sha256':file_hash(evidence)}]}
        write_json(root/'hold.json',spec)
        quality_holds.record('hold.json',root)
        self.plan['source_sha256'] = file_hash(source)
        self.candidate['recipe'] = 'recipe.json'
        write_json(self.run/'recipe.json',{'output':self.asset('target.mp4')})
        write_json(self.run/'outputs/candidate.json',self.candidate)
        with patch.object(fast_delivery,'validate_plan',return_value=self.plan), patch.object(media,'probe') as decode:
            with self.assertRaisesRegex(WorkflowError,'held-base-fixture'):
                fast_delivery.quality(self.run)
            decode.assert_not_called()


class CompletedRevisionNavigationTests(unittest.TestCase):
    def test_new_quality_feedback_overrides_old_completed_hint_without_retry_authority(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)/'runs/r1'
            run.mkdir(parents=True)
            old = {'video_sha256':'a'*64}
            with patch('video_localizer.quality_holds.active',return_value=[{'id':'actual-feedback'}]):
                result = work_packet._completion_navigation(run,'b'*64,old)
            self.assertEqual(result['state_hint'],'quality_feedback_requires_revision')
            self.assertIn('original budget',result['next_action'])
            self.assertIn('No automatic paid retry',result['next_action'])
            self.assertEqual(old,{'video_sha256':'a'*64})

    def test_new_candidate_not_hidden_by_historical_completion(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)/'runs/r1'
            write_json(run/'outputs/candidate.json',{'sha256':'c'*64})
            with patch('video_localizer.quality_holds.active',return_value=[]):
                result = work_packet._completion_navigation(run,'b'*64,{'video_sha256':'a'*64})
            self.assertEqual(result['state_hint'],'needs_review')
            self.assertEqual(result['current_candidate']['sha256'],'c'*64)


if __name__ == '__main__':
    unittest.main()
