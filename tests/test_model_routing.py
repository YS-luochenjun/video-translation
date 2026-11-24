import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from video_localizer import model_tasks
from video_localizer.common import WorkflowError, file_hash, read_json, write_json
from video_localizer.kie import KieClient
from video_localizer.production import tts_packet
from video_localizer.tts_recovery import prepare_tts_fallback


class ModelRoutingTests(unittest.TestCase):
    def test_new_plan_and_demo_reject_retired_generation_route_at_argument_parsing(self):
        entry = Path(__file__).resolve().parents[1] / 'bin/va.py'
        commands = [
            ['plan', '../retired-entry-probe', '--experiment', 'regenerate'],
            ['demo', '--id', '../retired-entry-probe', '--route', 'regenerate'],
        ]
        for arguments in commands:
            with self.subTest(command=arguments[0]):
                result = subprocess.run([sys.executable, str(entry), *arguments],
                                        capture_output=True, text=True, encoding='utf-8')
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn('invalid choice', result.stderr)

    def test_retired_video_models_are_rejected_before_network(self):
        client = KieClient(key='fixture-key')
        for model in ('veo-3-1', 'wan/2-7-videoedit', 'kling-3.0-omni/transformation', 'wan/2-6-flash-video-to-video',
                      'bytedance/seedance-2-fast', 'elevenlabs/text-to-speech-multilingual-v2',
                      'ai-music-api/separate-vocals'):
            with self.subTest(model=model), patch.object(client, '_request') as request:
                with self.assertRaises(WorkflowError):
                    client.create({'model': model, 'input': {}})
                request.assert_not_called()

    def test_single_video_and_tts_models_are_accepted(self):
        client = KieClient(key='fixture-key')
        for model in ('wan/3-0-video', 'google/gemini-3-8-flash-tts'):
            with patch.object(client, '_request', return_value={'taskId': 'fixture-task'}):
                self.assertEqual(client.create({'model': model, 'input': {}}), 'fixture-task')

    def test_default_tts_packet_separates_flash_style_from_exact_dialogue(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary) / 'runs' / 'flash-tts'
            run.mkdir(parents=True)
            source = run / 'source.mp4'
            source.write_bytes(b'fixture source')
            write_json(run / 'run.json', {'source': source.name, 'source_sha256': file_hash(source)})
            write_json(run / 'inputs/request.json', {'target_language': 'th'})
            text = 'สวัสดีค่ะ'
            write_json(run / 'analysis/inventory.json', {'speech_segments': [
                {'id': 'speech', 'target_text': text, 'caption_policy': 'none',
                 'caption_ids': [], 'caption_reason': 'Fixture has no source captions.'}]})
            result = tts_packet(run, 'Kore', 1)
            payload = read_json(run / result['packet'])['payload']
            self.assertFalse(result['paid_submission'])
            self.assertEqual(payload['model'], 'google/gemini-3-8-flash-tts')
            self.assertEqual(set(payload['input']), {'speakers', 'dialogue_turns'})
            self.assertEqual(payload['input']['speakers'], [{'speaker_id': 'Speaker 1', 'voice_name': 'Kore'}])
            turn = payload['input']['dialogue_turns'][0]
            self.assertEqual(turn['text'], text)
            self.assertIn('dialogue in th', turn['style'])

    def test_audio_default_is_flash_and_pro_does_not_silently_fallback(self):
        client = KieClient(key='fixture-key')
        with patch.object(client, '_request', return_value={'choices': [{}]}) as request:
            client.analyze_audio('https://example.invalid/source.wav', 'inspect')
            self.assertIn('/gemini-3-8-flash-openai/', request.call_args.args[0])
        with patch.object(client, '_request') as request:
            with self.assertRaises(WorkflowError):
                client.analyze_audio('https://example.invalid/source.wav', 'inspect', 'gemini-3-pro')
            request.assert_not_called()

    def test_tts_fallback_preserves_copy_voices_and_budget_after_settled_timeout(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary) / 'runs' / 'fallback'
            run.mkdir(parents=True)
            source = run / 'source.mp4'
            source.write_bytes(b'fixture source')
            source_hash = file_hash(source)
            write_json(run / 'run.json', {'source': source.name, 'source_sha256': source_hash})
            write_json(run / 'inputs/request.json', {'target_language': 'de'})
            speech = [('one', 'Guten Tag.'), ('two', 'Hallo!')]
            write_json(run / 'analysis/inventory.json', {'speech_segments': [
                {'id': key, 'target_text': text, 'caption_policy': 'none',
                 'caption_ids': [], 'caption_reason': 'Fixture has no source captions.'}
                for key, text in speech]})
            packet_path = 'inputs/flash.json'
            write_json(run / packet_path, {
                'purpose': 'Two-character localization', 'source_sha256': source_hash,
                'speech_ids': [key for key, _ in speech], 'estimated_credits': 2,
                'payload': {'model': model_tasks.GEMINI_FLASH_TTS, 'input': {
                    'speakers': [{'speaker_id': 'Speaker 1', 'voice_name': 'Kore'},
                                 {'speaker_id': 'Speaker 2', 'voice_name': 'Aoede'}],
                    'dialogue_turns': [{'speaker_id': f'Speaker {index}', 'text': text}
                                       for index, (_, text) in enumerate(speech, 1)]}}})
            job_id = 'a' * 64
            failure_path = run / 'jobs' / f'{job_id}.json'
            failure = {'id': job_id, 'kind': 'audio_task', 'model': model_tasks.GEMINI_FLASH_TTS,
                       'packet': packet_path, 'source_sha256': source_hash, 'task_id': 'remote-timeout',
                       'provider_code': '524', 'state': 'fail', 'credits_consumed': 0}
            write_json(failure_path, failure)
            budget = {'id': 'original-budget', 'state': 'open'}
            with patch('video_localizer.budgets.for_run', return_value=budget), \
                 patch.object(model_tasks, 'KieClient') as client:
                result = prepare_tts_fallback(run, packet_path, job_id)
                self.assertEqual(result['model'], 'google/gemini-2-5-pro-tts')
                self.assertEqual(result['request_budget'], budget['id'])
                self.assertEqual(read_json(failure_path), failure)
                self.assertEqual(result, prepare_tts_fallback(run, packet_path, job_id))
                for record, (key, text), voice in zip(result['packets'], speech, ('Kore', 'Aoede')):
                    self.assertEqual(record['speech_id'], key)
                    inputs = read_json(run / record['packet'])['payload']['input']
                    self.assertEqual(inputs['speakers'], [{'speaker_id': 'Speaker 1', 'voice_name': voice}])
                    self.assertEqual(inputs['dialogue_turns'], [{'speaker_id': 'Speaker 1', 'text': text}])
                    self.assertIn('scene', inputs)
                for update in ({'credits_consumed': None}, {'credits_consumed': 1}, {'state': 'generating'}):
                    with self.subTest(**update):
                        write_json(failure_path, {**failure, **update})
                        with self.assertRaisesRegex(WorkflowError, 'terminal zero-credit'):
                            prepare_tts_fallback(run, packet_path, job_id)
                client.assert_not_called()

    def test_retired_task_polling_remains_available(self):
        client = KieClient(key='fixture-key')
        with patch.object(client, '_request', return_value={'state': 'success'}) as request:
            client.status('old-task')
            self.assertIn('recordInfo', request.call_args.args[0])

    def test_retired_asr_size_is_blocked_before_download_or_inference(self):
        import tempfile
        from pathlib import Path
        from video_localizer import asr
        with tempfile.TemporaryDirectory() as tmp, patch.object(asr.model_cache, 'ensure') as install:
            with self.assertRaises(WorkflowError):
                asr.transcribe(Path(tmp), size='base', download=True)
            install.assert_not_called()
