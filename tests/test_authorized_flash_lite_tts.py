import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_localizer.common import WorkflowError, file_hash, write_json
from video_localizer.model_tasks import packet


class AuthorizedFlashLiteTtsTests(unittest.TestCase):
    def test_scoped_authorization_exact_copy_and_provider_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / 'runs/fixture'
            source = run / 'inputs/source.mp4'
            source.parent.mkdir(parents=True)
            source.write_bytes(b'fixture source')
            digest = file_hash(source)
            write_json(run / 'run.json', {'source': 'inputs/source.mp4', 'source_sha256': digest})
            write_json(run / 'inputs/request.json', {'target_language': 'pt'})
            write_json(run / 'analysis/inventory.json', {'text_instances': [], 'speech_segments': [
                {'id': 'a001', 'target_text': 'Olá.', 'caption_policy': 'none',
                 'caption_ids': [], 'caption_reason': 'No corresponding source captions.'}]})
            model = 'google/gemini-3-8-flash-lite-tts'
            grant = {'authority': 'user', 'source': 'current-human-followup', 'quote': 'Change the model.',
                     'model': model, 'source_sha256': digest, 'request_budget': 'budget',
                     'target_languages': ['pt']}
            write_json(run / 'inputs/grant.json', grant)
            data = {'source_sha256': digest, 'purpose': 'Exact role dialogue', 'estimated_credits': .3,
                    'speech_ids': ['a001'], 'model_authorization': {'path': 'inputs/grant.json',
                    'sha256': file_hash(run / 'inputs/grant.json')}, 'payload': {'model': model, 'input': {
                        'speakers': [{'speaker_id': 'Speaker 1', 'voice_name': 'Zephyr'}],
                        'dialogue_turns': [{'speaker_id': 'Speaker 1', 'text': 'Olá.', 'style': 'Warm.'}]}}}
            def validate():
                write_json(run / 'inputs/tts.json', data)
                return packet(run, 'inputs/tts.json')
            with patch('video_localizer.budgets.for_source', return_value={'id': 'budget'}):
                validate()
                data['payload']['input']['filler_words'] = True
                with self.assertRaisesRegex(WorkflowError, 'filler'):
                    validate()
                data['payload']['input'].pop('filler_words')
                data['payload']['input']['dialogue_turns'][0]['text'] = 'Another line'
                with self.assertRaises(WorkflowError):
                    validate()
                data['payload']['input']['dialogue_turns'][0]['text'] = 'Olá.'
                data['model_authorization'] = None
                with self.assertRaises(WorkflowError):
                    validate()
