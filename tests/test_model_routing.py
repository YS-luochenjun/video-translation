import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from video_localizer import model_tasks
from video_localizer.common import WorkflowError, file_hash, object_hash, read_json, write_json
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
                      'bytedance/seedance-2-fast', 'elevenlabs/text-to-speech-turbo-2-5',
                      'google/gemini-2-5-pro-tts',
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
                voice_flags = ['one=EXAVITQu4vr4xnSDxMaL', 'two=21m00Tcm4TlvDq8ikWAM']
                result = prepare_tts_fallback(run, packet_path, job_id, elevenlabs_voices=voice_flags)
                self.assertEqual(result['model'], model_tasks.ELEVENLABS_V3)
                self.assertEqual(result['request_budget'], budget['id'])
                self.assertEqual(read_json(failure_path), failure)
                self.assertEqual(result, prepare_tts_fallback(run, packet_path, job_id, elevenlabs_voices=voice_flags))
                for record, (key, text), assignment in zip(result['packets'], speech, voice_flags):
                    self.assertEqual(record['speech_id'], key)
                    inputs = read_json(run / record['packet'])['payload']['input']
                    self.assertEqual(inputs['dialogue'], [{'voice': assignment.split('=')[1], 'text': text}])
                    self.assertEqual(inputs['language_code'], 'de')
                for update in ({'credits_consumed': None}, {'credits_consumed': 1}, {'state': 'generating'}):
                    with self.subTest(**update):
                        write_json(failure_path, {**failure, **update})
                        with self.assertRaisesRegex(WorkflowError, 'terminal zero-credit'):
                            prepare_tts_fallback(run, packet_path, job_id)

                write_json(failure_path, {**failure, 'model': 'google/gemini-2-5-pro-tts'})
                options = {'elevenlabs_voices': voice_flags, 'combine': True}
                short = prepare_tts_fallback(run, packet_path, job_id, **options)
                self.assertEqual(short['model'], model_tasks.ELEVENLABS_V3)
                self.assertLess(short['packets'][0]['estimated_credits'], 6)
                self.assertEqual(short['packets'][0]['speech_ids'], ['one', 'two'])

                dialogue_failure = {**failure, 'model': model_tasks.ELEVENLABS_V3}
                write_json(failure_path, dialogue_failure)
                write_json(run / 'inputs/request.json', {'target_language': 'vi'})
                with self.assertRaisesRegex(WorkflowError, 'No compatible next TTS route'):
                    prepare_tts_fallback(run, packet_path, job_id, **options)
                write_json(run / 'inputs/request.json', {'target_language': 'zh-TW'})
                with self.assertRaisesRegex(WorkflowError, 'one voice per task'):
                    prepare_tts_fallback(run, packet_path, job_id, **options)
                voice_flags[1] = 'two=EXAVITQu4vr4xnSDxMaL'
                long_text = '這是經過確認的繁體中文配音稿。' * 35
                inventory_path = run / 'analysis/inventory.json'
                inventory = read_json(inventory_path)
                inventory['speech_segments'][0]['target_text'] = long_text
                write_json(inventory_path, inventory)
                source_packet = read_json(run / packet_path)
                source_packet['payload']['input']['dialogue_turns'][0]['text'] = long_text
                write_json(run / packet_path, source_packet)
                combined = prepare_tts_fallback(run, packet_path, job_id, **options)
                self.assertEqual(combined['model'], model_tasks.ELEVENLABS_V2)
                prepared = read_json(run / combined['packets'][0]['packet'])
                self.assertEqual(prepared['estimated_credits'], 12)
                self.assertEqual(prepared['payload']['input']['language_code'], 'zh')
                self.assertEqual(prepared['payload']['input']['text'], long_text + ' Hallo!')
                write_json(run / 'jobs' / ('b' * 64 + '.json'),
                           {**dialogue_failure, 'state': 'ambiguous', 'task_id': None, 'credits_consumed': None})
                with self.assertRaisesRegex(WorkflowError, 'Reconcile outstanding'):
                    prepare_tts_fallback(run, packet_path, job_id, **options)
                unknown_packet = {**source_packet, 'speech_ids': ['one']}
                write_json(run / 'inputs/unknown.json', unknown_packet)
                write_json(run / 'jobs' / ('b' * 64 + '.json'),
                           {**dialogue_failure, 'state': 'ambiguous', 'task_id': None, 'credits_consumed': None,
                            'packet': 'inputs/unknown.json', 'packet_sha256': object_hash(unknown_packet)})
                other_line = prepare_tts_fallback(run, packet_path, job_id, speech_ids=['two'],
                                                  elevenlabs_voices=voice_flags[1:])
                self.assertEqual(other_line['packets'][0]['speech_id'], 'two')
                with self.assertRaisesRegex(WorkflowError, 'Reconcile outstanding'):
                    prepare_tts_fallback(run, packet_path, job_id, **options)
                unknown_job_id = 'b' * 64
                unknown_job_path = run / 'jobs' / f'{unknown_job_id}.json'
                undispatched = {**read_json(unknown_job_path), 'id': unknown_job_id,
                                'error': 'Local audio task failure; inspect journal before retry'}
                write_json(unknown_job_path, undispatched)
                reservation = {'run': run.name, 'job': unknown_job_id, 'created_at': '2026-11-25T04:00:00Z'}
                budget['reservations'] = {unknown_job_id: reservation}
                self.assertEqual(prepare_tts_fallback(run, packet_path, job_id, **options)['packets'][0]['speech_ids'],
                                 ['one', 'two'])
                self.assertEqual(read_json(unknown_job_path), undispatched)
                reservation['dispatch'] = {'endpoint': '/api/v1/jobs/createTask'}
                with self.assertRaisesRegex(WorkflowError, 'Reconcile outstanding'):
                    prepare_tts_fallback(run, packet_path, job_id, **options)

                write_json(failure_path, failure)
                write_json(run / 'inputs/request.json', {'target_language': 'de'})
                rejected_record = result['packets'][0]
                rejected_packet = read_json(run / rejected_record['packet'])
                rejected_voice = rejected_packet['payload']['input']['dialogue'][0]['voice']
                rejection = {**undispatched, 'state': 'failed', 'packet': rejected_record['packet'],
                             'packet_sha256': object_hash(rejected_packet),
                             'error': f'KIE code 422: Invalid voice parameter: {rejected_voice}. '
                                      'Please refer to the documentation for the list of supported voices.'}
                write_json(unknown_job_path, rejection)
                reservation['dispatch']['request_sha256'] = object_hash(rejected_packet['payload'])
                with self.assertRaisesRegex(WorkflowError, 'Reconcile outstanding'):
                    prepare_tts_fallback(run, packet_path, job_id, **options)
                corrected = {**options, 'elevenlabs_voices': ['one=cgSgspJ2msm6clMCkdW9', voice_flags[1]]}
                self.assertEqual(prepare_tts_fallback(run, packet_path, job_id, **corrected)['model'],
                                 model_tasks.ELEVENLABS_V3)
                self.assertIsNone(read_json(unknown_job_path)['credits_consumed'])
                reservation['dispatch']['request_sha256'] = 'unverified'
                with self.assertRaisesRegex(WorkflowError, 'Reconcile outstanding'):
                    prepare_tts_fallback(run, packet_path, job_id, **corrected)

                rejection = {**rejection, 'error': 'KIE code 422: invalid decr count'}
                write_json(unknown_job_path, rejection)
                reservation['dispatch']['request_sha256'] = object_hash(rejected_packet['payload'])
                next_model = prepare_tts_fallback(
                    run, packet_path, unknown_job_id, speech_ids=['one'], elevenlabs_voices=voice_flags[:1])
                self.assertEqual(next_model['model'], model_tasks.ELEVENLABS_V2)
                self.assertIsNone(next_model['failed_task_id'])
                self.assertEqual(read_json(unknown_job_path), rejection)
                self.assertEqual(budget['reservations'][unknown_job_id], reservation)
                with self.assertRaisesRegex(WorkflowError, 'Reconcile outstanding'):
                    prepare_tts_fallback(run, packet_path, job_id, **options)
                reservation['dispatch']['request_sha256'] = 'unverified'
                with self.assertRaisesRegex(WorkflowError, 'Explicit rejection must match'):
                    prepare_tts_fallback(
                        run, packet_path, unknown_job_id, speech_ids=['one'], elevenlabs_voices=voice_flags[:1])
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
