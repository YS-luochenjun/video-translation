"""A no-retry decision must not duplicate or erase an uncertain upload."""
import unittest
import test_fireplay as fixtures
from video_localizer import fireplay, fireplay_submission
from video_localizer.common import WorkflowError, read_json, utc_now


class DeferredUploadTests(unittest.TestCase):
    setUp = fixtures.FireplayTests.setUp
    register = fixtures.FireplayTests.register
    record = fixtures.FireplayTests.record
    save = fixtures.FireplayTests.save
    downloaded = fixtures.FireplayTests.downloaded
    returned_setup = fixtures.FireplayTests.returned_setup
    verify_upload = fixtures.FireplayTests.verify_upload

    def decision(self):
        return {'authority': 'user', 'authorization_ref': 'test:user-no-retry',
                'source_quote': 'Keep the unknown file upload; do not retry it.'}

    def test_deferred_unknown_preserved_while_other_locale_binds(self):
        self.returned_setup()
        original = fireplay.dispatch(fixtures.CODE, True, self.root)['operation']
        fireplay.defer_unknown_upload(fixtures.CODE, 'es', self.decision(), self.root)
        fireplay.defer_unknown_upload(fixtures.CODE, 'es', self.decision(), self.root)
        operation = fireplay.dispatch(fixtures.CODE, True, self.root)['operation']
        self.assertEqual(operation['id'], 'upload-2')
        self.verify_upload('upload-2')
        fireplay.dispatch(fixtures.CODE, True, self.root)
        fireplay.receipt(fixtures.CODE, 'import-2', {'response': {'material_id': fixtures.MID}}, self.root)
        fireplay.dispatch(fixtures.CODE, True, self.root)
        fireplay.receipt(fixtures.CODE, 'verify-2', {'response': {'material': {
            'id': fixtures.MID, 'name': fixtures.CODE + '-ko', 'isPublic': False,
            'sharedDeptId': 'test', 'tags': ['ko', 'crush']}}}, self.root)
        binding = fireplay.dispatch(fixtures.CODE, True, self.root)['operation']
        self.assertEqual(binding['arguments']['items'][0]['material_ids'], [fixtures.MID])
        fireplay.receipt(fixtures.CODE, 'bind', {'response': {'success': True}, 'verification': {
            'serverTime': utc_now(), 'items': [{'id': fixtures.RID, 'materials': [{'id': fixtures.MID}]}]}}, self.root)
        path = self.root / 'state/fireplay' / fixtures.CODE / 'return-1.json'
        box = read_json(path)
        original.pop('arguments_file', None)
        self.assertEqual(box['operations']['upload-1'], original)
        self.assertNotIn('import-1', box['operations'])
        self.assertEqual(box['pending_locales'], ['es'])
        self.assertEqual(fireplay.dispatch(fixtures.CODE, root=self.root)['state'], 'partially_returned')
        self.assertEqual(fireplay_submission.bound_materials(self.record(), self.record()['videos'][0], self.root), [])

    def test_no_automatic_skip_or_unattributed_deferral(self):
        self.returned_setup()
        fireplay.dispatch(fixtures.CODE, True, self.root)
        self.assertEqual(fireplay.dispatch(fixtures.CODE, True, self.root)['state'], 'needs_reconciliation')
        with self.assertRaisesRegex(WorkflowError, 'actual user decision'):
            fireplay.defer_unknown_upload(fixtures.CODE, 'es', {}, self.root)
        with self.assertRaisesRegex(WorkflowError, 'unknown file upload'):
            fireplay.defer_unknown_upload(fixtures.CODE, 'ko', self.decision(), self.root)
        self.verify_upload('upload-1')
        fireplay.dispatch(fixtures.CODE, True, self.root)
        with self.assertRaisesRegex(WorkflowError, 'unknown file upload'):
            fireplay.defer_unknown_upload(fixtures.CODE, 'es', self.decision(), self.root)

    def test_attributed_agent_observation_cannot_retry_or_import_unknown_upload(self):
        self.returned_setup()
        fireplay.dispatch(fixtures.CODE, True, self.root)
        observation = {**self.decision(), 'authority': 'agent',
                       'authorization_ref': 'test:actual-upload-timeout',
                       'source_quote': 'Actual host upload timed out; retain uncertainty and do not retry.'}
        fireplay.defer_unknown_upload(fixtures.CODE, 'es', observation, self.root)
        self.assertEqual(fireplay.dispatch(fixtures.CODE, root=self.root)['operation']['id'], 'upload-2')
        box = read_json(self.root / 'state/fireplay' / fixtures.CODE / 'return-1.json')
        self.assertEqual(box['operations']['upload-1']['state'], 'unknown')
        self.assertNotIn('import-1', box['operations'])

    def test_all_deferred_does_not_claim_acceptance_or_dispatch_empty_binding(self):
        self.returned_setup()
        for locale in ('es', 'ko'):
            fireplay.dispatch(fixtures.CODE, True, self.root)
            fireplay.defer_unknown_upload(fixtures.CODE, locale, self.decision(), self.root)
        result = fireplay.dispatch(fixtures.CODE, True, self.root)
        self.assertEqual(result['state'], 'deferred_uploads')
        self.assertNotIn('operation', result)
        self.assertEqual(result['pending_locales'], ['es', 'ko'])
