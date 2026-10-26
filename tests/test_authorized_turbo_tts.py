import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_localizer.common import WorkflowError, file_hash, write_json
from video_localizer.model_tasks import packet


class AuthorizedTurboTtsTests(unittest.TestCase):
    def test_exact_copy_language_and_character_reservation_are_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / 'runs' / 'fixture'
            source = run / 'inputs/source.mp4'
            source.parent.mkdir(parents=True)
            source.write_bytes(b'source fixture')
            digest = file_hash(source)
            write_json(run / 'run.json', {'source': 'inputs/source.mp4', 'source_sha256': digest})
            write_json(run / 'inputs/request.json', {'target_language': 'pt'})
            write_json(run / 'analysis/inventory.json', {
                'text_instances': [], 'speech_segments': [{'id': 'a001', 'target_text': 'Olá.',
                    'caption_policy': 'none', 'caption_ids': [], 'caption_reason': 'No source caption.'}]})
            model = 'elevenlabs/text-to-speech-turbo-2-5'
            grant = {'authority': 'user', 'source': 'human-followup', 'quote': 'Change the failed TTS model.',
                     'model': model, 'source_sha256': digest, 'request_budget': 'budget', 'target_languages': ['pt']}
            write_json(run / 'inputs/grant.json', grant)
            data = {'source_sha256': digest, 'purpose': 'Exact finalized phrase', 'estimated_credits': .1,
                    'model_authorization': {'path': 'inputs/grant.json', 'sha256': file_hash(run / 'inputs/grant.json')},
                    'speech_ids': ['a001'], 'payload': {'model': model, 'input': {
                        'text': 'Olá.', 'voice': 'fixture-voice', 'language_code': 'pt', 'speed': 1.1}}}
            write_json(run / 'inputs/tts.json', data)
            with patch('video_localizer.budgets.for_source', return_value={'id': 'budget'}):
                self.assertEqual(packet(run, 'inputs/tts.json')['speech_ids'], ['a001'])
                data['payload']['input']['language_code'] = 'fr'
                write_json(run / 'inputs/tts.json', data)
                with self.assertRaisesRegex(WorkflowError, 'language must match'):
                    packet(run, 'inputs/tts.json')
                data['payload']['input']['language_code'] = 'pt'
                data['estimated_credits'] = .01
                write_json(run / 'inputs/tts.json', data)
                with self.assertRaisesRegex(WorkflowError, 'character price'):
                    packet(run, 'inputs/tts.json')
