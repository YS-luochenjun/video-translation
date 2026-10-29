"""Synthetic enqueue evidence: never contact Fireplay or publish a video."""
import copy
import unittest

import test_fireplay as fixtures
from video_localizer import fireplay, fireplay_monitor, fireplay_submission
from video_localizer import fireplay_youtube_handoff as handoff
from video_localizer.common import WorkflowError, file_hash, read_json, utc_now, write_json


class YouTubeHandoffTests(unittest.TestCase):
    setUp = fixtures.FireplayTests.setUp
    register = fixtures.FireplayTests.register
    record = fixtures.FireplayTests.record
    save = fixtures.FireplayTests.save
    downloaded = fixtures.FireplayTests.downloaded
    returned_setup = fixtures.FireplayTests.returned_setup

    def material(self, mid=fixtures.MID, url=None):
        return {'material': {'id': mid, 'currentVideoResourceId': fixtures.THREAD,
                'resources': [{'id': fixtures.THREAD, 'type': 'video', 'url': url}],
                'videoR2Url': 'https://example.com/source.mp4', 'postProcessStatus': 'done'}}

    def task(self, mid=fixtures.MID):
        return {'items': [{'task_id': fixtures.RESOURCE, 'material_id': mid,
                          'video_resource_id': fixtures.THREAD, 'status': 'pending'}]}

    def returned(self):
        self.returned_setup()
        fireplay.chat(fixtures.CODE, {'title': fixtures.CODE, 'threadId': fixtures.THREAD}, root=self.root)
        folder=self.root/'state/fireplay'/fixtures.CODE
        box=read_json(folder/'return-1.json')
        for i,mid in enumerate([fixtures.MID,fixtures.RESOURCE],1):
            for phase in ['upload','import','verify']:
                box['operations'][f'{phase}-{i}']={'state':'verified','result':{'material_id':mid}}
        box['operations']['bind']={'state':'verified','result':{'material_ids':[fixtures.MID,fixtures.RESOURCE]}}
        box['state']='returned';write_json(folder/'return-1.json',box)
        # Preserve the historical completion receipt before enabling the new gate.
        fireplay_submission.verify_completion(fixtures.CODE, {'serverTime':utc_now(),
            'items':[{'id':fixtures.RID,'materials':[{'id':fixtures.MID},{'id':fixtures.RESOURCE}]}]},self.root)
        old=file_hash(folder/'completion-check.json')
        write_json(self.root/'config/fireplay-youtube-routing.json',
                   {'require_requirement_group':False,'require_enqueue_evidence':True})
        return box,old

    def test_r2_ready_import_and_requested_flag_are_not_enqueue_proof(self):
        material=self.material()['material'];material['youtube_auto_upload_requested']=True
        with self.assertRaisesRegex(WorkflowError,'not YouTube enqueue evidence'):
            handoff.inspect(material)

    def test_task_must_match_current_material_resource_and_accepted_state(self):
        for key,value in [('material_id',fixtures.THREAD),('video_resource_id',fixtures.MID),
                          ('status','failed'),('task_id','not-a-real-task'),('task_type','transfer')]:
            task=self.task();task['items'][0][key]=value
            with self.subTest(key=key),self.assertRaises(WorkflowError):
                handoff.inspect(self.material()['material'],task)
        accepted=handoff.inspect(self.material()['material'],self.task())
        self.assertEqual(accepted['state'],'enqueue_verified')
        self.assertEqual(accepted['task_status'],'pending')

    def test_existing_current_youtube_url_needs_no_new_upload_task(self):
        self.assertEqual(handoff.inspect(self.material(url=fixtures.URL)['material'])['state'],'youtube_url_verified')
        material=self.material()['material']
        material['resources'].append({'id':fixtures.RESOURCE,'type':'video','url':fixtures.URL})
        with self.assertRaises(WorkflowError):handoff.inspect(material)

    def test_old_binding_stays_intact_but_completion_waits_for_each_enqueue(self):
        box,old=self.returned();folder=self.root/'state/fireplay'/fixtures.CODE
        self.assertFalse(fireplay_submission.completion_gate(self.record(),self.root)['can_close'])
        self.assertEqual(file_hash(folder/'completion-check.json'),old)
        self.assertEqual(fireplay.dispatch(fixtures.CODE,root=self.root)['state'],'needs_youtube_enqueue')
        tasks=fireplay_monitor.followups(self.root)
        self.assertEqual([t['action'] for t in tasks],['enable_youtube_upload'])
        for i,mid in enumerate([fixtures.MID,fixtures.RESOURCE]):
            spec={'material_receipt':self.material(mid),'task_receipt':self.task(mid),
                  'video_sha256':box['packages'][i]['sha256']}
            proof=handoff.record_receipt(fixtures.CODE,spec,self.root)
            self.assertEqual(proof['youtube_status'],'enqueue_verified')
            self.assertEqual(read_json(folder/'return-1.json'),box)
        self.assertTrue(fireplay_submission.completion_gate(self.record(),self.root)['can_close'])
        self.assertEqual(fireplay_monitor.followups(self.root),[])
        self.assertEqual(fireplay.dispatch(fixtures.CODE,root=self.root)['youtube_status'],'enqueue_verified')

    def test_wrong_output_hash_and_tampered_handoff_evidence_are_rejected(self):
        box,_=self.returned()
        spec={'material_receipt':self.material(),'task_receipt':self.task(),'video_sha256':'0'*64}
        with self.assertRaisesRegex(WorkflowError,'video hash'):
            handoff.record_receipt(fixtures.CODE,spec,self.root)
        spec['video_sha256']=box['packages'][0]['sha256']
        proof=handoff.record_receipt(fixtures.CODE,spec,self.root)
        (self.root/proof['receipt']).write_text('{}')
        with self.assertRaisesRegex(WorkflowError,'evidence changed'):
            fireplay_submission.completion_gate(self.record(),self.root)

    def test_partial_bound_batch_still_requires_its_actual_enqueue(self):
        box,_=self.returned()
        folder=self.root/'state/fireplay'/fixtures.CODE
        box['packages']=box['packages'][:1]
        box['pending_locales']=[self.record()['videos'][0]['targets'][1]]
        box['operations']['bind']['result']['material_ids']=[fixtures.MID]
        write_json(folder/'return-1.json',box)
        result=fireplay.dispatch(fixtures.CODE,root=self.root)
        self.assertEqual(result['state'],'needs_youtube_enqueue')
        self.assertEqual([m['material_id'] for m in result['youtube_handoff']['missing']],[fixtures.MID])

    def test_current_completion_check_reports_missing_enqueue_without_reimport(self):
        self.returned()
        result=fireplay_submission.verify_completion(fixtures.CODE, {'serverTime':utc_now(),
            'items':[{'id':fixtures.RID,'materials':[{'id':fixtures.MID},{'id':fixtures.RESOURCE}]}]},self.root)
        self.assertFalse(result['complete'])
        self.assertEqual({row['reason'] for row in result['missing']},{'youtube_enqueue_not_evidenced'})

    def test_saved_handoff_copies_receipt_content_without_live_path_dependency(self):
        box,_=self.returned()
        material=self.root/'work/actual-material.json';task=self.root/'work/actual-task.json'
        write_json(material,self.material());write_json(task,self.task())
        handoff.record_receipt(fixtures.CODE,{'material_receipt':str(material),'task_receipt':str(task),
            'video_sha256':box['packages'][0]['sha256']},self.root)
        material.unlink();task.unlink()
        rows=handoff.coverage(self.record(),self.record()['videos'][0],self.root)['missing']
        self.assertEqual([r['material_id'] for r in rows],[fixtures.RESOURCE])


if __name__=='__main__':unittest.main()
