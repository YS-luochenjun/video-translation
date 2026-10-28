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
