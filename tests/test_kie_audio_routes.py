import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from video_localizer.common import WorkflowError, file_hash, read_json, write_json
from video_localizer.kie import ApiError, KieClient
from video_localizer import audio_transcription


class AudioRouteTests(unittest.TestCase):
    def test_current_flash_endpoint_keeps_both_actual_media_urls(self):
        client = KieClient(key='fixture-key')
        with patch.object(client, '_request', return_value={'choices': [{}]}) as request:
            client.analyze_audio(['https://example.org/source.wav', 'https://example.org/final.wav'],
                                 'Compare actual recordings; return JSON.', 'gemini-3-8-flash-openai')
        endpoint, body = request.call_args.args
        self.assertTrue(endpoint.endswith('/gemini-3-8-flash-openai/v1/chat/completions'))
        urls = [item['image_url']['url'] for item in body['messages'][0]['content'] if item['type'] == 'image_url']
        self.assertEqual(urls, ['https://example.org/source.wav', 'https://example.org/final.wav'])
        self.assertNotIn('response_format', body)

    def test_unavailable_old_flash_is_rejected_before_network(self):
        client = KieClient(key='fixture-key')
        with patch.object(client, '_request') as request:
            with self.assertRaisesRegex(WorkflowError, 'Unsupported audio analysis endpoint'):
                client.analyze_audio('https://example.org/source.wav', 'inspect', 'gemini-3-flash')
        request.assert_not_called()

    def test_hydrogen_backup_accepts_both_audio_tracks_and_low_reasoning(self):
        client = KieClient(key='fixture-key')
        with patch.object(client, '_request', return_value={'choices': [{}]}) as request:
            client.analyze_audio(['https://example.org/source.wav', 'https://example.org/final.wav'],
                                 'Compare audio', 'gemini-4-hydrogen-openai')
        endpoint, body = request.call_args.args
        self.assertTrue(endpoint.endswith('/gemini-4-hydrogen-openai/v1/chat/completions'))
        self.assertEqual(body['reasoning_effort'], 'low')
        self.assertEqual([item['image_url']['url'] for item in body['messages'][0]['content']
                          if item['type'] == 'image_url'],
                         ['https://example.org/source.wav', 'https://example.org/final.wav'])

    def test_nemotron_transcription_uses_unprompted_word_timestamps(self):
        client = KieClient(key='fixture-key')
        with patch.object(client, '_request', return_value={'taskId': 'fixture-transcript'}) as request:
            self.assertEqual(client.transcribe_audio('https://example.org/final.wav'), 'fixture-transcript')
        endpoint, body = request.call_args.args
        self.assertTrue(endpoint.endswith('/api/v1/jobs/createTask'))
        self.assertEqual(body, {'model': 'nvidia/nemotron-3-5-transcribe',
                               'input': {'audio_url': 'https://example.org/final.wav', 'timestamps': True}})

    def test_transcription_collection_binds_real_receipt_and_transcript(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            job = {'id': 'fixture', 'model': 'nvidia/nemotron-3-5-transcribe',
                   'source_sha256': 'source', 'audio_sha256': 'audio',
                   'audio_path': 'review/audio.wav', 'video_sha256': 'video',
                   'task_id': 'task'}
            status = {'resultJson': json.dumps({'resultObject': {
                'text': 'Hola', 'url': 'https://example.org/transcript.json'}})}
            def save_transcript(url, destination, **kwargs):
                write_json(destination, {'text': 'Hola', 'words': [{'word': 'Hola'}]})
            with patch.object(audio_transcription, 'download', side_effect=save_transcript) as download:
                audio_transcription.collect(run, job, status)
                audio_transcription.collect(run, job, status)
            download.assert_called_once()
            evidence = read_json(run / job['result'])
            self.assertEqual(evidence['video_sha256'], 'video')
            self.assertEqual(evidence['audio_sha256'], 'audio')
            self.assertEqual(evidence['transcript_sha256'], file_hash(run / evidence['transcript']))
            self.assertEqual(job['result_sha256'], file_hash(run / job['result']))

    def test_transcription_retry_only_after_zero_credit_terminal_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            source = run / 'source.mp4'
            track = run / 'analysis/audio.wav'
            track.parent.mkdir()
            source.write_bytes(b'video')
            track.write_bytes(b'audio')
            client = Mock()
            client.upload.return_value = 'https://example.org/audio.wav'
            client.transcribe_audio.return_value = 'fixture-task'
            with patch('video_localizer.workflow.source_path', return_value=source), \
                 patch('video_localizer.workflow.execution_limits', return_value={
                     'max_paid_jobs_per_run': 10, 'max_estimated_credits_per_run': 10}), \
                 patch('video_localizer.batches.reserve', return_value={}), \
                 patch.object(audio_transcription.audio, 'inspect', return_value=({
                     'duration': 10, 'has_track': True}, None)):
                submit = audio_transcription.submit.__wrapped__
                first = submit(run, client=client)
                self.assertTrue(submit(run, client=client)['reused'])
                journal = run / 'jobs' / (first['job'] + '.json')
                original = read_json(journal)
                original.update(state='fail', provider_code='500', credits_consumed=None)
                write_json(journal, original)
                with self.assertRaisesRegex(WorkflowError, 'confirmed zero-credit'):
                    submit(run, client=client, retry_failed=True)
                original['credits_consumed'] = 0
                write_json(journal, original)
                second = submit(run, client=client, retry_failed=True)
                self.assertNotEqual(first['job'], second['job'])
                self.assertTrue(submit(run, client=client, retry_failed=True)['reused'])
                self.assertEqual(client.transcribe_audio.call_count, 2)

    def test_provider_error_preserves_redacted_body_and_marks_524_unknown(self):
        for code, ambiguous in [(524, True), (422, False)]:
            with self.subTest(code=code):
                response = io.BytesIO(json.dumps({'code': code, 'msg': 'failure fixture-key'}).encode())
                client = KieClient(key='fixture-key', opener=Mock(open=Mock(return_value=response)))
                with patch('video_localizer.budgets.authorize_request'):
                    with self.assertRaises(ApiError) as caught:
                        client._request('https://api.kie.ai/gemini-3-pro/v1/chat/completions', {})
                self.assertEqual(caught.exception.ambiguous, ambiguous)
                self.assertEqual(caught.exception.provider_response['code'], code)
                self.assertNotIn('fixture-key', json.dumps(caught.exception.provider_response))

    def test_read_only_status_retries_transient_provider_failures(self):
        first = HTTPError('https://api.kie.ai/api/v1/jobs/recordInfo', 503,
                          'Service Unavailable', {}, io.BytesIO(b'{"msg":"temporary"}'))
        second = io.BytesIO(json.dumps({'code': 200, 'data': {'state': 'success'}}).encode())
        client = KieClient(key='fixture-key', opener=Mock(open=Mock(side_effect=[first, second])))
        with patch('video_localizer.budgets.authorize_request'), patch('video_localizer.kie.time.sleep') as sleep:
            result = client._request('https://api.kie.ai/api/v1/jobs/recordInfo?taskId=test')
        self.assertEqual(result, {'state': 'success'})
        self.assertEqual(sleep.call_count, 1)

    def test_paid_post_timeout_stays_unknown_and_never_retries(self):
        timeout = HTTPError('https://api.kie.ai/api/v1/jobs/createTask', 408,
                            'timeout with fixture-key', {}, io.BytesIO(b'{}'))
        client = KieClient(key='fixture-key', opener=Mock(open=Mock(side_effect=timeout)))
        with patch('video_localizer.budgets.authorize_request'), self.assertRaises(ApiError) as caught:
            client._request('https://api.kie.ai/api/v1/jobs/createTask', {'model': 'example'})
        self.assertTrue(caught.exception.ambiguous)
        self.assertNotIn('fixture-key', str(caught.exception))
        client.opener.open.assert_called_once()
