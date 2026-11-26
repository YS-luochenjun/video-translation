"""A no-retry decision must not duplicate or erase an uncertain upload."""
import unittest
from unittest.mock import patch
import test_fireplay as fixtures
from video_localizer import fireplay, fireplay_revision, fireplay_submission
from video_localizer.common import WorkflowError, file_hash, read_json, utc_now, write_json


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
        verify_package = fireplay._verify_frozen_package

        def verify_with_deferred_hold(code, record, package, root, hashes):
            if package['locale'] == 'es':
                raise WorkflowError('Quality hold blocks the deferred upload')
            return verify_package(code, record, package, root, hashes)

        with patch.object(fireplay, '_verify_frozen_package', side_effect=verify_with_deferred_hold) as verifier:
            binding = fireplay.dispatch(fixtures.CODE, True, self.root)['operation']
        self.assertEqual([call.args[2]['locale'] for call in verifier.call_args_list], ['ko'])
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

    def test_repair_expired_untransferred_presign_preserves_bound_locale(self):
        self.returned_setup()
        outbox_path = self.root / 'state/fireplay' / fixtures.CODE / 'return-1.json'
        old = read_json(outbox_path)
        original, other = old['packages']
        observation = self.root / 'presign-observation.json'
        proof = self.root / 'presign-lookup.json'
        write_json(observation, {
            'rejected_sha256': original['sha256'], 'prior_presign_resource_id': fixtures.RID,
            'transport_observation': 'Presign issued. File PUT did not occur, and no material import or binding occurred.'})
        operation = {'id': 'upload-1', 'tool': 'material_r2_presign_upload', 'state': 'unknown'}
        prior_binding = {'state': 'verified', 'result': {'material_ids': [fixtures.MID]}}
        old.update(state='returned', pending_locales=['es'], operations={
            'upload-1': operation, 'verify-2': {'state': 'verified'}, 'bind': prior_binding},
            deferred_uploads={'es': {'operation_id': 'upload-1', 'video_sha256': original['sha256'],
                                     'authority': {'evidence': {'path': observation.name, 'sha256': file_hash(observation)}}}})
        write_json(outbox_path, old)
        digest = file_hash(outbox_path)
        replacement = {**original, 'sha256': 'b' * 64}
        value = {'packages': [replacement]}
        grant = {**self.decision(), 'reason': 'Repair exact held version', 'previous_outbox_sha256': digest}
        check = {'presign_denial': {'Code': 'ExpiredRequest'}, 'head_checks': [
            {'resource_id': fixtures.RID, 'transport_exit': 0, 'public_head_status': 200}]}
        write_json(proof, check)
        grant['untransferred_presign'] = {'path': proof.name, 'sha256': file_hash(proof)}
        with self.assertRaisesRegex(WorkflowError, 'absent object'):
            fireplay_revision.return_revision(outbox_path, old, value, grant, self.root)
        self.assertEqual(file_hash(outbox_path), digest)
        check['head_checks'][0]['public_head_status'] = 404
        write_json(proof, check)
        grant['untransferred_presign']['sha256'] = file_hash(proof)
        with patch('video_localizer.quality_holds.active', return_value=True):
            result = fireplay_revision.return_revision(outbox_path, old, value, grant, self.root)
        self.assertEqual(result['packages'], [replacement, other])
        self.assertEqual(result['operations'], {'verify-2': {'state': 'verified'}})
        self.assertEqual(result['binding_history'], [prior_binding])
        self.assertEqual(read_json(self.root / result['revision_history'][0]['prior_outbox']), old)

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
