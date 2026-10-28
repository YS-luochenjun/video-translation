"""A timeout may retry file transport, without losing old uncertainty or re-importing."""
import unittest
import test_fireplay as fixtures
from video_localizer import fireplay, fireplay_retry
from video_localizer.common import WorkflowError, read_json, write_json


class UploadRetryTests(unittest.TestCase):
    setUp = fixtures.FireplayTests.setUp
    register = fixtures.FireplayTests.register
    record = fixtures.FireplayTests.record
    save = fixtures.FireplayTests.save
    downloaded = fixtures.FireplayTests.downloaded
    returned_setup = fixtures.FireplayTests.returned_setup
    verify_upload = fixtures.FireplayTests.verify_upload

    def start(self):
        self.returned_setup()
        self.box = self.root / 'state/fireplay' / fixtures.CODE / 'return-1.json'
        fireplay.dispatch(fixtures.CODE, True, self.root)

    def spec(self, attempt=1):
        evidence = f'work/timeout-{attempt}.json'
        write_json(self.root / evidence, {'error': 'Connector request timed out', 'attempt': attempt})
        return {'timeout_evidence': evidence, 'authority': {
            'authority': 'user', 'authorization_ref': 'synthetic-standing-timeout-retry',
            'source_quote': 'Synthetic authorization to retry actual upload timeouts'}}

    def test_preview_and_retry_preserve_old_unknown_operation_and_frozen_package(self):
        self.start()
        original = read_json(self.box)
        spec = self.spec()
        self.assertEqual(fireplay_retry.retry_upload(fixtures.CODE, 'es', spec, root=self.root)['state'], 'preview')
        self.assertEqual(read_json(self.box), original)
        fireplay_retry.retry_upload(fixtures.CODE, 'es', spec, True, self.root)
        saved = read_json(self.box)
        self.assertEqual(saved['packages'], original['packages'])
        self.assertEqual(saved['upload_attempts']['upload-1'][0]['previous_operation'], original['operations']['upload-1'])
        operation = fireplay.dispatch(fixtures.CODE, True, self.root)['operation']
        self.assertEqual(operation['attempt'], 2)
        self.assertEqual(fireplay.dispatch(fixtures.CODE, True, self.root)['state'], 'needs_reconciliation')
        self.verify_upload('upload-1')
        self.assertEqual(fireplay.dispatch(fixtures.CODE, True, self.root)['operation']['id'], 'import-1')

    def test_new_attempt_needs_its_own_timeout_and_is_bounded(self):
        self.start()
        for attempt in [1, 2]:
            fireplay_retry.retry_upload(fixtures.CODE, 'es', self.spec(attempt), True, self.root)
            fireplay.dispatch(fixtures.CODE, True, self.root)
            if attempt == 1:
                with self.assertRaisesRegex(WorkflowError, 'new timeout observation'):
                    fireplay_retry.retry_upload(fixtures.CODE, 'es', self.spec(attempt), True, self.root)
        with self.assertRaisesRegex(WorkflowError, 'retry limit'):
            fireplay_retry.retry_upload(fixtures.CODE, 'es', self.spec(3), True, self.root)

    def test_known_upload_or_import_cannot_be_reuploaded(self):
        self.start()
        self.verify_upload('upload-1')
        with self.assertRaisesRegex(WorkflowError, 'Only an unknown upload'):
            fireplay_retry.retry_upload(fixtures.CODE, 'es', self.spec(), True, self.root)

    def test_deferred_upload_resumes_and_binding_clears_only_completed_gap(self):
        self.start()
        box = read_json(self.box)
        box['packages'] = box['packages'][:1]
        box['pending_locales'] = ['ko']
        write_json(self.box, box)
        fireplay.defer_unknown_upload(fixtures.CODE, 'es', {
            'authority': 'agent', 'authorization_ref': 'synthetic-timeout', 'source_quote': 'Observed timeout'}, self.root)
        fireplay_retry.retry_upload(fixtures.CODE, 'es', self.spec(), True, self.root)
        self.assertNotIn('es', read_json(self.box)['deferred_uploads'])
        fixtures.FireplayTests.complete_partial_locale(self, 1, 'es', fixtures.MID, [fixtures.MID])
        self.assertEqual(read_json(self.box)['pending_locales'], ['ko'])

    def test_plain_unknown_without_timeout_evidence_cannot_retry(self):
        self.start()
        spec = self.spec()
        write_json(self.root / spec['timeout_evidence'], {'state': 'still uploading'})
        with self.assertRaisesRegex(WorkflowError, 'actual timeout observation'):
            fireplay_retry.retry_upload(fixtures.CODE, 'es', spec, True, self.root)
