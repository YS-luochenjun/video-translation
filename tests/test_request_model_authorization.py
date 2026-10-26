import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_localizer.common import WorkflowError, file_hash, write_json
from video_localizer.kie import KieClient
from video_localizer.model_routing import require_remote_task


MODEL = 'elevenlabs/text-to-dialogue-v3'


class RequestModelAuthorizationTests(unittest.TestCase):
    def test_alternative_is_blocked_without_the_bound_human_authorization(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / 'runs' / 'fixture'
            write_json(run / 'run.json', {'source': 'inputs/source.mp4', 'source_sha256': 'source'})
            with self.assertRaises(WorkflowError):
                require_remote_task(MODEL, run=run)
            client = KieClient(key='fixture-key')
            with patch.object(client, '_request') as request:
                with self.assertRaises(WorkflowError):
                    client.create({'model': MODEL, 'input': {}})
                request.assert_not_called()

    def test_authorization_is_limited_to_one_budget_source_model_and_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / 'runs' / 'fixture'
            source = run / 'inputs/source.mp4'
            source.parent.mkdir(parents=True)
            source.write_bytes(b'actual source fixture')
            digest = file_hash(source)
            write_json(run / 'run.json', {'source': 'inputs/source.mp4', 'source_sha256': digest})
            record = {'id': 'fixture-budget', 'state': 'open', 'sources': [digest]}
            write_json(run / 'inputs/request.json', {'target_language': 'zh-TW'})
            authorization = {'authority': 'user', 'source': 'human-followup',
                             'quote': 'For this video, change the failed speech model.',
                             'request_budget': record['id'], 'source_sha256': digest,
                             'model': MODEL, 'target_languages': ['zh-TW']}
            path = run / 'inputs/model-authorization.json'
            write_json(path, authorization)
            binding = {'path': 'inputs/model-authorization.json', 'sha256': file_hash(path)}
            with patch('video_localizer.budgets.for_source', return_value=record):
                require_remote_task(MODEL, run=run, authorization=binding)
                with self.assertRaises(WorkflowError):
                    require_remote_task('elevenlabs/unknown-model', run=run, authorization=binding)
                authorization['source_sha256'] = 'another source'
                write_json(path, authorization)
                binding['sha256'] = file_hash(path)
                with self.assertRaises(WorkflowError):
                    require_remote_task(MODEL, run=run, authorization=binding)
