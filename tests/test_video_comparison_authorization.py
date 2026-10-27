from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from video_localizer import cost, model_routing, video_tests
from video_localizer.common import WorkflowError, file_hash, write_json


class VideoComparisonAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.run = self.root / 'runs' / 'comparison'
        write_json(self.run / 'run.json', {'source_sha256': 'source'})
        write_json(self.run / 'inputs/request.json', {'target_language': 'es'})
        self.grant = {'authority': 'user', 'quote': 'Compare exactly these three models', 'source': 'actual-human-event',
            'capability': 'video_erasure_comparison', 'run_id': 'comparison', 'source_sha256': 'source',
            'target_languages': ['es'], 'models': list(video_tests.MODELS), 'request_budget': 'budget',
            'max_submissions_per_model': 1, 'max_estimated_credits': 150,
            'estimated_credits_by_model': dict(zip(video_tests.MODELS, [80, 20, 50])),
            'source_interval': [40.3, 45.3], 'clip_sha256': 'clip', 'aspect_ratio': '9:16', 'prompt': 'erase only CHEER'}
        self.save()
        self.binding = {'path': 'inputs/grant.json', 'sha256': file_hash(self.run / 'inputs/grant.json')}
        self.scope = patch('video_localizer.budgets.for_source', return_value={'id': 'budget'})
        self.scope.start(); self.addCleanup(self.scope.stop)

    def save(self):
        write_json(self.run / 'inputs/grant.json', self.grant)

    def test_global_seedance_and_flash_blocks_remain_without_grant(self):
        for model in video_tests.MODELS[1:]:
            with self.subTest(model=model), self.assertRaises(WorkflowError):
                model_routing.require_remote_task(model, run=self.run)
        with self.assertRaises(WorkflowError):
            model_routing.require_remote_task('bytedance/seedance-2-fast', run=self.run, authorization=self.binding)

    def test_exact_alternative_test_models_are_allowed_and_cost_stays_scoped(self):
        for model, estimate in zip(video_tests.MODELS, [80, 20, 50]):
            cost.check_new_video_task(model, estimate, run=self.run, authorization=self.binding)
            if model != video_tests.MODELS[0]:
                model_routing.require_remote_task(model, run=self.run, authorization=self.binding)
        with self.assertRaises(WorkflowError):
            cost.check_new_video_task(video_tests.MODELS[2], 1, run=self.run, authorization=self.binding)

    def test_changed_grant_run_source_budget_and_capability_are_rejected(self):
        model = video_tests.MODELS[2]
        for key, value in [('run_id', 'other'), ('source_sha256', 'other'), ('request_budget', 'other'),
                           ('capability', 'production'), ('models', ['bytedance/seedance-2-fast'])]:
            original = self.grant[key]
            self.grant[key] = value; self.save()
            binding = {**self.binding, 'sha256': file_hash(self.run / 'inputs/grant.json')}
            with self.subTest(key=key), self.assertRaises(WorkflowError):
                video_tests.authorize(model, self.run, binding)
            self.grant[key] = original; self.save()
        self.grant['quote'] = 'edited'; self.save()
        with self.assertRaisesRegex(WorkflowError, 'changed'):
            video_tests.authorize(model, self.run, self.binding)

    def test_unknown_reservations_and_one_submission_per_model_are_retained(self):
        write_json(self.run / 'jobs/first.json', {'model': video_tests.MODELS[0], 'state': 'ambiguous', 'estimated_credits': 80})
        with self.assertRaisesRegex(WorkflowError, 'already consumed'):
            cost.check_new_video_task(video_tests.MODELS[0], 80, run=self.run, authorization=self.binding)
        cost.check_new_video_task(video_tests.MODELS[2], 50, run=self.run, authorization=self.binding)
        write_json(self.run / 'jobs/overbilling.json', {'model': video_tests.MODELS[1], 'state': 'success', 'credits_consumed': 30})
        with self.assertRaisesRegex(WorkflowError, 'credit limit'):
            cost.check_new_video_task(video_tests.MODELS[2], 50, run=self.run, authorization=self.binding)

    def test_common_clip_prompt_and_mini_billing_are_frozen(self):
        model = video_tests.MODELS[2]
        data = {'payload': {'model': model, 'input': {'prompt': self.grant['prompt'],
            'reference_video_urls': ['ASSET:video'], 'generate_audio': False, 'resolution': '720p',
            'aspect_ratio': '9:16', 'duration': 5, 'web_search': False}},
            'model_authorization': self.binding, 'estimated_credits': 50,
            'source_interval': self.grant['source_interval'], 'assets': {'video': {'sha256': 'clip'}}}
        video_tests.check_packet(self.run, data)
        for key, value in [('resolution', '480p'), ('duration', -1), ('prompt', 'change the scene')]:
            original = data['payload']['input'][key]
            data['payload']['input'][key] = value
            with self.subTest(key=key), self.assertRaises(WorkflowError):
                video_tests.check_packet(self.run, data)
            data['payload']['input'][key] = original
        data['assets']['video']['sha256'] = 'different-clip'
        with self.assertRaisesRegex(WorkflowError, 'common clip'):
            video_tests.check_packet(self.run, data)
