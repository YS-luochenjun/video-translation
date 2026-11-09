"""Coordination isolation, crash recovery and shared-budget invariants."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'src'))
from video_localizer import fireplay_parallel as parallel
from video_localizer.common import WorkflowError, file_hash, read_json, write_json


CODE = 'MOG-20261105-037'
OWNER = '01a1aac6-959b-7682-9238-b03f5c87bbb5'
RID = '01a1aabd-c3e8-7d49-8e0f-350a9a611de5'


class ParallelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        write_json(self.root / 'config/fireplay-parallel.json', {
            'enabled': True, 'max_active_sources_per_requirement': 2,
            'max_active_sources_global': 3, 'lease_minutes': 120})
        self.record = self.make_requirement(CODE, RID)
        self.evidence = self.root / 'work/observation.json'
        write_json(self.evidence, {'actual_observation': 'worker-stopped'})

    def make_requirement(self, code, rid):
        videos = []
        for index in range(1, 4):
            name = f'{code}-{index}-01'
            source = self.root / 'runs' / name / 'inputs/source.mp4'
            source.parent.mkdir(parents=True)
            source.write_bytes(f'fixture-source-{code}-{index}'.encode())
            videos.append({'index': index, 'title': f'{code}-{index}', 'targets': ['es', 'pt'],
                           'pilot': name, 'members': [name],
                           'source': {'path': source.relative_to(self.root).as_posix(),
                                      'sha256': file_hash(source)}})
        record = {'code': code, 'requirement_id': rid, 'content_version': 'old-version',
                  'targets': ['es', 'pt'], 'budget': 'original-shared-budget', 'videos': videos,
                  'chat': {'state': 'ready', 'threadId': OWNER}, 'blockers': []}
        write_json(self.root / 'state/fireplay' / code / 'request.json', record)
        return record

    def save(self):
        write_json(self.root / 'state/fireplay' / CODE / 'request.json', self.record)

    def claim(self, index=1, kind='owner', code=CODE, token=None, **extra):
        spec = {'action': 'claim', 'video_index': index, 'actor_id': OWNER,
                'owner_thread_id': OWNER, 'claim_token': token or f'claim-token-{code}-{index}',
                'assignee_kind': kind, **extra}
        if kind == 'owner':
            spec['assignee_id'] = OWNER
        return parallel.update(code, spec, self.root)

    def change(self, task, action, **extra):
        return parallel.update(task['code'], {'action': action, 'task_id': task['task_id'],
                               'actor_id': OWNER, 'claim_token': task['claim_token'], **extra}, self.root)

    def attach(self, task, worker='worker-one'):
        path = self.root / f'work/{worker}-receipt.json'
        write_json(path, {'agent_id': worker})
        return self.change(task, 'reconcile', assignee_id=worker,
                           evidence=[path.relative_to(self.root).as_posix()])

    def test_plan_is_readonly_and_freezes_source_identity_without_budget_mutation(self):
        before = copy.deepcopy(self.record)
        result = parallel.plan(CODE, self.root)
        self.assertEqual(len(result['sources']), 3)
        self.assertTrue(all(x['runnable'] for x in result['sources']))
        self.assertEqual(result['budget_id'], 'original-shared-budget')
        self.assertFalse((self.root / 'state/fireplay/parallel.json').exists())
        self.assertFalse((self.root / 'state/budgets').exists())
        self.assertEqual(read_json(self.root / 'state/fireplay' / CODE / 'request.json'), before)

    def test_duplicate_claim_and_cap_include_owner_and_unknown_child(self):
        first = self.claim()
        self.assertEqual(self.claim(), first)
        with self.assertRaisesRegex(WorkflowError, 'already has an owner'):
            self.claim(token='different-token')
        child = self.claim(2, 'subagent')
        self.assertEqual(child['state'], 'dispatch_unknown')
        with self.assertRaisesRegex(WorkflowError, 'Requirement active source limit'):
            self.claim(3, 'subagent')
        self.assertEqual(parallel.status(CODE, self.root)['active_source_count'], 2)

    def test_global_cap_covers_other_requirements(self):
        self.claim(1)
        self.claim(2, 'subagent')
        other = 'SHE-20261105-032'
        self.make_requirement(other, '01a1a9f2-f8c8-7580-b7c9-50ef0ed6fb79')
        self.claim(1, code=other)
        with self.assertRaisesRegex(WorkflowError, 'Global active source limit'):
            self.claim(2, 'subagent', code=other)

    def test_unknown_dispatch_must_have_actual_receipt_before_work(self):
        task = self.claim(1, 'subagent')
        with self.assertRaisesRegex(WorkflowError, 'Reconcile actual worker first'):
            self.change(task, 'heartbeat')
        with self.assertRaisesRegex(WorkflowError, 'actual worker id'):
            self.change(task, 'reconcile', assignee_id='missing-worker', evidence=['work/observation.json'])
        active = self.attach(task)
        self.assertEqual(active['assignee_id'], 'worker-one')
        self.assertEqual(active['state'], 'active')
        with self.assertRaisesRegex(WorkflowError, 'Only unknown dispatch'):
            self.attach(task)

    def test_lease_expiry_never_frees_claim_or_unknown_dispatch(self):
        task = self.claim(1, 'subagent')
        path = self.root / 'state/fireplay/parallel.json'
        journal = read_json(path)
        journal['tasks'][task['task_id']]['lease_expires_at'] = '2000-01-01T00:00:00+00:00'
        write_json(path, journal)
        self.assertTrue(parallel.status(CODE, self.root)['tasks'][0]['lease_expired'])
        with self.assertRaisesRegex(WorkflowError, 'already has an owner'):
            self.claim(1, 'subagent', token='another-claim-token')
        with self.assertRaisesRegex(WorkflowError, 'reconciled before release'):
            self.change(task, 'release', relinquish=True, work_stopped=True,
                        reason='explicit checked recovery', evidence=['work/observation.json'])
        released = self.change(task, 'release', relinquish=True, work_stopped=True,
                               reconciled_no_worker=True, reason='actual spawn did not happen',
                               evidence=['work/observation.json'])
        self.assertEqual(released['state'], 'released')
        retry = self.claim(1, 'subagent', token='new-reviewed-token')
        self.assertTrue(any(x['action'] == 'previous_claim' for x in retry['history']))

    def test_claim_owner_and_worker_updates_are_scoped(self):
        with self.assertRaisesRegex(WorkflowError, 'existing owner'):
            self.claim(actor_id='other-chat')
        with self.assertRaisesRegex(WorkflowError, 'overrides are prohibited'):
            self.claim(allowed_paths=['.'])
        task = self.attach(self.claim(1, 'subagent'))
        with self.assertRaisesRegex(WorkflowError, 'Only the owner or the assigned worker'):
            self.change(task, 'heartbeat', actor_id='unrelated-worker')
        self.assertEqual(self.change(task, 'heartbeat', actor_id='worker-one')['state'], 'active')
        with self.assertRaisesRegex(WorkflowError, 'Claim token'):
            self.change(task, 'heartbeat', claim_token='not-the-token')
        self.assertEqual(task['permissions'], {'production_only': True, 'paid_submission': False,
                         'budget_mutation': False, 'platform_submission': False, 'spawn_children': False})

    def test_source_and_content_changes_block_stale_completion_and_new_claim(self):
        task = self.claim()
        self.record['content_version'] = 'actual-revised-version'
        self.save()
        with self.assertRaisesRegex(WorkflowError, 'content version changed'):
            self.change(task, 'complete', evidence=[self.record['videos'][0]['source']['path']])
        with self.assertRaisesRegex(WorkflowError, 'previous source/content version'):
            self.claim(token='revised-version-token')
        self.change(task, 'release', relinquish=True, work_stopped=True, reason='reviewed revision',
                    evidence=['work/observation.json'])
        fresh = self.claim(token='revised-version-token')
        self.assertNotEqual(task['task_id'], fresh['task_id'])

    def test_changed_source_bytes_and_missing_source_are_not_runnable(self):
        source = self.root / self.record['videos'][0]['source']['path']
        source.write_bytes(b'changed bytes')
        result = parallel.plan(CODE, self.root)
        self.assertFalse(result['sources'][0]['runnable'])
        self.assertEqual(result['sources'][0]['state'], 'source_not_ready')
        with self.assertRaisesRegex(WorkflowError, 'SHA256 changed'):
            self.claim()

    def test_complete_requires_scoped_actual_files_and_does_not_close_requirement(self):
        task = self.claim()
        with self.assertRaisesRegex(WorkflowError, 'outside the assigned source'):
            self.change(task, 'complete', evidence=[self.record['videos'][1]['source']['path']])
        with self.assertRaisesRegex(WorkflowError, 'does not exist'):
            self.change(task, 'complete', evidence=['runs/missing/report.json'])
        path = self.root / task['allowed_paths'][0] / 'review/worker-handoff.json'
        write_json(path, {'review': 'actual fixture observation', 'quality': 'pending_owner_review'})
        result = self.change(task, 'complete', evidence=[path.relative_to(self.root).as_posix()])
        self.assertEqual(result['state'], 'worker_complete')
        self.assertEqual(result['completion_evidence'][0]['sha256'], file_hash(path))
        self.assertFalse(result['whole_requirement_complete'])
        self.assertFalse((self.root / 'state/fireplay' / CODE / 'delivery-closure.json').exists())

    def test_stale_unknown_can_attach_actual_identity_but_remains_blocked(self):
        task = self.claim(1, 'subagent')
        self.record['content_version'] = 'new-version'
        self.save()
        blocked = self.attach(task)
        self.assertEqual(blocked['state'], 'blocked')
        self.assertIn('Stale source scope', blocked['reason'])
        with self.assertRaisesRegex(WorkflowError, 'Blocked source'):
            self.change(blocked, 'complete', evidence=['work/observation.json'])

    def test_disabled_policy_has_no_runnable_plan_or_instruction(self):
        path = self.root / 'config/fireplay-parallel.json'
        value = read_json(path)
        value['enabled'] = False
        write_json(path, value)
        self.assertTrue(all(not source['runnable'] for source in parallel.plan(CODE, self.root)['sources']))
        self.assertEqual(parallel.instruction(self.root), '')
        with self.assertRaisesRegex(WorkflowError, 'not enabled'):
            self.claim()
        self.assertFalse((self.root / 'state/fireplay/parallel.json').exists())
        value['enabled'] = True
        write_json(path, value)
        instruction = parallel.instruction(self.root)
        self.assertIn('dispatch_unknown', instruction)
        self.assertIn('不新建预算', instruction)
        self.assertIn('不发付费模型', instruction)

    def test_unstarted_sources_require_owner_start_before_claim(self):
        self.record.pop('budget')
        self.record['videos'][0].pop('members')
        self.save()
        plan = parallel.plan(CODE, self.root)
        self.assertEqual(plan['sources'][0]['state'], 'needs_owner_start')
        self.assertFalse(any(v['runnable'] for v in plan['sources']))
        with self.assertRaisesRegex(WorkflowError, 'fireplay-start'):
            self.claim()

    def test_fully_bound_source_is_not_offered_or_reclaimed(self):
        path = self.root / 'state/fireplay' / CODE / 'user-approved-return-1.json'
        write_json(path, {'requirement_id': RID, 'state': 'returned_user_approved',
                         'items': [{'locale': locale, 'material_id': f'01a1aabd-c3e8-7d49-8e0f-350a9a611de{index}',
                                    'sha256': 'a' * 64} for index, locale in enumerate(['es', 'pt'])]})
        source = parallel.plan(CODE, self.root)['sources'][0]
        self.assertEqual(source['state'], 'already_bound')
        self.assertFalse(source['runnable'])
        with self.assertRaisesRegex(WorkflowError, 'already fully bound'):
            self.claim()

    def test_same_token_does_not_hide_changed_targets_or_paths(self):
        task = self.claim()
        self.record['videos'][0]['targets'].append('de')
        self.save()
        with self.assertRaisesRegex(WorkflowError, 'targets or shared budget changed'):
            self.claim()
        self.record['videos'][0]['targets'].remove('de')
        self.record['videos'][0]['members'].append(CODE + '-1-extra')
        self.save()
        with self.assertRaisesRegex(WorkflowError, 'run paths changed'):
            self.claim()

    def test_run_symlink_scope_resolves_inside_workspace(self):
        old_runs = self.root / 'runs'
        actual_runs = self.root / 'work/runs'
        actual_runs.parent.mkdir(exist_ok=True)
        old_runs.rename(actual_runs)
        old_runs.symlink_to(actual_runs, target_is_directory=True)
        source = parallel.plan(CODE, self.root)['sources'][0]
        self.assertEqual(source['allowed_paths'], ['work/runs/' + CODE + '-1-01'])
        self.assertTrue(source['runnable'])
        self.assertEqual(self.claim()['allowed_paths'], source['allowed_paths'])


if __name__ == '__main__':
    unittest.main()
