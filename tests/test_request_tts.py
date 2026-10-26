import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_localizer.common import WorkflowError, file_hash, write_json
from video_localizer.request_tts import MODEL, validate


class RequestTtsTests(unittest.TestCase):
    def test_request_authorization_and_exact_script_are_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / 'runs/fixture'
            source = run / 'inputs/source.mp4'
            source.parent.mkdir(parents=True)
            source.write_bytes(b'source')
            sha = file_hash(source)
            write_json(run / 'run.json', {'source': 'inputs/source.mp4', 'source_sha256': sha})
            write_json(run / 'inputs/request.json', {'target_language': 'zh-TW'})
            write_json(run / 'analysis/inventory.json', {'speech_segments': [
                {'id': 'a001', 'target_text': 'hello', 'character_id': 'one',
                 'caption_policy': 'none', 'caption_ids': [], 'caption_reason': 'No source caption'}]})
            grant = run / 'inputs/grant.json'
            authorization = {'authority': 'user', 'source': 'test fixture human consent',
                              'quote': 'Send this script to Microsoft online speech.', 'model': MODEL,
                              'external_destination_consent': True,
                              'destination': 'Microsoft online speech',
                              'source_sha256': sha, 'target_languages': ['zh-TW'], 'request_budget': 'budget'}
            write_json(grant, authorization)
            voices = run / 'inputs/voices.json'
            write_json(voices, [{'ShortName': 'fixture-female'}])
            spec = {'source_sha256': sha,
                    'model_authorization': {'path': 'inputs/grant.json', 'sha256': file_hash(grant)},
                    'voice_inventory': {'path': 'inputs/voices.json', 'sha256': file_hash(voices)},
                    'lines': [{'id': 'a001', 'target_text': 'hello', 'voice': 'fixture-female'}]}
            write_json(run / 'inputs/spec.json', spec)
            with patch('video_localizer.budgets.for_source', return_value={'id': 'budget'}):
                self.assertEqual(validate(run, 'inputs/spec.json'), spec)
                authorization['external_destination_consent'] = False
                write_json(grant, authorization)
                spec['model_authorization']['sha256'] = file_hash(grant)
                write_json(run / 'inputs/spec.json', spec)
                with self.assertRaisesRegex(WorkflowError, 'Explicit consent'):
                    validate(run, 'inputs/spec.json')
                authorization['external_destination_consent'] = True
                write_json(grant, authorization)
                spec['model_authorization']['sha256'] = file_hash(grant)
                spec['lines'][0]['target_text'] = 'invented copy'
                write_json(run / 'inputs/spec.json', spec)
                with self.assertRaises(WorkflowError):
                    validate(run, 'inputs/spec.json')
