import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_localizer.common import WorkflowError, file_hash, write_json
from video_localizer.kie import KieClient
from video_localizer.model_routing import require_audio_analysis_model


class AuthorizedAudioReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'work/test-tmp')
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name) / 'runs/fixture'
        (self.run / 'inputs').mkdir(parents=True)
        write_json(self.run / 'run.json', {'source_sha256': 'a' * 64})
        write_json(self.run / 'inputs/request.json', {'target_language': 'hi'})
        self.grant = {'authority': 'user', 'source': 'fixture-human-message',
                      'quote': 'Change models for this source audio review.',
                      'model': 'gemini-3.1-pro', 'capability': 'audio_analysis',
                      'source_sha256': 'a' * 64, 'target_languages': ['hi'], 'request_budget': 'fixture-budget'}

    def binding(self):
        path = self.run / 'inputs/audio-grant.json'
        write_json(path, self.grant)
        return {'path': 'inputs/audio-grant.json', 'sha256': file_hash(path)}

    def test_alternative_requires_grant_before_any_network(self):
        client = KieClient(key='synthetic-key')
        with patch.object(client, '_request') as request:
            with self.assertRaisesRegex(WorkflowError, 'explicit source/request-bound'):
                client.analyze_audio('https://example.org/actual.wav', 'Actual transcription', 'gemini-3.1-pro')
            request.assert_not_called()

    def test_authorized_route_uses_documented_audio_media_structure(self):
        client = KieClient(key='synthetic-key')
        with patch('video_localizer.budgets.for_source', return_value={'id': 'fixture-budget'}), \
                patch.object(client, '_request', return_value={'choices': [{}]}) as request:
            client.analyze_audio('https://example.org/actual.wav', 'Actual transcription', 'gemini-3.1-pro',
                                 run=self.run, model_authorization=self.binding())
        endpoint, body = request.call_args.args
        self.assertTrue(endpoint.endswith('/gemini-3.1-pro/v1/chat/completions'))
        self.assertEqual(body['messages'][0]['content'][-1]['image_url']['url'], 'https://example.org/actual.wav')

    def test_grant_cannot_cross_source_language_capability_or_budget(self):
        for key, invalid in [('source_sha256', 'b' * 64), ('target_languages', ['vi']),
                             ('capability', 'tts'), ('request_budget', 'other-budget')]:
            with self.subTest(key=key), patch('video_localizer.budgets.for_source', return_value={'id': 'fixture-budget'}):
                original = self.grant[key]
                self.grant[key] = invalid
                with self.assertRaises(WorkflowError):
                    require_audio_analysis_model('gemini-3.1-pro', self.run, self.binding())
                self.grant[key] = original

    def test_grant_tampering_is_rejected(self):
        binding = self.binding()
        self.grant['quote'] = 'changed'
        self.binding()
        with self.assertRaisesRegex(WorkflowError, 'authorization changed'):
            require_audio_analysis_model('gemini-3.1-pro', self.run, binding)
