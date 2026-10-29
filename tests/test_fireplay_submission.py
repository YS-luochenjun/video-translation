"""Fireplay acceptance closes the owner workflow; YouTube runs on the platform."""
import unittest
import test_fireplay as fixtures
from video_localizer import fireplay, fireplay_monitor, fireplay_submission, batches
from video_localizer.common import WorkflowError, utc_now, write_json


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
        self.assertEqual(fireplay_monitor.followups(self.root)[0]['action'], 'verify_completion')
        self.completion()
        self.assertEqual(fireplay_monitor.followups(self.root), [])

    def test_unbound_items_are_not_mistaken_for_completed_submission(self):
        for row in self.rows: row['bound_verified'] = False
        write_json(self.folder/'user-approved-return-1.json', {'requirement_id': fixtures.RID,
                   'state': 'pending', 'items': self.rows})
        self.assertEqual(fireplay_submission.bound_materials(self.record(), self.record()['videos'][0], self.root), [])

    def test_partial_manual_return_does_not_hide_missing_locales(self):
        write_json(self.folder/'user-approved-return-1.json', {'requirement_id': fixtures.RID,
                   'state': 'returned_user_approved', 'items': self.rows[:1]})
        progress = fireplay_submission.coverage(self.record(), self.record()['videos'][0], self.root)
        self.assertEqual(progress['bound_locales'], ['es'])
        self.assertEqual(progress['missing_locales'], ['ko'])
        tasks = fireplay_monitor.followups(self.root)
        self.assertEqual(tasks[0]['action'], 'complete_delivery')
        self.assertEqual(tasks[0]['missing_locales'], ['ko'])

    def test_missing_outputs_still_get_a_completion_followup(self):
        task = fireplay_monitor.followups(self.root)[0]
        self.assertEqual(task['action'], 'complete_delivery')
        self.assertEqual(task['missing_locales'], ['es', 'ko'])

    def test_returned_label_and_empty_pending_do_not_hide_unknown_import(self):
        write_json(self.folder/'return-1.json', {'state':'returned', 'pending_locales':[],
                   'packages':[{'locale':r['locale'],'sha256':r['sha256']} for r in self.rows],
                   'operations':{'bind':{'state':'verified','result':{'material_ids':[fixtures.MID]}},
                                 'import-1':{'state':'verified','result':{'material_id':fixtures.MID}},
                                 'verify-1':{'state':'verified'}, 'import-2':{'state':'unknown'}}})
        self.assertEqual(fireplay_submission.bound_materials(self.record(), self.record()['videos'][0], self.root), [])
        self.assertEqual(fireplay_submission.coverage(self.record(), self.record()['videos'][0], self.root)['missing_locales'], ['ko'])
        self.assertEqual(fireplay_monitor.followups(self.root)[0]['missing_locales'], ['ko'])

    def test_canonical_returned_outbox_never_polls_youtube(self):
        box = {'state': 'returned', 'packages': [{'locale': r['locale'], 'sha256': r['sha256']} for r in self.rows],
               'operations': {'bind': {'state': 'verified'}}}
        for i,row in enumerate(self.rows,1):
            box['operations'][f'import-{i}'] = {'state': 'verified', 'result': {'material_id': row['material_id']}}
            box['operations'][f'upload-{i}'] = {'state': 'verified'}
            box['operations'][f'verify-{i}'] = {'state': 'verified'}
        write_json(self.folder/'return-1.json',box)
        self.assertEqual(fireplay_monitor.followups(self.root)[0]['action'], 'verify_completion')
        self.completion()
        self.assertEqual(fireplay_monitor.followups(self.root), [])
        result=fireplay.dispatch(fixtures.CODE, root=self.root)
        self.assertEqual(result['state'],'returned')
        self.assertIn('do not poll',result['next'])

    def completion(self, rows=None):
        write_json(self.folder/'user-approved-return-1.json', {'requirement_id':fixtures.RID,
                   'state':'returned_user_approved','items':self.rows})
        return fireplay_submission.verify_completion(fixtures.CODE, {'serverTime':utc_now(),
            'items':[{'id':fixtures.RID, 'status':'done', 'materials':rows if rows is not None else
                      [{'id':r['material_id']} for r in self.rows]}]}, self.root)

    def test_current_platform_read_checks_every_requested_locale(self):
        self.assertTrue(self.completion()['complete'])
        result = self.completion([{'id':fixtures.MID}])
        self.assertFalse(result['complete'])
        self.assertEqual([(r['locale'],r['reason']) for r in result['missing']],
                         [('ko','material_not_in_current_platform_binding')])

    def test_completion_requires_all_sources_and_does_not_trust_done_status(self):
        record = self.record()
        record['videos'].append({**record['videos'][0], 'index':2, 'targets':['es']})
        self.save(record)
        result = self.completion()
        self.assertFalse(result['complete'])
        self.assertEqual(result['expected_count'],3)
        self.assertEqual(result['missing'][0]['video_index'],2)

    def test_completion_rejects_stale_platform_read(self):
        with self.assertRaisesRegex(WorkflowError,'stale'):
            fireplay_submission.verify_completion(fixtures.CODE, {'serverTime':'2020-01-01T00:00:00Z',
                'items':[{'id':fixtures.RID,'materials':[]}]}, self.root)

    def test_access_contract_does_not_grant_spending_permission(self):
        auth=batches.authorization(self.root)
        self.assertFalse(auth['automatic_use'])
        self.assertFalse(auth['task_verification']['request_user_dashboard_login'])
        self.assertEqual(auth['task_verification']['mode'],'api_and_local_logs_only')
