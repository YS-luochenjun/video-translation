import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from video_localizer import compositor,layout,media,workflow
from video_localizer.common import file_hash,write_json
from video_localizer.kie import ApiError, KieClient


class LocaleAudioTests(unittest.TestCase):
    def setUp(self):
        from workspace_fixture import isolate_mock_provider
        isolate_mock_provider(self)
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'work/test-tmp')
        self.run=Path(self.tmp.name)
        for folder in ['inputs','analysis','outputs']:(self.run/folder).mkdir()
        source=self.run/'inputs/source.mp4';source.write_bytes(b'synthetic source binding')
        write_json(self.run/'run.json',{'source':'inputs/source.mp4','source_sha256':file_hash(source)})
        write_json(self.run/'inputs/request.json',{'target_language':'ja-JP'})
        (self.run/'analysis/audio.wav').write_bytes(b'synthetic source audio')
        candidate=self.run/'outputs/candidate.mp4';candidate.write_bytes(b'synthetic Japanese candidate')
        self.digest=file_hash(candidate)
        write_json(self.run/'outputs/candidate.json',{'path':'outputs/candidate.mp4','sha256':self.digest,'plan_id':'fixture'})
        audio=self.run/'review'/self.digest[:12]/'audio.wav';audio.parent.mkdir(parents=True);audio.write_bytes(b'synthetic candidate audio')
        self.calls=[]
        outer=self
        class Client:
            def upload(self,path):return 'https://example.org/'+path.parent.name+'.wav'
            def analyze_audio(self,urls,prompt,model=None):
                outer.calls.append((urls,prompt))
                return {'id':'synthetic-receipt','credits_consumed':0.1,'choices':[{'message':{'content':json.dumps({'has_speech':True,'speech_segments':[]})}}]}
        self.client=Client()

    def tearDown(self):self.tmp.cleanup()

    def test_character_voice_review_uses_real_comparison_and_rejects_inconsistent_assignments(self):
        inventory={'speech_segments':[
            {'character_id':'heroine','voice_name':'Kore','start':0,'end':1},
            {'character_id':'doctor','voice_name':'Charon','start':1,'end':2},
            {'character_id':'heroine','voice_name':'Kore','start':2,'end':3}]}
        write_json(self.run/'analysis/inventory.json',inventory)
        result=self.inspect(voice_review=True)
        self.assertEqual(result['state'],'success')
        urls,prompt=self.calls[-1]
        self.assertEqual(len(urls),2)
        self.assertIn('ACTUALLY audible',prompt)
        self.assertIn('character_voices',prompt)
        self.assertIn('heroine',prompt)
        inventory['speech_segments'][-1]['voice_name']='Puck'
        write_json(self.run/'analysis/inventory.json',inventory)
        with self.assertRaisesRegex(Exception,'conflicting assigned voices'):
            self.inspect(voice_review=True)
        self.assertEqual(len(self.calls),1)

    def inspect(self,**kwargs):
        with patch.object(workflow.media,'probe',return_value={'has_audio':True}),patch.object(workflow,'current_plan',return_value={'id':'fixture'}):
            return workflow.analyze_audio(self.run,self.client,candidate=True,**kwargs)

    def test_japanese_comparison_does_not_request_chinese_translation(self):
        self.inspect()
        self.assertEqual(len(self.calls[0][0]),2)
        self.assertIn('translation of A into ja-JP',self.calls[0][1])
        self.assertNotIn('Chinese translation',self.calls[0][1])
        self.assertIn('Sung samples belonging to the background music',self.calls[0][1])

    def test_candidate_transcription_sends_only_actual_candidate(self):
        result=self.inspect(transcribe_only=True)
        self.assertEqual(len(self.calls[0][0]),1)
        self.assertIn('Do not translate while transcribing',self.calls[0][1])
        self.assertIn('no source comparison',self.calls[0][1])
        self.assertTrue(result['analysis'].endswith('audio-candidate-transcript.json'))

    def test_upload_retry_preserves_failure_and_does_not_repeat_paid_post(self):
        original = self.client.upload
        self.client.upload = lambda path: (_ for _ in ()).throw(ApiError('KIE transport/response failure (URLError); inspect provider log before resubmitting', ambiguous=True))
        with self.assertRaises(ApiError):
            self.inspect(transcribe_only=True)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.inspect(transcribe_only=True)['state'], 'failed')
        self.client.upload = original
        with patch('video_localizer.budgets.resume_undispatched') as resume:
            result = self.inspect(transcribe_only=True, retry_upload=True)
        resume.assert_called_once_with(self.run, result['job'])
        self.assertEqual(result['state'], 'success')
        self.assertEqual(len(self.calls), 1)
        journal = json.loads((self.run / 'jobs' / (result['job'] + '.json')).read_text())
        snapshot = self.run / journal['upload_retry_history'][0]['path']
        self.assertEqual(json.loads(snapshot.read_text())['failure_stage'], 'upload')
        with self.assertRaisesRegex(Exception, 'reconcile ambiguous'):
            self.inspect(transcribe_only=True, retry_upload=True)
        self.assertEqual(len(self.calls), 1)

    def test_upload_retry_rejects_ambiguous_paid_model_request(self):
        self.client.analyze_audio = lambda *args, **kwargs: (_ for _ in ()).throw(ApiError('KIE code 503: Service Unavailable', ambiguous=True))
        with self.assertRaises(ApiError):
            self.inspect(transcribe_only=True)
        with self.assertRaisesRegex(Exception, 'reconcile ambiguous'):
            self.inspect(transcribe_only=True, retry_upload=True)

    def test_audio_request_has_a_specific_supported_model_and_longer_timeout(self):
        client=KieClient(key='synthetic-test-key')
        with patch.object(client,'_request',return_value={'choices':[{}]}) as request:
            client.analyze_audio('https://example.org/audio.wav','Synthetic inspection',model='gemini-3-8-flash-openai')
        self.assertTrue(request.call_args.args[0].endswith('/gemini-3-8-flash-openai/v1/chat/completions'))
        self.assertEqual(request.call_args.kwargs['timeout'],180)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg required')
class TextOcclusionTests(unittest.TestCase):
    def test_foreground_card_keeps_pixels_while_translated_text_remains_visible(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'work/test-tmp') as temporary:
            root=Path(temporary);source=root/'source.mp4'
            media.ffmpeg(['-f','lavfi','-i','color=green:s=160x96:r=30:d=0.4','-vf','drawbox=x=65:y=15:w=30:h=60:color=white:t=fill','-c:v','libx264','-pix_fmt','yuv420p',source])
            item={'action':'model_edit','source_text':'source','target_text':'WWWWWW','start':0,'end':.4,'bbox':[5,15,150,60],
                  'display':{'font_family':'Arial','font_size':60,'color':'#FF0000','outline':0,'bold':True},
                  'trajectory':[{'time':0,'bbox':[5,15,150,60],'occluded_by':[65,15,30,60]}]}
            result=compositor.text(source,{'start':0,'end':.4},[item],{'width':160,'height':96},root/'render')
            def pixels(p):
                return subprocess.run(['ffmpeg','-v','error','-i',str(p),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],capture_output=True,check=True).stdout
            before,after=pixels(source),pixels(result)
            for y in range(22,68):
                for x in range(71,89):
                    index=(y*160+x)*3
                    self.assertLess(max(abs(before[index+c]-after[index+c]) for c in range(3)),12)
            red=sum(after[i]>150 and after[i]>after[i+1]+60 for i in range(0,len(after),3))
            self.assertGreater(red,100)


if __name__=='__main__':unittest.main()
