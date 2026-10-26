import tempfile
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from video_localizer import model_routing, model_tasks
from video_localizer.common import WorkflowError, file_hash, write_json
from video_localizer.kie import KieClient


class AuthorizedElevenTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name) / 'runs/example'
        (self.run / 'inputs').mkdir(parents=True)
        (self.run / 'inputs/source.mp4').write_bytes(b'fixture')
        self.sha = file_hash(self.run / 'inputs/source.mp4')
        write_json(self.run / 'run.json', {'source': 'inputs/source.mp4', 'source_sha256': self.sha})
        write_json(self.run / 'inputs/request.json', {'target_language': 'es'})
        write_json(self.run / 'analysis/inventory.json', {'audio': {'has_speech': True}, 'text_instances': [],
            'speech_segments': [{'id': 'a001', 'target_text': 'Hola.', 'caption_policy': 'none',
                                 'caption_ids': [], 'caption_reason': 'Synthetic fixture'}]})
        self.grant = {'authority': 'user', 'source': 'Explicit fixture human message', 'quote': 'Use V3',
            'model': 'elevenlabs/text-to-dialogue-v3', 'source_sha256': self.sha,
            'request_budget': 'fixture-budget', 'target_languages': ['es']}
        write_json(self.run / 'inputs/grant.json', self.grant)
        self.authorization = {'path': 'inputs/grant.json', 'sha256': file_hash(self.run / 'inputs/grant.json')}
        self.payload = {'model': 'elevenlabs/text-to-dialogue-v3', 'input': {'dialogue': [
            {'text': 'Hola.', 'voice': '5l5f8iK3YPeGga21rQIX'}], 'stability': .5}}

    def policy(self, authorization=None):
        model_routing.require_remote_task(self.payload['model'], run=self.run,
                                         authorization=authorization or self.authorization)

    def test_no_implicit_model_fallback_or_network(self):
        client = KieClient(key='fixture')
        with patch.object(client, '_request') as network:
            with self.assertRaises(WorkflowError): client.create(self.payload)
            network.assert_not_called()

    def test_explicit_matching_grant_is_accepted_and_changed_scope_is_rejected(self):
        with patch('video_localizer.budgets.for_source', return_value={'id': 'fixture-budget'}):
            self.policy()
            self.grant['target_languages'] = ['ja']
            write_json(self.run / 'inputs/grant.json', self.grant)
            changed = {'path': 'inputs/grant.json', 'sha256': file_hash(self.run / 'inputs/grant.json')}
            with self.assertRaisesRegex(WorkflowError, 'language'): self.policy(changed)
        with self.assertRaisesRegex(WorkflowError, 'authorization changed'): self.policy()

    def test_budget_mismatch_is_rejected(self):
        with patch('video_localizer.budgets.for_source', return_value={'id': 'another-budget'}):
            with self.assertRaisesRegex(WorkflowError, 'request budget'): self.policy()

    def test_packet_checks_exact_script_and_price_reservation(self):
        data = {'source_sha256': self.sha, 'purpose': 'Explicit single role fixture', 'estimated_credits': .1,
                'speech_ids': ['a001'], 'model_authorization': self.authorization, 'payload': self.payload}
        def packet():
            write_json(self.run / 'inputs/task.json', data)
            return model_tasks.packet(self.run, 'inputs/task.json')
        with patch('video_localizer.budgets.for_source', return_value={'id': 'fixture-budget'}):
            packet()
            data['payload']['input']['dialogue'][0]['text'] = 'Changed words.'
            data['estimated_credits'] = 1
            with self.assertRaisesRegex(WorkflowError, 'differs from final'): packet()
            data['payload']['input']['dialogue'][0]['text'] = 'Hola.'
            data['estimated_credits'] = .01
            with self.assertRaisesRegex(WorkflowError, 'character price'): packet()

    def test_flash_alternative_requires_exact_model_grant_and_script(self):
        self.grant['model'] = 'google/gemini-3-1-flash-tts'
        write_json(self.run / 'inputs/grant.json', self.grant)
        grant = {'path': 'inputs/grant.json', 'sha256': file_hash(self.run / 'inputs/grant.json')}
        data = {'source_sha256': self.sha, 'purpose': 'Explicit alternative KIE model fixture',
                'estimated_credits': .5, 'speech_ids': ['a001'], 'model_authorization': grant,
                'payload': {'model': self.grant['model'], 'input': {'speakers': [
                    {'speaker_id': 'Speaker 1', 'voice_name': 'Aoede'}],
                    'dialogue_turns': [{'speaker_id': 'Speaker 1', 'text': 'Hola.'}]}}}
        with patch('video_localizer.budgets.for_source', return_value={'id': 'fixture-budget'}):
            write_json(self.run / 'inputs/task.json', data)
            model_tasks.packet(self.run, 'inputs/task.json')
            data['payload']['input']['dialogue_turns'][0]['text'] = 'Unapproved script.'
            write_json(self.run / 'inputs/task.json', data)
            with self.assertRaisesRegex(WorkflowError, 'differs from final'):
                model_tasks.packet(self.run, 'inputs/task.json')
