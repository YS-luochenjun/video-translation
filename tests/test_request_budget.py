import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock

from video_localizer import budgets
from video_localizer.common import WorkflowError, file_hash, read_json, write_json
from video_localizer.kie import KieClient


class RequestBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'work/test-tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'original.mp4'; self.source.write_bytes(b'synthetic original')
        self.spec = {'authority': 'user', 'authorization_ref': 'host:human-message-1',
                     'user_request': 'Translate this original to two languages', 'mode': 'first', 'source': str(self.source)}
        self.scope = budgets.open_request(self.spec, self.root)['id']
        self.run = self.make_run('first')
        self.op = budgets.operation(); self.op.__enter__(); self.addCleanup(self.op.__exit__, None, None, None)

    def make_run(self, name, content=None):
        run = self.root / 'runs' / name; run.mkdir(parents=True)
        (run / 'source.mp4').write_bytes(self.source.read_bytes() if content is None else content)
        write_json(run / 'run.json', {'source': 'source.mp4', 'source_sha256': file_hash(run / 'source.mp4')})
        return run

    def test_new_runs_and_new_first_request_ids_cannot_replenish(self):
        budgets.reserve(self.run, 'a'*64, 59)
        new = self.make_run('split-locale')
        self.assertEqual(budgets.open_request({**self.spec, 'authorization_ref': 'invented-new-run-id'}, self.root)['id'], self.scope)
        with self.assertRaisesRegex(WorkflowError, 'Whole-request'):
            budgets.reserve(new, 'b'*64, 2)
        budgets.reserve(new, 'b'*64, 1)
        self.assertEqual(budgets.status(self.scope, self.root)['remaining_credits'], 0)

    def test_derived_clip_inherits_parent_and_cannot_open_another_first_allowance(self):
        budgets.reserve(self.run, 'a'*64, 40)
        child = self.make_run('short-clip', b'derived bytes')
        with self.assertRaisesRegex(WorkflowError, 'Unbound paid run'):
            budgets.reserve(child, 'b'*64, 21)
        budgets.bind(child, self.run)
        with self.assertRaisesRegex(WorkflowError, 'Whole-request'):
            budgets.reserve(child, 'b'*64, 21)
        reopened = budgets.open_request({**self.spec, 'source': str(child / 'source.mp4'),
                                         'authorization_ref': 'different-worker-id'}, self.root)
        self.assertEqual(reopened['id'], self.scope)

    def test_one_host_event_cannot_open_budget_for_another_source(self):
        other = self.root / 'other.mp4'; other.write_bytes(b'other')
        with self.assertRaisesRegex(WorkflowError, 'multiple budgets'):
            budgets.open_request({**self.spec, 'source': str(other)}, self.root)

    def test_reuse_requires_new_user_event_and_reconciliation(self):
        budgets.reserve(self.run, 'a'*64, 20)
        spec = {**self.spec, 'mode': 'reuse', 'authorization_ref': 'host:human-message-2',
                'reuse_of': self.scope, 'reuse_confirmation': 'new_user_request'}
        with self.assertRaisesRegex(WorkflowError, 'Reconcile'):
            budgets.open_request(spec, self.root)
        write_json(self.run / 'jobs' / ('a'*64 + '.json'), {'id': 'a'*64, 'state': 'success',
                   'task_id': 'synthetic', 'estimated_credits': 20, 'credits_consumed': 8})
        reuse = budgets.open_request(spec, self.root)
        self.assertEqual(reuse['credit_limit'], 40)
        self.assertEqual(budgets.open_request(spec, self.root)['id'], reuse['id'])
        with self.assertRaisesRegex(WorkflowError, 'closed'):
            budgets.reserve(self.run, 'b'*64, 1)
        new = self.make_run('new-user-reuse')
        budgets.reserve(new, 'c'*64, 40)
        with self.assertRaisesRegex(WorkflowError, 'Whole-request'):
            budgets.reserve(self.make_run('reuse-split'), 'd'*64, 1)

    def test_direct_provider_call_and_repeated_post_are_blocked_before_transport(self):
        opener = Mock()
        client = KieClient('synthetic-key', opener)
        with self.assertRaisesRegex(WorkflowError, 'executor reservation'):
            client.create({'model': 'wan/2-7-videoedit'})
        opener.open.assert_not_called()
        budgets.reserve(self.run, 'a'*64, 5)
        opener.open.return_value = io.BytesIO(json.dumps({'code': 200, 'data': {'taskId': 'fixture'}}).encode())
        self.assertEqual(client.create({'model': 'wan/2-7-videoedit'}), 'fixture')
        with self.assertRaisesRegex(WorkflowError, 'already dispatched'):
            client.create({'model': 'wan/2-7-videoedit'})
        self.assertEqual(opener.open.call_count, 1)

    def test_existing_unbound_runs_are_imported_before_new_first_run_can_spend(self):
        source = self.root / 'legacy.mp4'; source.write_bytes(b'legacy original')
        legacy = self.make_run('legacy', source.read_bytes())
        write_json(legacy / 'jobs' / ('e'*64 + '.json'), {'id': 'e'*64, 'state': 'success',
                   'task_id': 'old-paid-task', 'credits_consumed': 55})
        record = budgets.open_request({**self.spec, 'source': str(source),
                                      'authorization_ref': 'host:legacy-human-event'}, self.root)
        self.assertEqual(budgets.status(record['id'], self.root)['remaining_credits'], 5)
        with self.assertRaisesRegex(WorkflowError, 'Whole-request'):
            budgets.reserve(self.make_run('new-legacy-run', source.read_bytes()), 'f'*64, 6)

    def test_settled_historical_receipts_are_not_rebilled_in_a_new_reuse_request(self):
        budgets.bind(self.run)
        paid = {'id': 'a'*64, 'state': 'success', 'task_id': 'previous-request', 'credits_consumed': 25}
        write_json(self.run / 'jobs' / ('a'*64 + '.json'), paid)
        record = budgets.open_request({**self.spec, 'mode': 'reuse', 'authorization_ref': 'host:reuse-human-event',
                    'reuse_of': self.scope, 'reuse_confirmation': 'new_user_request'}, self.root)
        restored = self.make_run('restored-into-new-request')
        write_json(restored / 'jobs' / ('a'*64 + '.json'), paid)
        budgets.bind(restored)
        self.assertEqual(budgets.status(record['id'], self.root)['reserved_or_billed_credits'], 0)
        budgets.reserve(restored, 'b'*64, 40)
        self.assertEqual(budgets.status(record['id'], self.root)['remaining_credits'], 0)

    def test_restored_receipts_deduplicate_but_distinct_actual_tasks_do_not(self):
        other = self.make_run('restored')
        for run in (self.run, other):
            write_json(run / 'jobs' / ('a'*64 + '.json'), {'id': 'a'*64, 'state': 'success',
                'task_id': 'same-provider-task', 'credits_consumed': 20})
            budgets.bind(run)
        self.assertEqual(budgets.status(self.scope, self.root)['reserved_or_billed_credits'], 20)
        write_json(other / 'jobs' / ('a'*64 + '.json'), {'id': 'a'*64, 'state': 'success',
                    'task_id': 'distinct-actually-charged-task', 'credits_consumed': 15})
        self.assertEqual(budgets.status(self.scope, self.root)['reserved_or_billed_credits'], 35)
        self.assertEqual(budgets.status(self.scope, self.root)['reserved_or_billed_credits'], 35)

    def test_missing_journal_after_reservation_and_deleted_run_keep_the_charge(self):
        budgets.reserve(self.run, 'a'*64, 60)
        shutil.rmtree(self.run)
        with self.assertRaisesRegex(WorkflowError, 'Whole-request'):
            budgets.reserve(self.make_run('restart'), 'b'*64, 1)


if __name__ == '__main__':
    unittest.main()
