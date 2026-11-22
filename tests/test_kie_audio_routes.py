import io
import json
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from video_localizer.common import WorkflowError
from video_localizer.kie import ApiError, KieClient


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
