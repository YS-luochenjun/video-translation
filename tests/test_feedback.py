import copy
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from video_localizer import model_tasks as audio_tasks, media, compositor, workflow, cost, prepared, knowledge
from video_localizer.common import WorkflowError, file_hash, object_hash, read_json, write_json
from video_localizer.kie import ApiError

PROJECT = Path(__file__).resolve().parents[1]
TEMP = PROJECT / 'work/test-tmp'
TEMP.mkdir(parents=True, exist_ok=True)


class AudioTaskTests(unittest.TestCase):
    def setUp(self):
        from workspace_fixture import isolate_mock_provider
        isolate_mock_provider(self)
        self.temp = tempfile.TemporaryDirectory(dir=TEMP)
        self.run = Path(self.temp.name)
        source = self.run / 'inputs/source.mp4'
        source.parent.mkdir()
        source.write_bytes(b'bound source for journal tests')
        write_json(self.run / 'run.json', {'source': 'inputs/source.mp4', 'source_sha256': file_hash(source)})
        write_json(self.run / 'analysis/inventory.json', {'speech_segments': [{'id': 'a001', 'target_text': '你好'}]})
        self.data = {'source_sha256': file_hash(source), 'purpose': 'Chinese narration trial', 'estimated_credits': 5, 'speech_ids': ['a001'],
                     'payload': {'model': 'google/gemini-2-5-pro-tts', 'input': {'speakers': [{'speaker_id': 'Speaker 1', 'voice_name': 'Kore'}], 'dialogue_turns': [{'speaker_id': 'Speaker 1', 'text': '你好'}]}}}
        write_json(self.run / 'inputs/tts.json', self.data)
        self.calls = []
        outer = self
        class Client:
            def credits(self): return 1000
            def create(self, payload):
                outer.calls.append(payload)
                return 'fixture-task'
        self.client = Client()

    def tearDown(self): self.temp.cleanup()

    def test_repeating_packet_reuses_task(self):
        first = audio_tasks.submit(self.run, 'inputs/tts.json', self.client)
        second = audio_tasks.submit(self.run, 'inputs/tts.json', self.client)
        self.assertEqual(first['job'], second['job'])
        self.assertTrue(second['reused'])
        self.assertEqual(len(self.calls), 1)

    def test_ambiguous_post_cannot_be_resubmitted(self):
        self.client.create = lambda payload: (_ for _ in ()).throw(ApiError('timeout', ambiguous=True))
        with self.assertRaises(ApiError): audio_tasks.submit(self.run, 'inputs/tts.json', self.client)
        self.assertEqual(audio_tasks.submit(self.run, 'inputs/tts.json', self.client)['state'], 'ambiguous')

    def test_video_jobs_consume_the_same_budget(self):
        write_json(self.run / 'jobs/existing1.json', {'state': 'success', 'credits_consumed': 1})
        write_json(self.run / 'jobs/existing2.json', {'state': 'ambiguous', 'estimated_credits': 2})
        with self.assertRaisesRegex(WorkflowError, 'budget'): audio_tasks.submit(self.run, 'inputs/tts.json', self.client)

    def test_changed_source_rejected_before_create(self):
        (self.run / 'inputs/source.mp4').write_bytes(b'changed')
        with self.assertRaisesRegex(WorkflowError, 'Source changed'): audio_tasks.submit(self.run, 'inputs/tts.json', self.client)
        self.assertFalse(self.calls)

    def test_user_cost_guard_blocks_new_seedance_and_expensive_trials(self):
        write_json(self.run/'config/model-policy.json',{'block_seedance_major_at_least':2,'max_new_video_task_estimated_credits':40})
        for model in ('bytedance/seedance-2-fast','bytedance/seedance-2.5','bytedance/seedance-3'):
            with self.assertRaisesRegex(WorkflowError,'blocked'):cost.check_new_video_task(model,10,self.run)
        with self.assertRaisesRegex(WorkflowError,'exceeds'):cost.check_new_video_task('wan/2-7-videoedit',160,self.run)
        with self.assertRaises(WorkflowError):cost.check_new_video_task('wan/2-6-flash-video-to-video',20,self.run)
        cost.check_new_video_task('wan/2-7-videoedit',32,self.run)

    def test_invalid_audio_reply_still_preserves_raw_receipt(self):
        audio_file=self.run/'analysis/audio.wav'
        audio_file.parent.mkdir(exist_ok=True)
        audio_file.write_bytes(b'synthetic analysis input')
        self.client.upload=lambda path:'https://example.org/audio.wav'
        self.client.analyze_audio=lambda urls,prompt,model=None:{'id':'invalid-reply-receipt','credits_consumed':0.2,'choices':[{'message':{'content':'[]'}}]}
        with patch.object(workflow.media,'probe',return_value={'has_audio':True}):
            with self.assertRaisesRegex(WorkflowError,'Invalid audio analysis'):
                workflow.analyze_audio(self.run,self.client)
        self.assertTrue((self.run/'analysis/audio-analysis-response.json').exists())
        job=read_json(next((self.run/'jobs').glob('*.json')))
        self.assertEqual(job['state'],'response_invalid')
        self.assertEqual(job['response_id'],'invalid-reply-receipt')
        self.assertEqual(job['credits_consumed'],0.2)

    def test_tts_retranslation_is_blocked_before_paid_creation(self):
        changed = copy.deepcopy(self.data)
        changed['payload']['input']['dialogue_turns'][0]['text'] = '您好'
        write_json(self.run / 'inputs/tts.json', changed)
        with self.assertRaisesRegex(WorkflowError, 'TTS copy differs from final speech script'):
            audio_tasks.submit(self.run, 'inputs/tts.json', self.client)
        self.assertFalse(self.calls)
        self.assertFalse(list((self.run / 'jobs').glob('*.json')))

    def test_tts_missing_final_speech_binding_is_blocked_before_creation(self):
        changed = copy.deepcopy(self.data)
        changed.pop('speech_ids')
        write_json(self.run / 'inputs/tts.json', changed)
        with self.assertRaisesRegex(WorkflowError, 'speech_ids'):
            audio_tasks.submit(self.run, 'inputs/tts.json', self.client)
        self.assertFalse(self.calls)

    def test_paid_result_reuse_requires_identical_request_and_assets(self):
        packet={'plan_id':'old','payload':{'model':'video-fixture','input':{'prompt':'Erase'}},
                'assets':{'video':{'path':'source.mp4','sha256':'source-fixture-hash'}}}
        digest=object_hash(packet)
        write_json(self.run/'plans/old/s001/packet.json',packet)
        result=self.run/'outputs/model.mp4';result.parent.mkdir();result.write_bytes(b'paid-result-fixture')
        write_json(self.run/'jobs'/(digest+'.json'),{'id':digest,'plan_id':'old','segment':'s001','packet_sha256':digest,
                    'task_id':'paid-fixture','state':'success','result':'outputs/model.mp4','result_sha256':file_hash(result)})
        new=copy.deepcopy(packet);new['plan_id']='new'
        segment={'id':'s001','reused_model_job':digest}
        with patch.object(workflow,'prepare_packet',return_value=new),patch.object(workflow,'current_plan',return_value={'segments':[segment]}):
            reused=workflow.submit(self.run,'s001',self.client)
        self.assertFalse(reused['new_charge']);self.assertFalse(self.calls)
        new['payload']['input']['prompt']='Different prompt'
        with self.assertRaisesRegex(WorkflowError,'parameters differ'):workflow.reused_model_result(self.run,segment,new)
        new['payload']=packet['payload'];new['assets']['video']['sha256']='different-source'
        with self.assertRaisesRegex(WorkflowError,'source assets differ'):workflow.reused_model_result(self.run,segment,new)

    def test_wan_flash_probe_reserves_actual_price_and_cannot_enable_audio(self):
        data={'source_sha256':self.data['source_sha256'],'purpose':'Bounded silent reference proposal','estimated_credits':20,
              'source_interval':[0,5],'assets':{'video':{'path':'inputs/source.mp4','sha256':self.data['source_sha256']}},
              'payload':{'model':'wan/2-6-flash-video-to-video','input':{'prompt':'Remove only specified lettering.','video_urls':['ASSET:video'],
                        'duration':'5','resolution':'720p','audio':False,'multi_shots':False}}}
        path=self.run/'inputs/probe.json';write_json(path,data)
        with patch.object(audio_tasks.media,'probe',return_value={'duration':5}):
            self.assertEqual(audio_tasks.packet(self.run,'inputs/probe.json')['estimated_credits'],20)
        data['payload']['input']['audio']=True;write_json(path,data)
        with self.assertRaisesRegex(WorkflowError,'silent 720p'):audio_tasks.packet(self.run,'inputs/probe.json')
        data['payload']['input']['audio']=False;data['estimated_credits']=10;write_json(path,data)
        with self.assertRaisesRegex(WorkflowError,'price reservation'):audio_tasks.packet(self.run,'inputs/probe.json')

    def test_prepared_master_cannot_reuse_another_source_or_target_lettering(self):
        master=self.run/'outputs/master.mp4';master.parent.mkdir();master.write_bytes(b'neutral visual fixture')
        record={'source_sha256':self.data['source_sha256'],'target_language':None,'contains_target_typography':False,
                'inputs':[{'path':'inputs/source.mp4','sha256':self.data['source_sha256']}],
                'output':{'path':'outputs/master.mp4','sha256':file_hash(master)}}
        path=self.run/'outputs/preparation.json';write_json(path,record)
        asset={'path':'outputs/master.mp4','sha256':file_hash(master),'record':'outputs/preparation.json','record_sha256':file_hash(path)}
        self.assertEqual(prepared.verify(self.run,asset,self.data['source_sha256']),master)
        with self.assertRaisesRegex(WorkflowError,'another source'):prepared.verify(self.run,asset,'different source')
        record['contains_target_typography']=True;write_json(path,record);asset['record_sha256']=file_hash(path)
        with self.assertRaisesRegex(WorkflowError,'typography'):prepared.verify(self.run,asset,self.data['source_sha256'])
        record['contains_target_typography']=False;write_json(path,record);asset['record_sha256']=file_hash(path)
        (self.run/'inputs/source.mp4').write_bytes(b'tampered source')
        with self.assertRaisesRegex(WorkflowError,'input changed'):prepared.verify(self.run,asset,self.data['source_sha256'])

    def test_approved_reference_scope_does_not_leak_to_other_source_or_language(self):
        reference=self.run/'knowledge/local/reference.md';reference.parent.mkdir(parents=True);reference.write_text('bounded approved style',encoding='utf-8')
        scope={'workflow':'video-localization','source_sha256':'same-source','target_language':'zh-CN'}
        write_json(self.run/'config/knowledge.local.json',{'entries':[{'id':'approved','path':'knowledge/local/reference.md','status':'active','scope':scope}]})
        with patch.object(knowledge,'ROOT',self.run):
            self.assertEqual(len(knowledge.retrieve(scope)),1)
            self.assertFalse(knowledge.retrieve({**scope,'source_sha256':'another-source'}))
            self.assertFalse(knowledge.retrieve({**scope,'target_language':'ja-JP'}))


@unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
class LayoutFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.mp4'
        media.ffmpeg(['-f', 'lavfi', '-i', 'color=green:s=320x180:r=30:d=1', '-c:v', 'libx264', self.source])

    def tearDown(self): self.temp.cleanup()

    def test_overlay_cannot_cover_an_observed_info_icon(self):
        item = {'id': 't001', 'action': 'solid_overlay', 'start': 0, 'end': 1, 'bbox': [45, 80, 145, 32],
                'target_text': '2千条评价', 'protected_regions': [[181, 85, 19, 21]]}
        with self.assertRaisesRegex(WorkflowError, 'protected'):
            media.render_local(self.source, {'start': 0, 'end': 1}, [item], media.probe(self.source), self.root / 'overlay')

    def test_source_banner_stays_restored_when_picture_ends_before_edit(self):
        edited = self.root / 'edit.mp4'
        media.ffmpeg(['-f', 'lavfi', '-i', 'color=red:s=320x180:r=30:d=1.1', '-c:v', 'libx264', edited])
        output = media.restore_regions(self.source, edited, {'start': 0, 'end': 1.1}, [[0, 0, 320, 60]], self.root / 'restored')
        value = subprocess.run(['ffmpeg', '-v', 'error', '-ss', '1.033333', '-i', str(output), '-vf', 'crop=2:2:50:20', '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1'], capture_output=True, check=True).stdout
        self.assertEqual(len(value), 12)
        self.assertGreater(value[1], value[0] + 80, 'Source green banner fell through to red model frame')

    def test_regional_model_composite_preserves_pixels_outside_text(self):
        edited=self.root/'regional-edit.mp4'
        media.ffmpeg(['-f','lavfi','-i','color=red:s=320x180:r=30:d=1','-c:v','libx264',edited])
        item={'id':'t001','action':'model_edit','start':0,'end':1,'bbox':[130,60,60,30]}
        output=compositor.regions(self.source,edited,{'start':0,'end':1},[item],media.probe(self.source),self.root/'regional')
        def pixel(x,y):
            return subprocess.run(['ffmpeg','-v','error','-i',str(output),'-vf',f'crop=2:2:{x}:{y}','-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],capture_output=True,check=True).stdout
        outside,inside=pixel(20,20),pixel(150,70)
        self.assertGreater(outside[1],outside[0]+80)
        self.assertGreater(inside[0],inside[1]+150)

    def test_seedance_packet_uses_its_15s_contract_instead_of_wan_limit(self):
        run=self.root/'packet'
        directory=run/'plans/fixture/s001'
        directory.mkdir(parents=True)
        for name in ('source.mp4','source-model-time.mp4'):(directory/name).write_bytes(b'synthetic video asset')
        write_json(run/'analysis/inventory.json',{'audio':{'strategy':'preserve'}})
        segment={'id':'s001','route':'seedance_edit','start':0,'end':23,'model_input_seconds':15,'prompt':'Erase specified text only.'}
        plan={'id':'fixture','segments':[segment],'audio':{'strategy':'preserve'}}
        with patch.object(workflow,'current_plan',return_value=plan),patch.object(media,'probe',return_value={'duration':15,'width':720,'height':1280,'fps':30}):
            packet=workflow.prepare_packet(run,'s001')
        self.assertEqual(packet['payload']['model'],'bytedance/seedance-2-fast')
        self.assertEqual(packet['payload']['input']['duration'],15)
        self.assertEqual(packet['payload']['input']['reference_video_urls'],['ASSET:video'])
        self.assertFalse(packet['payload']['input']['generate_audio'])
