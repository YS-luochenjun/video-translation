"""Derivative attribution must reach both platform naming and visible tags."""
import unittest
import test_fireplay as fixtures
from video_localizer import fireplay
from video_localizer.common import read_json, WorkflowError


class DesignerTagTests(unittest.TestCase):
    setUp = fixtures.FireplayTests.setUp
    register = fixtures.FireplayTests.register
    record = fixtures.FireplayTests.record
    save = fixtures.FireplayTests.save
    downloaded = fixtures.FireplayTests.downloaded
    returned_setup = fixtures.FireplayTests.returned_setup
    verify_upload = fixtures.FireplayTests.verify_upload

    def derivative(self):
        spec = self.returned_setup()
        (self.root / 'state/fireplay' / fixtures.CODE / 'return-1.json').unlink()
        spec['attribution'] = {'designer_dids': 'D288+D299', 'creation_type': 'derivative',
                               'authorization_ref': 'synthetic-verified-assignee-designers',
                               'source_quote': 'Synthetic attribution fixture; no platform writes'}
        return fireplay.prepare_return(fixtures.CODE, spec, self.root)

    def test_multiple_designers_derivative_marker_and_tag_are_preserved(self):
        box = self.derivative()
        self.assertEqual(box['attribution']['designer_dids'], 'D288+D299')
        for package in box['packages']:
            self.assertEqual(package['name'], package['display_name'] + '_D288+D299_#')
            self.assertEqual(package['tags'], [package['locale'], 'crush', '二创'])
        fireplay.dispatch(fixtures.CODE, True, self.root)
        self.verify_upload('upload-1')
        op = fireplay.dispatch(fixtures.CODE, True, self.root)['operation']
        self.assertEqual(op['arguments']['items'][0]['tags'], ['es', 'crush', '二创'])

    def test_readback_rejects_missing_derivative_tag(self):
        self.derivative()
        fireplay.dispatch(fixtures.CODE, True, self.root)
        self.verify_upload('upload-1')
        fireplay.dispatch(fixtures.CODE, True, self.root)
        fireplay.receipt(fixtures.CODE, 'import-1', {'response': {'material_id': fixtures.MID}}, self.root)
        fireplay.dispatch(fixtures.CODE, True, self.root)
        response = {'material': {'id': fixtures.MID, 'name': fixtures.CODE + '-es',
                                'isPublic': False, 'sharedDeptId': 'test', 'tags': ['es', 'crush']}}
        with self.assertRaisesRegex(WorkflowError, 'missing language or product tags'):
            fireplay.receipt(fixtures.CODE, 'verify-1', {'response': response}, self.root)
        response['material']['tags'].append('二创')
        self.assertEqual(fireplay.receipt(fixtures.CODE, 'verify-1', {'response': response}, self.root)['state'], 'verified')

    def test_unassigned_submission_does_not_gain_derivative_attribution(self):
        self.returned_setup()
        box = read_json(self.root / 'state/fireplay' / fixtures.CODE / 'return-1.json')
        self.assertTrue(box['attribution']['unassigned'])
        self.assertNotIn('二创', box['packages'][0]['tags'])

    def direct_ids(self, authorized=True):
        spec = self.returned_setup()
        (self.root / 'state/fireplay' / fixtures.CODE / 'return-1.json').unlink()
        spec['attribution'] = {'designer_ids': ['test'], 'identity_route': 'verified_user_id',
                               'creation_type': 'derivative', 'authorization_ref': 'synthetic-user-id-route',
                               'source_quote': 'Synthetic explicit user choice of verified assignee ID'}
        if authorized:
            spec['attribution']['identity_authorization_ref'] = 'synthetic-explicit-user-choice'
        return fireplay.prepare_return(fixtures.CODE, spec, self.root)

    def test_verified_user_id_route_requires_separate_explicit_authority(self):
        with self.assertRaisesRegex(WorkflowError, 'explicit user authorization'):
            self.direct_ids(False)

    def test_prepared_batch_cannot_silently_change_attribution(self):
        spec = self.returned_setup()
        box = read_json(self.root / 'state/fireplay' / fixtures.CODE / 'return-1.json')
        spec['attribution'] = {'designer_ids': ['test'], 'identity_route': 'verified_user_id',
                               'creation_type': 'unspecified', 'authorization_ref': 'changed-attribution',
                               'identity_authorization_ref': 'synthetic-explicit-user-choice',
                               'source_quote': 'Synthetic assignment change; same display name and tags'}
        with self.assertRaisesRegex(WorkflowError, 'different attribution'):
            fireplay.prepare_return(fixtures.CODE, spec, self.root)
        self.assertEqual(read_json(self.root / 'state/fireplay' / fixtures.CODE / 'return-1.json'), box)

    def test_current_upload_snake_case_receipt_preserves_real_identity(self):
        self.returned_setup()
        fireplay.dispatch(fixtures.CODE, True, self.root)
        result = fireplay.receipt(fixtures.CODE, 'upload-1', {'response': {
            'success': True, 'public_url': 'https://example.com/video.mp4',
            'resource_id': fixtures.RESOURCE}}, self.root)
        self.assertEqual(result['result']['resourceId'], fixtures.RESOURCE)

    def test_direct_id_write_is_journaled_and_needs_attribution_readback(self):
        box = self.direct_ids()
        self.assertEqual(box['packages'][0]['name'], box['packages'][0]['display_name'])
        self.assertIn('二创', box['packages'][0]['tags'])
        fireplay.dispatch(fixtures.CODE, True, self.root)
        self.verify_upload('upload-1')
        fireplay.dispatch(fixtures.CODE, True, self.root)
        fireplay.receipt(fixtures.CODE, 'import-1', {'response': {'material_id': fixtures.MID}}, self.root)
        op = fireplay.dispatch(fixtures.CODE, True, self.root)['operation']
        self.assertEqual(op['tool'], 'material_attribution_update')
        self.assertNotIn('confirmed', op['arguments'])
        self.assertEqual(fireplay.dispatch(fixtures.CODE, True, self.root)['state'], 'needs_reconciliation')
        verification = {'material': {'id': fixtures.MID, 'designerIds': [], 'creationType': 'derivative'}}
        with self.assertRaisesRegex(WorkflowError, 'designer read-back'):
            fireplay.receipt(fixtures.CODE, 'attribute-1', {'response': {'success': True},
                             'verification': verification}, self.root)
        verification['material']['designerIds'] = ['test']
        with self.assertRaisesRegex(WorkflowError, 'preview'):
            fireplay.receipt(fixtures.CODE, 'attribute-1', {'response': {'isPreview': True},
                             'verification': verification}, self.root)
        fireplay.receipt(fixtures.CODE, 'attribute-1', {'response': {'success': True},
                         'verification': verification}, self.root)
        self.assertEqual(fireplay.dispatch(fixtures.CODE, True, self.root)['operation']['id'], 'verify-1')
        response = {'material': {**verification['material'], 'name': box['packages'][0]['display_name'],
                                'isPublic': False, 'sharedDeptId': 'test', 'tags': ['es', 'crush', '二创']}}
        response['material']['creationType'] = 'original'
        with self.assertRaisesRegex(WorkflowError, 'lost verified designer attribution'):
            fireplay.receipt(fixtures.CODE, 'verify-1', {'response': response}, self.root)
