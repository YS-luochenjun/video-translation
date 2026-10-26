import tempfile
import unittest
from pathlib import Path

from video_localizer import budgets, fast_delivery
from video_localizer.common import WorkflowError, file_hash, write_json
from video_localizer.native_composition import require_native_timing


class FastDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.run = self.root / 'runs/r1'
        self.run.mkdir(parents=True)
        evidence = self.run / 'observed.json'
        evidence.write_text('actual frozen evidence')
        self.asset = {'path': 'observed.json', 'sha256': file_hash(evidence)}
        self.candidate = {'sha256': 'c'*64, 'plan_id': 'p'}
        self.inventory = {'text_instances': [{'id': 'title'}, {'id': 'cta'}],
                          'speech_segments': [{'id': 'head'}, {'id': 'tail'}]}
        self.checks = ['speech_complete', 'protected_graphics', 'native_motion']
        self.review = {'video_sha256': 'c'*64, 'plan_id': 'p', 'reviewer': 'fixture', 'method': 'fixture',
                       'covered_text_ids': ['title','cta'], 'covered_speech_ids': ['head','tail'],
                       'checks': {c: {'decision':'pass','observation':'Observed fixture', 'evidence':[self.asset]}
                                  for c in self.checks}}

    def failures(self):
        return fast_delivery.review_failures(self.review,self.candidate,self.inventory,self.run,self.checks)

    def test_missing_tail_cannot_pass_even_with_pass_checkbox(self):
        self.review['covered_speech_ids'] = ['head']
        self.assertIn('speech_coverage_missing',self.failures())

    def test_changed_video_requires_new_observations(self):
        self.candidate['sha256'] = 'd'*64
        self.assertIn('review_binding_changed',self.failures())

    def test_changed_evidence_invalidates_check(self):
        (self.run/'observed.json').write_text('changed')
        self.assertIn('protected_graphics_evidence_changed',self.failures())

    def test_missing_motion_review_is_not_metadata_pass(self):
        del self.review['checks']['native_motion']
        self.assertIn('native_motion_unreviewed',self.failures())

    def test_minor_finish_passes_but_major_and_missing_playback_do_not(self):
        acceptance = {'minimum_score': 3, 'scale': 5, 'allowed_severities': ['minor']}
        self.review['visual_finish'] = {'score': 3, 'normal_speed_observation': 'Fixture full playback',
            'evidence': [self.asset], 'defects': [{'severity': 'minor', 'time_range': [1, 2],
                'observation': 'Small texture difference; no distraction in normal playback'}]}
        self.assertEqual(fast_delivery.visual_finish_failures(self.review, self.run, acceptance), [])
        self.review['visual_finish']['defects'][0]['severity'] = 'major'
        self.assertIn('visual_finish_blocking_or_unspecified_defect',
                      fast_delivery.visual_finish_failures(self.review, self.run, acceptance))
        self.review['visual_finish']['defects'] = []
        self.review['visual_finish']['normal_speed_observation'] = ''
        self.assertIn('visual_finish_playback_unreviewed',
                      fast_delivery.visual_finish_failures(self.review, self.run, acceptance))

    def test_finish_score_rejects_bool_nan_and_low_score(self):
        acceptance = {'minimum_score': 3, 'scale': 5, 'allowed_severities': ['minor']}
        for score in (True, float('nan'), 2, 6):
            self.review['visual_finish'] = {'score': score, 'normal_speed_observation': 'Observed',
                                          'evidence': [self.asset], 'defects': []}
            self.assertIn('visual_finish_below_threshold_or_unreviewed',
                          fast_delivery.visual_finish_failures(self.review, self.run, acceptance))

    def test_minor_finish_never_waives_basic_defect(self):
        self.review['checks']['protected_graphics']['decision'] = 'fail'
        self.assertIn('protected_graphics_unreviewed', self.failures())

    def test_native_mapping_rejects_short_clip_and_fps_changes(self):
        for values in [(134,60,30,30),(134,134,30,15)]:
            with self.assertRaises(WorkflowError): require_native_timing(*values)
        require_native_timing(134,134,30,30)

    def test_current_frame_graphics_restore_exactly(self):
        import sys
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'.runtime/deps/vision'))
        import numpy as np
        from video_localizer.native_composition import preserve_regions
        source=np.arange(120,dtype=np.uint8).reshape(10,4,3)
        altered=np.zeros_like(source)
        result=preserve_regions(altered,source,[(0,4,4,10)])
        self.assertTrue(np.array_equal(result[4:],source[4:]))
        self.assertTrue(np.all(result[:4]==0))

    def test_lower_budget_retains_unknown_and_rejects_dispatched_recovery(self):
        source=self.root/'source.mp4';source.write_bytes(b'fixture')
        write_json(self.run/'run.json',{'source':'source.mp4','source_sha256':file_hash(source)})
        (self.run/'source.mp4').write_bytes(source.read_bytes())
        scope=budgets.open_request({'authority':'user','authorization_ref':'human1','user_request':'test',
                                   'mode':'first','source':str(source)},self.root)['id']
        with budgets.operation():
            budgets.reserve(self.run,'a'*64,50)
            amended=budgets.amend_limit(scope,55,'human2','cap55',self.root)
            self.assertEqual(amended['credit_limit'],55)
            self.assertEqual(budgets.status(scope,self.root)['remaining_credits'],5)
            with self.assertRaises(WorkflowError): budgets.amend_limit(scope,49,'human3','cap49',self.root)
            budgets.resume_undispatched(self.run,'a'*64)
            budgets.authorize_request('https://api.kie.ai/api/v1/jobs/createTask',{'fixture':True})
            with self.assertRaisesRegex(WorkflowError,'dispatched'):
                budgets.resume_undispatched(self.run,'a'*64)


if __name__ == '__main__': unittest.main()
