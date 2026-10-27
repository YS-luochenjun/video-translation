"""Offline routing regression tests; no material or external upload is created."""
import copy
from datetime import datetime, timedelta, timezone
import unittest

import test_fireplay as fixtures
from video_localizer import fireplay, fireplay_youtube
from video_localizer.common import WorkflowError, file_hash, read_json, utc_now, write_json


class YouTubeRoutingTests(unittest.TestCase):
    register = fixtures.FireplayTests.register
    record = fixtures.FireplayTests.record
    save = fixtures.FireplayTests.save
    downloaded = fixtures.FireplayTests.downloaded
    returned_setup = fixtures.FireplayTests.returned_setup
    verify_upload = fixtures.FireplayTests.verify_upload

    def setUp(self):
        fixtures.FireplayTests.setUp(self)
        write_json(self.root / 'config/fireplay-youtube-routing.json', {'require_requirement_group': True})
        self.returned_setup()
        fireplay.dispatch(fixtures.CODE, True, self.root)
        self.verify_upload('upload-1')

    def box(self):
        return read_json(self.root / 'state/fireplay' / fixtures.CODE / 'return-1.json')

    def route(self):
        path = self.root / 'work/runs/test-routing/account.png'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'synthetic selection evidence, never a live upload')
        return {'method': 'host_web_account_selection', 'selected_account_id': fixtures.THREAD,
                'account': {'id': fixtures.THREAD, 'department_id': 'od-test', 'department_name': 'Test'},
                'selection_verified': True, 'observed_at': utc_now(),
                'evidence': {'path': str(path.relative_to(self.root)), 'sha256': file_hash(path)}}

    def test_correct_library_sharing_does_not_allow_default_youtube_account(self):
        before = self.box()
        result = fireplay.dispatch(fixtures.CODE, True, self.root)
        self.assertEqual(result['state'], 'needs_explicit_youtube_routing')
        self.assertEqual(result['expected_department'], {'id': 'test', 'name': 'Test'})
        self.assertEqual(self.box(), before)

    def test_missing_policy_keeps_safe_default(self):
        (self.root / 'config/fireplay-youtube-routing.json').unlink()
        self.assertEqual(fireplay.dispatch(fixtures.CODE, True, self.root)['state'], 'needs_explicit_youtube_routing')

    def test_platform_managed_policy_uses_normal_import_and_still_checks_sharing(self):
        write_json(self.root / 'config/fireplay-youtube-routing.json', {'require_requirement_group': False})
        operation = fireplay.dispatch(fixtures.CODE, True, self.root)['operation']
        self.assertEqual(operation['tool'], 'material_upload_from_url')
        self.assertEqual(operation['arguments']['VedioSouce'], 'YouTube')
        fireplay.receipt(fixtures.CODE, 'import-1', {'response': {'material_id': fixtures.MID}}, self.root)
        fireplay.dispatch(fixtures.CODE, True, self.root)
        material = {'id': fixtures.MID, 'name': fixtures.CODE+'-es', 'isPublic': False,
                    'sharedDeptId': 'wrong', 'tags': ['es', 'crush']}
        with self.assertRaisesRegex(WorkflowError, 'sharing'):
            fireplay.receipt(fixtures.CODE, 'verify-1', {'response': material}, self.root)
        material['sharedDeptId'] = 'test'
        self.assertEqual(fireplay.receipt(fixtures.CODE, 'verify-1', {'response': material}, self.root)['state'], 'verified')

    def test_latest_policy_recovers_old_unknown_material_without_requiring_task_group_or_reimport(self):
        fireplay_youtube.record_route(fixtures.CODE, self.route(), root=self.root)
        fireplay.dispatch(fixtures.CODE, True, self.root)
        receipt = {'response': {'material_id': fixtures.MID}}
        with self.assertRaises(WorkflowError):
            fireplay.receipt(fixtures.CODE, 'import-1', receipt, self.root)
        write_json(self.root / 'config/fireplay-youtube-routing.json', {'require_requirement_group': False})
        accepted = fireplay.receipt(fixtures.CODE, 'import-1', receipt, self.root)
        self.assertEqual(accepted['result']['material_id'], fixtures.MID)
        self.assertNotIn('youtube_task_verification', accepted['result'])
        self.assertEqual(fireplay.dispatch(fixtures.CODE, root=self.root)['state'], 'needs_material_verification')

    def test_wrong_group_and_unselected_default_are_rejected(self):
        for changes in ({'department_id': 'MOG', 'department_name': 'MOG'},
                        {'department_id': 'backend', 'department_name': '后端开发组'}):
            route = self.route()
            route['account'].update(changes)
            with self.assertRaisesRegex(WorkflowError, 'group differs'):
                fireplay_youtube.record_route(fixtures.CODE, route, root=self.root)
        route = self.route()
        route['selected_account_id'] = None
        with self.assertRaisesRegex(WorkflowError, 'actual selected'):
            fireplay_youtube.record_route(fixtures.CODE, route, root=self.root)

    def test_stale_changed_or_other_video_evidence_is_rejected(self):
        route = self.route()
        route['observed_at'] = (datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
        with self.assertRaisesRegex(WorkflowError, 'Refresh'):
            fireplay_youtube.record_route(fixtures.CODE, route, root=self.root)
        route = self.route()
        route['evidence']['sha256'] = '0'*64
        with self.assertRaisesRegex(WorkflowError, 'missing or changed'):
            fireplay_youtube.record_route(fixtures.CODE, route, root=self.root)
        route = self.route()
        route['video_sha256'] = '0'*64
        with self.assertRaisesRegex(WorkflowError, 'another video'):
            fireplay_youtube.record_route(fixtures.CODE, route, root=self.root)

    def test_actual_assignment_must_match_before_receipt_acceptance_and_no_retry(self):
        fireplay_youtube.record_route(fixtures.CODE, self.route(), root=self.root)
        dispatched = fireplay.dispatch(fixtures.CODE, True, self.root)
        self.assertIsNone(dispatched['operation']['tool'])
        self.assertEqual(dispatched['operation']['arguments']['host_action'], 'web_upload_with_verified_account')
        receipt = {'response': {'material_id': fixtures.MID}}
        with self.assertRaisesRegex(WorkflowError, 'Read back'):
            fireplay.receipt(fixtures.CODE, 'import-1', receipt, self.root)
        self.assertEqual(fireplay.dispatch(fixtures.CODE, True, self.root)['state'], 'needs_reconciliation')
        task = {'material_id': fixtures.MID, 'task_id': fixtures.RESOURCE, 'account_id': fixtures.THREAD,
                'account_department_id': 'test', 'account_department_name': 'Test', 'task_department_id': 'test'}
        bad = copy.deepcopy(task)
        bad['task_department_id'] = 'backend'
        with self.assertRaisesRegex(WorkflowError, 'group mismatch'):
            fireplay.receipt(fixtures.CODE, 'import-1', {**receipt, 'youtube_task_verification': bad}, self.root)
        self.assertEqual(self.box()['operations']['import-1']['state'], 'unknown')
        self.assertTrue(self.box()['operations']['import-1']['last_observed_receipt'])
        good = fireplay.receipt(fixtures.CODE, 'import-1', {**receipt, 'youtube_task_verification': task}, self.root)
        self.assertEqual(good['state'], 'verified')
        self.assertEqual(good['result']['material_id'], fixtures.MID)
        self.assertEqual(fireplay.dispatch(fixtures.CODE, root=self.root)['state'], 'needs_material_verification')

    def test_explicit_user_exception_preserves_scope_and_account_checks(self):
        fireplay_youtube.record_route(fixtures.CODE, self.route(), root=self.root)
        op = fireplay.dispatch(fixtures.CODE, True, self.root)['operation']
        record = fireplay._record(fixtures.CODE, self.root)
        path = self.root / 'state/fireplay' / fixtures.CODE / 'task-group-user-exception.json'
        grant = {'authority': 'user', 'authorization_ref': 'synthetic-user-exception',
                 'source_quote': 'Proceed after disclosed task-group display difference',
                 'ignore_task_group_display': True, 'requirement_id': record['requirement_id'],
                 'content_version': record['content_version'],
                 'video_sha256s': [op['youtube_route']['video_sha256']]}
        write_json(path, grant)
        task = {'material_id': fixtures.MID, 'account_id': fixtures.THREAD,
                'account_department_id': 'test', 'account_department_name': 'Test',
                'task_department_id': 'backend', 'user_exception_sha256': file_hash(path),
                'verification_scope': 'selected_account_and_fireplay_acceptance_user_exception'}
        receipt = {'response': {'material_id': fixtures.MID}, 'youtube_task_verification': task}
        for field, value in [('account_id', fixtures.MID), ('material_id', fixtures.RESOURCE),
                             ('account_department_id', 'backend'), ('user_exception_sha256', '0'*64)]:
            bad = copy.deepcopy(receipt)
            bad['youtube_task_verification'][field] = value
            with self.assertRaisesRegex(WorkflowError, 'Exception receipt'):
                fireplay.receipt(fixtures.CODE, 'import-1', bad, self.root)
        good = fireplay.receipt(fixtures.CODE, 'import-1', receipt, self.root)
        self.assertEqual(good['state'], 'verified')
        self.assertEqual(good['result']['youtube_task_verification']['task_department_id'], 'backend')
        self.assertEqual(good['result']['youtube_status'], 'requested_not_verified')

    def test_user_exception_for_another_video_does_not_relax_gate(self):
        fireplay_youtube.record_route(fixtures.CODE, self.route(), root=self.root)
        fireplay.dispatch(fixtures.CODE, True, self.root)
        record = fireplay._record(fixtures.CODE, self.root)
        write_json(self.root / 'state/fireplay' / fixtures.CODE / 'task-group-user-exception.json',
                   {'authority': 'user', 'authorization_ref': 'synthetic', 'source_quote': 'Proceed',
                    'ignore_task_group_display': True, 'requirement_id': record['requirement_id'],
                    'content_version': record['content_version'], 'video_sha256s': ['0'*64]})
        with self.assertRaisesRegex(WorkflowError, 'does not match'):
            fireplay.receipt(fixtures.CODE, 'import-1', {'response': {'material_id': fixtures.MID}}, self.root)
        self.assertEqual(self.box()['operations']['import-1']['state'], 'unknown')


if __name__ == '__main__':
    unittest.main()
