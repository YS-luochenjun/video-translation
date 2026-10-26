import copy
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_localizer import media, production, repair, retention, learning_evidence, visual_storage
from video_localizer.common import WorkflowError, file_hash, read_json, write_json

PROJECT = Path(__file__).resolve().parents[1]


class RepairAndCompactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=PROJECT/'work/test-tmp')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.run = self.root/'runs/fixture'
        self.run.mkdir(parents=True)
        (self.run/'source.mp4').write_bytes(b'source')
        self.sha = file_hash(self.run/'source.mp4')
        write_json(self.run/'run.json', {'source':'source.mp4','source_sha256':self.sha})
        write_json(self.run/'analysis/media.json', {'duration':2,'fps':10})
        write_json(self.run/'analysis/inventory.json', {'shots':[], 'text_instances':[]})

    def test_diagnostic_files_do_not_invalidate_render_but_bound_asset_change_is_rejected(self):
        voice = self.run/'voice.wav';voice.write_bytes(b'voice')
        plan={'source_sha256':self.sha,'audio_assets':[{'path':'voice.wav','sha256':file_hash(voice)}]}
        first=production._fingerprint(self.run,plan)
        write_json(self.run/'analysis/new-final-asr.json',{'diagnostic':'does not change pixels'})
        (self.run/'inputs').mkdir();(self.run/'inputs/debug.png').write_bytes(b'diagnostic')
        self.assertEqual(first,production._fingerprint(self.run,plan))
        changed=copy.deepcopy(plan);changed['target_text']='New actual copy'
        self.assertNotEqual(first,production._fingerprint(self.run,changed))
        voice.write_bytes(b'tampered')
        with self.assertRaisesRegex(WorkflowError,'dependency changed'):
            production._fingerprint(self.run,plan)

    def test_pixel_reuse_survives_removal_of_origin_without_linking_review_state(self):
        from PIL import Image
        image=Image.new('RGB',(48,40),'blue')
        first=self.run/'inputs/visual-audit/one/compare.png'
        store=visual_storage.PageStore(self.root);store.save(image,first);store.commit()
        second=self.run/'review/two/visual-audit/two/compare.png'
        store=visual_storage.PageStore(self.root);store.save(image,second);store.commit()
        self.assertEqual(store.hits,1)
        first.unlink()
        with Image.open(second) as actual:self.assertEqual(image.tobytes(),actual.tobytes())
        self.assertFalse((second.parent/'reviews.json').exists())
        second.write_bytes(b'changed')
        with self.assertRaisesRegex(WorkflowError,'cache changed'):
            visual_storage.PageStore(self.root).save(image,self.run/'third.png')

    def test_render_dependency_distinguishes_workspace_knowledge_from_run_media(self):
        method=self.root/'knowledge/rules/method.md';method.parent.mkdir(parents=True);method.write_text('reviewed method')
        plan={'source_sha256':self.sha,'knowledge':[{'path':'knowledge/rules/method.md','sha256':file_hash(method)}]}
        self.assertTrue(production._fingerprint(self.run,plan))
        method.write_text('changed without new review')
        with self.assertRaisesRegex(WorkflowError,'workspace dependency changed'):
            production._fingerprint(self.run,plan)

    def test_audio_review_receipt_does_not_invalidate_render_but_selected_model_does(self):
        plan = {'id': 'p', 'source_sha256': self.sha,
                'segments': [{'id': 's1', 'route': 'wan_edit'}]}
        result = self.run / 'model.mp4'; result.write_bytes(b'generated video')
        job = {'id': 'selected', 'plan_id': 'p', 'segment': 's1', 'state': 'success',
               'result': 'model.mp4', 'result_sha256': file_hash(result), 'credits_consumed': None}
        write_json(self.run / 'jobs/selected.json', job)
        first = production._fingerprint(self.run, plan)
        write_json(self.run / 'jobs/audio-review.json', {'id': 'review', 'plan_id': 'p',
                   'segment': 'audio-analysis', 'state': 'failed', 'error': 'provider timeout',
                   'estimated_credits': 20, 'credits_consumed': None})
        self.assertEqual(first, production._fingerprint(self.run, plan))
        job.update(credits_consumed=32, last_checked_at='later')
        write_json(self.run / 'jobs/selected.json', job)
        self.assertEqual(first, production._fingerprint(self.run, plan))
        result.write_bytes(b'revised generated video')
        job['result_sha256'] = file_hash(result)
        write_json(self.run / 'jobs/selected.json', job)
        self.assertNotEqual(first, production._fingerprint(self.run, plan))

    def test_preflight_covers_source_entry_and_shot_cut_separately(self):
        write_json(self.run/'analysis/inventory.json', {'shots':[{'id':'s','start':0,'end':1.2}],
            'text_instances':[{'id':'wm','start':.5,'end':1.8,'source_interval':[.3,1.9],
                               'action':'remove_watermark','trajectory':[{'time':.8,'bbox':[0,1,5,6]}]}]})
        result=repair.preflight(self.run)
        events={w['event'] for w in result['windows']}
        self.assertTrue({.3,.5,.8,1.2,1.8,1.9}<=events)
        self.assertFalse(result['automatic_pass'])

    def test_donor_cannot_cross_pose_cut(self):
        recipe={'source_sha256':self.sha,'shots':[{'id':'one','start':0,'end':1}],
            'operations':[{'method':'temporal_frame','shot':'one','start':0,'end':.8,
                           'donor_time':1.1,'reason':'wrong pose','bbox':[0,0,5,5]}]}
        write_json(self.run/'recipe.json',recipe)
        with self.assertRaisesRegex(WorkflowError,'Donor crosses'):
            repair.execute(self.run,'recipe.json',True)

    def test_interrupted_local_repair_requires_dead_owner_and_does_not_retry_models(self):
        path=self.root/'state/repair-trials/fixture.json'
        write_json(path,{'attempts':[{'state':'running','pid':123,'output':'outputs/missing.json'}],'extensions':[]})
        with patch.object(repair,'_alive',return_value=True):
            with self.assertRaisesRegex(WorkflowError,'still running'):
                repair.reconcile(self.run,'Confirmed interrupted local process')
        with patch.object(repair,'_alive',return_value=False):
            result=repair.reconcile(self.run,'Confirmed interrupted local process')
        self.assertEqual(result['attempts'][0]['state'],'interrupted')
        self.assertFalse(result['paid_retry'])

    def test_bounded_learning_keeps_all_explicit_failure_frames(self):
        folder=self.run/'review'/('a'*12)/'visual-audit/one'
        pages=[]
        for n in range(12):
            p=folder/f'compare-{n:06}.png';p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(str(n).encode())
            pages.append({'frame':n,'id':p.name})
        write_json(folder/'text-visual-audit.json',{'binding':{'video_sha256':'a'*64},'instances':[{'id':'t','pages':pages}]})
        write_json(folder/'observations/fail.json',{'checks':{'erasure':{'status':'fail','evidence_pages':['compare-000007.png','compare-000008.png']}}})
        files=learning_evidence.select(self.run,'a'*64)
        names={p.name for p in files}
        self.assertTrue({'compare-000000.png','compare-000006.png','compare-000011.png',
                         'compare-000007.png','compare-000008.png'}<=names)
        self.assertNotIn('compare-000003.png',names)

    def test_prune_requires_matching_preview_and_keeps_current_pictures_and_observations(self):
        inv=read_json(self.run/'analysis/inventory.json')
        inv['shots']=[{'prepared_video':{'sha256':'b'*64}}]
        write_json(self.run/'analysis/inventory.json',inv)
        old=self.run/'inputs/visual-audit/old';current=self.run/'inputs/visual-audit/current'
        for folder,sha in [(old,'a'*64),(current,'b'*64)]:
            write_json(folder/'text-visual-audit.json',{'binding':{'video_sha256':sha},'instances':[]})
            (folder/'compare.png').write_bytes(b'generated')
            write_json(folder/'observations.json',{'decision':'fail' if sha=='a'*64 else 'pass'})
        write_json(self.root/'state/run-retention/fixture.json',{'case':'independent-case','recovery':'recovery','package':None})
        with patch.object(retention,'inspect',return_value={'decision':'ready','blockers':[],'fingerprint':'preserved'}):
            preview=retention.prune(self.run,self.root)
            self.assertEqual(preview['files'],1)
            with self.assertRaisesRegex(WorkflowError,'preview fingerprint'):
                retention.prune(self.run,self.root,True,'wrong')
            retention.prune(self.run,self.root,True,preview['fingerprint'])
        self.assertFalse((old/'compare.png').exists())
        self.assertTrue((old/'observations.json').exists())
        self.assertTrue((current/'compare.png').exists())

    @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg needed')
    def test_recipe_lossless_output_preserves_unmasked_pixels_and_checkpoint(self):
        media.ffmpeg(['-f','lavfi','-i','testsrc2=size=64x48:rate=10:duration=0.6','-c:v','ffv1',self.run/'source.mkv'])
        sha=file_hash(self.run/'source.mkv')
        write_json(self.run/'run.json',{'source':'source.mkv','source_sha256':sha})
        recipe={'source_sha256':sha,'shots':[{'id':'s','start':0,'end':.6}],
            'operations':[{'method':'temporal_frame','shot':'s','start':.1,'end':.5,'donor_time':0,
                           'reason':'clean same-shot donor','bbox':[8,8,24,16],'protected_regions':[[12,12,4,4]]}]}
        write_json(self.run/'recipe.json',recipe)
        result=repair.execute(self.run,'recipe.json')
        self.assertFalse(result['approved_for_reuse'])
        self.assertTrue(repair.execute(self.run,'recipe.json')['reused'])
        import sys
        from video_localizer.runtime import vision_path
        sys.path.insert(0,str(vision_path(PROJECT)))
        import cv2,numpy as np
        a=cv2.VideoCapture(str(self.run/'source.mkv'));b=cv2.VideoCapture(str(self.run/result['output']['path']))
        for n in range(6):
            _,x=a.read();_,y=b.read();mask=np.zeros(x.shape[:2],bool)
            if 1<=n<5:mask[8:25,8:33]=True;mask[12:16,12:16]=False
            self.assertTrue(np.array_equal(x[~mask],y[~mask]))
        a.release();b.release()
        ledger=self.root/'state/repair-trials/fixture.json';value=read_json(ledger)
        value['attempts']*=4;write_json(ledger,value)
        recipe['operations'][0]['bbox']=[9,8,24,16];write_json(self.run/'recipe.json',recipe)
        with self.assertRaisesRegex(WorkflowError,'budget exhausted'):
            repair.execute(self.run,'recipe.json')
