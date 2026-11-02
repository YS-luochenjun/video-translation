"""No visible-cover production route; proof-bound exceptional blur and review."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_localizer import text_restoration as policy, fast_delivery, media, workflow
from video_localizer.common import WorkflowError, file_hash, write_json


class TextRestorationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)/'runs/new-contract'
        (self.run/'inputs').mkdir(parents=True)
        write_json(self.run/'inputs/request.json', {'text_restoration_contract_version': 1})
        p=self.run/'observed.jpg';p.write_bytes(b'actual fixture evidence')
        self.asset={'path':'observed.jpg','sha256':file_hash(p)}
        self.item={'id':'t001','action':'model_edit','target_text':'translated',
                   'restoration':{'method':'imagegen_repair','reason':'actual source repair', 'evidence':[self.asset]}}
        self.inv={'text_instances':[self.item]}
        self.candidate={'sha256':'a'*64,'plan_id':'plan'}
        write_json(self.run/'review/capture.json',{'video_sha256':'a'*64,'files':{'observed.jpg':self.asset['sha256']}})
        self.review={'text_restoration_review':[{'id':'t001','decision':'pass','visible_coverup':False,
                      'observation':'Actual encoded output checked; no cover block', 'evidence':[self.asset]}]}

    def fallback(self):
        self.item['restoration'].update(method='feathered_blur',fallback={
            'difficulty':'actual moving textured area with occlusion','wan_assessment':'observed candidate damages moving foreground',
            'attempts':[{'method':'wan_repair','outcome':'unsafe','observation':'actual candidate foreground damage','evidence':[self.asset]}],
            'opacity':.7,'feather_px':4,'source_motion_preserved':True})
        return self.item['restoration']['fallback']

    def test_natural_repair_and_technical_matte_remain_allowed(self):
        self.item['mask_selector']={'kind':'technical_only'}
        policy.validate(self.run,self.inv)
        self.assertEqual(policy.review_failures(self.run,self.inv,self.review,self.candidate),[])

    def test_solid_cover_and_added_pill_block_even_on_static_background(self):
        for change in ('solid','pill'):
            item=copy.deepcopy(self.item)
            if change=='solid':item.update(action='solid_overlay',background_is_static=True)
            else:item['display']={'pill':True}
            with self.subTest(change=change), self.assertRaises(WorkflowError):
                policy.validate(self.run,{'text_instances':[item]})

    def test_unknown_cover_alias_cannot_claim_natural_repair(self):
        for method in ['solid_cover','opaque_panel','hard_patch','mask','blur','mosaic']:
            self.item['restoration']['method']=method
            with self.subTest(method=method),self.assertRaises(WorkflowError):policy.validate(self.run,self.inv)

    def test_blur_requires_real_attempts_not_budget_only(self):
        fallback=self.fallback();policy.validate(self.run,self.inv)
        fallback['attempts']=[];fallback['difficulty']='budget exhausted'
        with self.assertRaisesRegex(WorkflowError,'after evidenced'):policy.validate(self.run,self.inv)

    def test_blur_must_be_transparent_feathered_and_motion_preserving(self):
        for key,value in [('opacity',1),('opacity',0),('opacity',float('nan')),('feather_px',0),('source_motion_preserved',False)]:
            fallback=self.fallback();fallback[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(WorkflowError):policy.validate(self.run,self.inv)

    def test_failed_candidate_evidence_cannot_change_silently(self):
        self.fallback();(self.run/'observed.jpg').write_bytes(b'changed')
        with self.assertRaises(WorkflowError):policy.validate(self.run,self.inv)

    def test_review_is_pending_and_never_auto_passes(self):
        rows=policy.review_template(self.inv)
        self.assertIsNone(rows[0]['visible_coverup'])
        self.assertTrue(policy.review_failures(self.run,self.inv,{'text_restoration_review':rows},self.candidate))
        self.assertTrue(policy.review_failures(self.run,self.inv,{},self.candidate))

    def test_visible_cover_cannot_be_waived_by_pass_or_high_score(self):
        self.review['text_restoration_review'][0]['visible_coverup']=True
        self.review['scores']={'visual_fidelity':5}
        self.assertIn('visible_coverup_or_unreviewed:t001',policy.review_failures(self.run,self.inv,self.review,self.candidate))
        failures=fast_delivery.review_failures(self.review,self.candidate,self.inv,self.run,[])
        self.assertIn('visible_coverup_or_unreviewed:t001',failures)

    def test_current_candidate_capture_required(self):
        write_json(self.run/'review/capture.json',{'video_sha256':'b'*64,'files':{'observed.jpg':self.asset['sha256']}})
        self.assertTrue(policy.review_failures(self.run,self.inv,self.review,self.candidate))

    def test_direct_renderer_rejects_cover_before_ffmpeg(self):
        self.item['action']='solid_overlay'
        with patch.object(media,'ffmpeg') as execute:
            with self.assertRaises(WorkflowError):media.render_local(None,{},[self.item],{},self.run/'out',self.run)
            execute.assert_not_called()

    def test_prohibited_coverup_is_not_ordinary_best_available(self):
        from video_localizer.fireplay_publication import _ordinary_best
        for kind in ['visible_solid_coverup','hard_edged_coverup','unapproved_blur_coverup']:
            assessment={'defects':[{'kind':kind,'severity':'minor','publication_impact':'ordinary'}],
                        'best_available':{'stop_condition':'budget_limit','reason':'stopped','evidence':['e']}}
            self.assertFalse(_ordinary_best(assessment,{'e'}, {'mode':'bounded_best_available'}))

    def test_historical_request_cannot_start_a_new_solid_cover_render(self):
        write_json(self.run/'inputs/request.json',{})
        self.item['action']='solid_overlay'
        with self.assertRaises(WorkflowError):policy.forbid_covers(self.run,[self.item])

    def test_original_container_preservation_and_historical_record_are_not_rewritten(self):
        self.item.update(action='preserve',display={'pill':True})
        policy.validate(self.run,self.inv)
        write_json(self.run/'inputs/request.json',{})
        self.item.update(action='solid_overlay')
        policy.validate(self.run,self.inv)
        self.assertEqual(policy.review_failures(self.run,self.inv,{},self.candidate),[])


if __name__=='__main__':unittest.main()
