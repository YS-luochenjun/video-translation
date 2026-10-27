import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_localizer.audio_retry import authorized_retry
from video_localizer.common import WorkflowError, file_hash, object_hash, read_json, write_json


class ExplicitAudioRetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name)
        self.descriptor = {'kind': 'audio_review', 'model': 'gemini-3-8-flash-openai',
                           'source_sha256': 'source', 'audio_sha256': 'source-audio',
                           'video_sha256': 'video', 'candidate_audio_sha256': 'target-audio',
                           'prompt': 'Compare the actual two audio tracks'}
        self.original_id = object_hash(self.descriptor)
        self.journal = self.run / 'jobs' / (self.original_id + '.json')
        write_json(self.journal, {**self.descriptor, 'id': self.original_id,
                   'state': 'ambiguous', 'failure_stage': 'model_request',
                   'batch_budget': {'request_budget': 'existing-budget'}})
        write_json(self.run / 'inputs/request.json', {'target_language': 'pt'})
        self.grant = {'authority': 'user', 'authorization_ref': 'fixture-human-retry',
                      'source_quote': 'Retry these two requests', 'retry_of': self.original_id,
                      'original_job_sha256': file_hash(self.journal), 'target_language': 'pt',
                      'request_budget': 'existing-budget', 'maximum_additional_attempts': 1,
                      **{k: self.descriptor[k] for k in
                         ('source_sha256', 'video_sha256', 'candidate_audio_sha256', 'model')}}

    def binding(self):
        path = self.run / 'inputs/retry.json'
        write_json(path, self.grant)
        return {'path': 'inputs/retry.json', 'sha256': file_hash(path)}

    def retry(self, binding=None):
        with patch('video_localizer.budgets._index', return_value={
                'runs': {self.run.name: {'scope': 'existing-budget'}}}):
            return authorized_retry(self.run, self.descriptor, binding or self.binding())

    def test_stable_retry_preserves_original_and_rejects_another_grant(self):
        original = self.journal.read_bytes()
        binding = self.binding()
        identity = self.retry(binding)
        self.assertEqual(self.journal.read_bytes(), original)
        retry_id = object_hash({**self.descriptor, **identity})
        write_json(self.run / 'jobs' / (retry_id + '.json'), {'retry_authorization': binding})
        self.assertEqual(self.retry(binding), identity)
        self.grant['authorization_ref'] = 'another-grant'
        with self.assertRaisesRegex(WorkflowError, 'already has'):
            self.retry()

    def test_grant_cannot_change_media_language_budget_or_attempt_limit(self):
        for key in ('source_sha256', 'video_sha256', 'candidate_audio_sha256', 'model',
                    'target_language', 'request_budget', 'maximum_additional_attempts'):
            with self.subTest(key=key):
                old = self.grant[key]
                self.grant[key] = 'different'
                with self.assertRaises(WorkflowError):
                    self.retry()
                self.grant[key] = old

    def test_task_or_response_must_be_recovered_and_tampering_is_rejected(self):
        binding = self.binding()
        self.grant['source_quote'] = 'changed'
        self.binding()
        with self.assertRaisesRegex(WorkflowError, 'authorization changed'):
            self.retry(binding)
        for key in ('task_id', 'response_id', 'response_path', 'result'):
            job = read_json(self.journal)
            job[key] = 'recoverable'
            write_json(self.journal, job)
            self.grant['original_job_sha256'] = file_hash(self.journal)
            with self.assertRaisesRegex(WorkflowError, 'Recover an existing'):
                self.retry()
            job.pop(key)
            write_json(self.journal, job)

    def test_second_attempt_requires_new_user_instruction_and_stops_at_two(self):
        binding = self.binding()
        first_id = object_hash({**self.descriptor, **self.retry(binding)})
        prior = self.run / 'jobs' / (first_id + '.json')
        write_json(prior, {'state': 'ambiguous', 'failure_stage': 'model_request',
                          'retry_authorization': binding})
        old_grant = self.run / 'inputs/first-grant.json'
        old_grant.write_bytes((self.run / binding['path']).read_bytes())
        job = read_json(prior)
        job['retry_authorization'] = {'path': 'inputs/first-grant.json', 'sha256': file_hash(old_grant)}
        write_json(prior, job)
        self.grant.update(retry_attempt=2, previous_retry=first_id,
                          previous_retry_sha256=file_hash(prior))
        with self.assertRaisesRegex(WorkflowError, 'new explicit user'):
            self.retry()
        self.grant['authorization_ref'] = 'new-human-retry'
        self.assertEqual(self.retry()['retry_attempt'], 2)
        self.grant['retry_attempt'] = 3
        with self.assertRaisesRegex(WorkflowError, 'limit reached'):
            self.retry()
