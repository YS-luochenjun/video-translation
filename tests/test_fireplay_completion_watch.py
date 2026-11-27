"""Completion-watch scheduling must preserve scope and require current closure evidence."""
import unittest
import test_fireplay as fixtures
import test_fireplay_submission as submission_fixtures
from video_localizer import fireplay_monitor as monitor, fireplay_parallel as parallel, fireplay_submission as submission
from video_localizer.common import read_json, write_json


class CompletionWatchTests(unittest.TestCase):
    register = fixtures.FireplayTests.register
    record = fixtures.FireplayTests.record
    save = fixtures.FireplayTests.save
    setUp = submission_fixtures.SubmissionClosureTests.setUp
    completion = submission_fixtures.SubmissionClosureTests.completion

    def manifest(self, **extra):
        path = self.root / 'work/fireplay-monitor/current-completion-watch.json'
        write_json(path, {'status': 'ACTIVE', 'automation_id': 'test-watch', 'requirements': [{
            'code': fixtures.CODE, 'requirement_id': fixtures.RID,
            'threadId': fixtures.THREAD, 'hostId': 'local'}], **extra})
        return path

    def plan(self):
        return monitor.completion_watch_status(monitor.followups(self.root), self.root)

    def test_unfinished_owner_requires_one_ten_minute_watch(self):
        value = self.plan()
        self.assertEqual(value['host_action'], 'ensure_active')
        self.assertEqual(value['interval_minutes'], 10)
        self.assertEqual(value['owner_status_checks'][0]['threadId'], fixtures.THREAD)
        self.assertFalse(value['owner_status_is_completion_evidence'])
        self.assertEqual(len(value['requirements']), 1)
        self.manifest()
        value = self.plan()
        self.assertEqual(value['automation_id'], 'test-watch')
        self.assertEqual(len(value['requirements']), 1)
        self.assertEqual(value['discovery_automation_action'], 'keep_active')

    def test_complete_check_without_close_cannot_end_watch(self):
        self.manifest()
        self.completion()
        self.assertEqual(monitor.followups(self.root), [])
        self.assertEqual(self.plan()['host_action'], 'ensure_active')
        submission.close_delivery(fixtures.CODE, self.root)
        self.assertEqual(self.plan()['host_action'], 'delete_completion_watch')
        check = read_json(self.folder / 'completion-check.json')
        check['verified'][0]['sha256'] = 'c' * 64
        write_json(self.folder / 'completion-check.json', check)
        self.assertEqual(self.plan()['host_action'], 'ensure_active')

    def test_missing_or_changed_watched_request_never_disappears(self):
        self.manifest()
        (self.folder / 'request.json').unlink()
        value = monitor.completion_watch_status([], self.root)
        self.assertEqual(value['host_action'], 'ensure_active')
        self.assertEqual(value['pending'][0]['code'], fixtures.CODE)
        self.assertEqual(value['verified_complete'], [])

    def test_readonly_approval_rejection_prevents_automatic_upgrade(self):
        self.manifest(mode='read_only', followup_approval_required=True)
        value = self.plan()
        self.assertEqual(value['host_action'], 'observe_only')
        self.assertTrue(value['followup_approval_required'])
        self.assertFalse(value['automatic_approval'])

    def test_new_owner_appends_without_dropping_unavailable_prior_scope(self):
        path = self.manifest()
        value = read_json(path)
        old = dict(value['requirements'][0], code='KEY-20261027-999', requirement_id=fixtures.MID)
        value['requirements'].append(old)
        write_json(path, value)
        plan = self.plan()
        self.assertEqual(len(plan['requirements']), 2)
        self.assertEqual(len(plan['pending']), 2)
        self.assertEqual(plan['host_action'], 'ensure_active')

    def test_finished_batch_does_not_revive_without_new_owner(self):
        self.completion()
        submission.close_delivery(fixtures.CODE, self.root)
        self.manifest(status='COMPLETE_DELETED')
        self.assertEqual(monitor.completion_watch_status([], self.root)['host_action'], 'none')
        self.assertEqual(self.plan()['requirements'], [])

    def test_manual_owner_without_publication_followup_is_watched(self):
        self.completion()
        self.assertEqual(monitor.followups(self.root), [])
        value = self.plan()
        self.assertEqual(value['host_action'], 'ensure_active')
        self.assertEqual(value['scheduler_action'], 'create')
        self.assertEqual(value['pending'][0]['threadId'], fixtures.THREAD)

    def test_newer_platform_rejection_suppresses_old_followups_and_watch(self):
        self.manifest()
        record = self.record()
        saved_row = record['snapshot']['row']
        saved_row.update(status='in_progress', updatedAt='2026-11-27T04:00:00Z')
        self.save(record)
        cached_followups = monitor.followups(self.root)
        self.assertTrue(cached_followups)
        platform_row = dict(saved_row, id=fixtures.RID, code=fixtures.CODE,
                            status='rejected', updatedAt='2026-11-27T07:00:00Z')
        state_path = self.root / 'state/fireplay/monitor/state.json'
        write_json(state_path, {'requirements': {fixtures.RID: {'row': platform_row, 'state': 'registered'}}})

        self.assertEqual(monitor.followups(self.root), [])
        value = monitor.completion_watch_status(cached_followups, self.root)
        self.assertEqual(value['host_action'], 'delete_completion_watch')
        self.assertEqual(value['requirements'], [])
        self.assertEqual(value['owner_status_checks'], [])
        self.assertEqual(self.record(), record)

        platform_row.update(updatedAt='2026-11-27T03:00:00Z')
        write_json(state_path, {'requirements': {fixtures.RID: {'row': platform_row, 'state': 'registered'}}})
        self.assertTrue(monitor.followups(self.root))

    def test_rejected_history_releases_inferred_capacity_and_preserves_explicit_claim(self):
        record = self.record()
        row = record['snapshot']['row']
        row.update(status='in_progress', updatedAt='2026-11-27T04:00:00Z')
        record['videos'][0]['chat'] = dict(record['chat'])
        self.save(record)
        source = (fixtures.RID, 1)
        self.assertEqual(parallel.active_sources(self.root, {}), {source})

        platform_row = dict(row, id=fixtures.RID, code=fixtures.CODE,
                            status='rejected', updatedAt='2026-11-27T07:00:00Z')
        write_json(self.root / 'state/fireplay/monitor/state.json',
                   {'requirements': {fixtures.RID: {'row': platform_row}}})
        self.assertEqual(parallel.active_sources(self.root, {}), set())
        claim = {'state': 'dispatch_unknown', 'requirement_id': fixtures.RID, 'video_index': 1}
        self.assertEqual(parallel.active_sources(self.root, {'ticket': claim}), {source})

        record['videos'][0]['chat']['state'] = 'unknown'
        self.save(record)
        self.assertEqual(parallel.active_sources(self.root, {}), {source})

    def test_new_owner_restarts_deleted_watch_without_old_automation_id(self):
        self.manifest(status='COMPLETE_DELETED')
        value = self.plan()
        self.assertEqual(value['scheduler_action'], 'create')
        self.assertIsNone(value['automation_id'])
        self.assertTrue(value['restart_when_new_owner'])

    def test_new_manual_owner_during_active_watch_is_appended(self):
        path = self.manifest()
        value = read_json(path)
        value['requirements'] = [dict(value['requirements'][0], code='KEY-20261027-999', requirement_id=fixtures.MID)]
        write_json(path, value)
        value = monitor.completion_watch_status([], self.root)
        self.assertEqual(len(value['requirements']), 2)
        self.assertEqual(value['scheduler_action'], 'update')
        self.assertIn(fixtures.CODE, [row['code'] for row in value['pending']])

    def test_accepted_legacy_batch_does_not_reopen_for_missing_close(self):
        self.completion()
        record = self.record()
        record['created_at'] = '2020-01-01T00:00:00+00:00'
        self.save(record)
        self.manifest(requirements=[], enrollment_started_at='2026-11-09T00:00:00+00:00')
        self.assertEqual(self.plan()['pending'], [])

    def test_closed_original_scope_cannot_end_watch_with_a_new_owner(self):
        self.completion()
        submission.close_delivery(fixtures.CODE, self.root)
        self.manifest()
        record = self.record()
        record.update(code='KEY-20261027-999', requirement_id=fixtures.MID)
        write_json(self.root / 'state/fireplay/KEY-20261027-999/request.json', record)
        value = self.plan()
        self.assertEqual(value['host_action'], 'ensure_active')
        self.assertEqual(value['scheduler_action'], 'update')
        self.assertEqual(value['pending'][0]['code'], 'KEY-20261027-999')


if __name__ == '__main__':
    unittest.main()
