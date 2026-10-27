"""Fireplay acceptance closes the owner workflow; YouTube runs on the platform."""
import unittest
import test_fireplay as fixtures
from video_localizer import fireplay, fireplay_monitor, fireplay_submission, batches
from video_localizer.common import write_json


class SubmissionClosureTests(unittest.TestCase):
    register = fixtures.FireplayTests.register
    record = fixtures.FireplayTests.record
    save = fixtures.FireplayTests.save

    def setUp(self):
        fixtures.FireplayTests.setUp(self)
        self.register()
        fireplay.chat(fixtures.CODE, {'title': fixtures.CODE, 'threadId': fixtures.THREAD}, root=self.root)
        self.folder = self.root / 'state/fireplay' / fixtures.CODE
        self.rows = [{'material_id': fixtures.MID, 'locale': 'es', 'sha256': 'a'*64, 'bound_verified': True},
                     {'material_id': fixtures.RESOURCE, 'locale': 'ko', 'sha256': 'b'*64, 'bound_verified': True}]

    def test_bound_legacy_receipt_is_not_redispatched_for_missing_youtube_links(self):
        write_json(self.folder/'user-approved-return-1.json', {'requirement_id': fixtures.RID,
                   'state': 'imported_bound_youtube_unverified_approval_required', 'items': self.rows})
        self.assertEqual(len(fireplay_submission.bound_materials(self.record(), self.record()['videos'][0], self.root)), 2)
        self.assertEqual(fireplay_monitor.followups(self.root), [])

    def test_unbound_items_are_not_mistaken_for_completed_submission(self):
        for row in self.rows: row['bound_verified'] = False
        write_json(self.folder/'user-approved-return-1.json', {'requirement_id': fixtures.RID,
                   'state': 'pending', 'items': self.rows})
        self.assertEqual(fireplay_submission.bound_materials(self.record(), self.record()['videos'][0], self.root), [])

    def test_canonical_returned_outbox_never_polls_youtube(self):
        box = {'state': 'returned', 'packages': [{'locale': r['locale'], 'sha256': r['sha256']} for r in self.rows],
               'operations': {'bind': {'state': 'verified'}}}
        for i,row in enumerate(self.rows,1):
            box['operations'][f'import-{i}'] = {'state': 'verified', 'result': {'material_id': row['material_id']}}
            box['operations'][f'upload-{i}'] = {'state': 'verified'}
            box['operations'][f'verify-{i}'] = {'state': 'verified'}
        write_json(self.folder/'return-1.json',box)
        self.assertEqual(fireplay_monitor.followups(self.root), [])
        result=fireplay.dispatch(fixtures.CODE, root=self.root)
        self.assertEqual(result['state'],'returned')
        self.assertIn('do not poll',result['next'])

    def test_access_contract_does_not_grant_spending_permission(self):
        auth=batches.authorization(self.root)
        self.assertFalse(auth['automatic_use'])
        self.assertFalse(auth['task_verification']['request_user_dashboard_login'])
        self.assertEqual(auth['task_verification']['mode'],'api_and_local_logs_only')
