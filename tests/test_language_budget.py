"""Language-scaled allowances and historical ledger compatibility."""
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from video_localizer import batches, budgets, media, workflow
from video_localizer.common import ROOT, WorkflowError, file_hash, read_json, write_json


class LanguageBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / 'work/test-tmp')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'config').mkdir()
        for name in ('budget-policy.json', 'workspace.json', 'language-aliases.json'):
            shutil.copyfile(ROOT / 'config' / name, self.root / 'config' / name)
        self.source = self.root / 'source.mp4'
        self.source.write_bytes(b'original fixture')
        self.spec = {'authority': 'user', 'authorization_ref': 'human:language-budget',
                     'user_request': 'Translate into Japanese, Spanish and Portuguese',
                     'mode': 'first', 'source': str(self.source), 'targets': ['ja', 'es', 'pt']}

    def open(self, targets=None):
        spec = self.spec if targets is None else {**self.spec, 'targets': targets}
        with patch.object(media, 'probe', return_value={'duration': 75}):
            return budgets.open_request(spec, self.root)

    def make_run(self, name, locale='ja', data=None):
        run = self.root / 'runs' / name
        run.mkdir(parents=True)
        source = run / 'source.mp4'
        source.write_bytes(self.source.read_bytes() if data is None else data)
        write_json(run / 'run.json', {'source': 'source.mp4', 'source_sha256': file_hash(source)})
        write_json(run / 'inputs/request.json', {'target_language': locale})
        return run

    def test_single_and_multiple_language_allowance_is_independent_of_duration(self):
        for targets, expected in [(['ja'], 60), (['ja', 'es', 'pt'], 180)]:
            for seconds in (1.23456, 10, 75, 600):
                with self.subTest(targets=targets, seconds=seconds), patch.object(media, 'probe', return_value={'duration': seconds}):
                    quote = budgets.request_allowance(self.source, targets, self.root)
                    self.assertEqual(quote['credit_limit'], expected)
                    self.assertEqual(quote['budget_basis']['source_duration_seconds'], seconds)
        self.assertEqual(self.open()['credit_limit'], 180)

    def test_aliases_case_and_duplicate_targets_do_not_issue_extra_credit(self):
        record = self.open(['ja', 'JA', 'es', 'ES'])
        self.assertEqual(record['credit_limit'], 120)
        self.assertEqual(record['budget_basis']['targets'], ['es', 'ja'])
        aliases = read_json(self.root / 'config/language-aliases.json')['groups']['ja']
        self.assertEqual(self.open(['ja', aliases[0]])['id'], record['id'])
        with patch.object(media, 'probe', return_value={'duration': 75}):
            quote = budgets.request_allowance(self.source, ['pt-BR', 'pt-PT'], self.root)
        self.assertEqual(quote['credit_limit'], 120)

    def test_missing_targets_and_invalid_duration_do_not_open_ledger(self):
        for targets in (None, [], 'ja', ['not a language']):
            with self.subTest(targets=targets), patch.object(media, 'probe', return_value={'duration': 75}):
                with self.assertRaises(WorkflowError):
                    budgets.open_request({**self.spec, 'targets': targets}, self.root)
        for seconds in (0, -1, float('nan'), float('inf')):
            with patch.object(media, 'probe', return_value={'duration': seconds}), self.assertRaises(WorkflowError):
                budgets.open_request(self.spec, self.root)
        self.assertFalse((self.root / 'state/budgets/index.json').exists())

    def test_shared_preparation_languages_and_clips_use_one_pool(self):
        record = self.open()
        first = self.make_run('japanese')
        second = self.make_run('spanish', 'es')
        child = self.make_run('short-clip', 'pt', b'clip')
        budgets.bind(first)
        budgets.bind(child, first)
        with patch.object(media, 'probe', side_effect=AssertionError('must inherit')):
            self.assertEqual(budgets.run_allowance(child)['credit_limit'], 180)
        with budgets.operation():
            budgets.reserve(first, 'a' * 64, 80)  # Shared visual preparation may exceed 60.
            budgets.reserve(second, 'b' * 64, 99)
            with self.assertRaisesRegex(WorkflowError, 'Whole-request'):
                budgets.reserve(child, 'c' * 64, 2)
        self.assertEqual(budgets.status(record['id'], self.root)['remaining_credits'], 1)
        with self.assertRaisesRegex(WorkflowError, 'Target languages'):
            budgets.bind(self.make_run('unregistered-language', 'de'))

    def test_retry_or_new_batch_cannot_expand_targets_or_replenish(self):
        record = self.open()
        for authorization in (self.spec['authorization_ref'], 'human:duplicate-first'):
            with self.assertRaisesRegex(WorkflowError, 'Target languages'):
                budgets.open_request({**self.spec, 'authorization_ref': authorization, 'targets': ['de']}, self.root)
        with self.assertRaisesRegex(WorkflowError, 'Target languages'):
            batches.create('unregistered', self.source, ['de'], 'fixture', root=self.root)
        self.assertFalse((self.root / 'state/batches/unregistered.json').exists())
        self.assertEqual(self.open()['credit_limit'], record['credit_limit'])

    def test_batch_members_inherit_pool_without_two_job_override(self):
        first = self.open()
        self.spec.update(mode='reuse', authorization_ref='human:batch-reuse', reuse_of=first['id'],
                         reuse_confirmation='new_user_request')
        self.open()
        write_json(self.root / 'config/profiles/company-default/profile.json', {})
        with patch.object(workflow, 'ROOT', self.root), patch.object(media, 'probe', return_value={'duration': 75}):
            result = batches.create('new-reuse', self.source, ['ja', 'es', 'pt'], 'fixture', reused=True, root=self.root)
            for name in result['members'].values():
                run = self.root / 'runs' / name
                self.assertFalse((run / 'inputs/budget.json').exists())
                self.assertEqual(workflow.execution_limits(run)['max_paid_jobs_per_run'], 32)
                self.assertEqual(workflow.execution_limits(run)['max_estimated_credits_per_run'], 180)
        self.assertEqual(result['credit_limit'], 180)

    def test_attributed_target_amendment_preserves_unknown_reservations(self):
        record = self.open()
        run = self.make_run('pending')
        with budgets.operation():
            budgets.reserve(run, 'a' * 64, 80)
        targets = ['ja', 'es', 'pt', 'de']
        amended = budgets.amend_limit(record['id'], 240, 'human:add-german', 'Add German at 60 credits', self.root, targets=targets)
        self.assertEqual(amended['credit_limit'], 240)
        self.assertEqual(budgets.status(record['id'], self.root)['remaining_credits'], 160)
        self.assertEqual(budgets.status(record['id'], self.root)['unknown_billing_jobs'], 1)
        budgets.bind(self.make_run('german', 'de'))
        self.assertEqual(budgets.amend_limit(record['id'], 240, 'human:add-german', 'same event', self.root, targets=targets)['authorized_amendments'], amended['authorized_amendments'])
        with self.assertRaisesRegex(WorkflowError, 'identity changed'):
            budgets.amend_limit(record['id'], 240, 'human:add-german', 'same event', self.root)

    def test_new_reuse_gets_sixty_per_language_and_keeps_old_request_closed(self):
        old = self.open()
        self.spec.update(mode='reuse', authorization_ref='human:new-reuse', reuse_of=old['id'], reuse_confirmation='new_user_request')
        record = self.open(['es', 'pt'])
        self.assertEqual(record['credit_limit'], 120)
        self.assertEqual(read_json(self.root / 'state/budgets' / (old['id'] + '.json'))['state'], 'closed')

    def test_historical_duration_limit_and_cost_do_not_change(self):
        write_json(self.root / 'config/budget-policy.json', {'mode': 'source_duration', 'max_credits_per_source_second': 3})
        old = self.open()
        run = self.make_run('historical')
        with budgets.operation():
            budgets.reserve(run, 'a' * 64, 80)
        shutil.copyfile(ROOT / 'config/budget-policy.json', self.root / 'config/budget-policy.json')
        with patch.object(media, 'probe', side_effect=AssertionError('no repricing')):
            self.assertEqual(self.open()['credit_limit'], 225)
            self.assertEqual(budgets.run_allowance(run)['credit_limit'], 225)
        self.assertEqual(budgets.status(old['id'], self.root)['remaining_credits'], 145)

    def test_task_slots_follow_segments_roles_and_request_ceiling(self):
        self.open()
        run = self.make_run('voices')
        budgets.bind(run)
        write_json(run / 'analysis/inventory.json', {'speech_segments': [{'character_id': f'role{i}'} for i in range(12)]})
        with patch.object(workflow, 'ROOT', self.root):
            limits = workflow.execution_limits(run)
        self.assertEqual(limits['max_paid_jobs_per_run'], 38)
        self.assertEqual(limits['max_estimated_credits_per_run'], 180)
