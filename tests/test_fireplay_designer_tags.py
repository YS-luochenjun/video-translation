"""Derivative attribution must reach both platform naming and visible tags."""
import unittest
import test_fireplay as fixtures
from video_localizer import fireplay, project_storage
from video_localizer.common import read_json, utc_now, WorkflowError


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

    def direct_ids(self, authorized=True, **options):
        spec = self.returned_setup(**options)
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

    def ready_attribution_batch(self):
        box = self.direct_ids()
        material_ids = [fixtures.MID, fixtures.RID]
        for number, resource in enumerate([fixtures.RESOURCE, fixtures.THREAD], 1):
            fireplay.dispatch(fixtures.CODE, True, self.root, package_index=number)
            fireplay.receipt(fixtures.CODE, f'upload-{number}', {'response': {
                'publicUrl': f'https://example.com/video-{number}.mp4', 'resourceId': resource}}, self.root)
        imported = fireplay.dispatch_import_batch(fixtures.CODE, True, self.root)['operation']
        fireplay.receipt(fixtures.CODE, imported['id'], {'response': {'results': [
            {'item_index': slot, 'success': True, 'material_imported': True, 'material_id': material_id}
            for slot, material_id in enumerate(material_ids)]}}, self.root)
        details = [{'material': {'id': material_id, 'name': package['display_name'], 'designerIds': ['test'],
                                 'creationType': 'derivative', 'isPublic': False,
                                 'sharedDeptId': 'test', 'tags': package['tags']}}
                   for material_id, package in zip(material_ids, box['packages'])]
        return material_ids, details

    def test_default_attribution_batches_matching_assets_and_reuses_readback(self):
        material_ids, details = self.ready_attribution_batch()
        path = self.root / 'state/fireplay' / fixtures.CODE / 'return-1.json'
        preview = fireplay.dispatch(fixtures.CODE, root=self.root)
        self.assertEqual(preview['state'], 'preview')
        self.assertNotIn('attribution_batches', read_json(path))
        batch = fireplay.dispatch(fixtures.CODE, True, self.root)['operation']
        self.assertEqual(batch['id'], preview['operation']['id'])
        self.assertEqual(batch['operation_ids'], ['attribute-1', 'attribute-2'])
        self.assertEqual(batch['tool'], 'material_attribution_update')
        self.assertEqual(batch['arguments'], {'material_ids': material_ids, 'designer_ids': ['test'],
                                              'creation_type': 'derivative'})
        result = fireplay.receipt(fixtures.CODE, batch['id'],
                                 {'response': {'success': True, 'updated': material_ids, 'skipped': []},
                                  'verification': list(reversed(details))}, self.root)
        self.assertEqual(result['state'], 'verified')
        operations = read_json(path)['operations']
        self.assertEqual(operations['verify-1']['last_observed_receipt'],
                         operations['verify-2']['last_observed_receipt'])
        bind = fireplay.dispatch(fixtures.CODE, True, self.root)['operation']
        self.assertEqual(bind['id'], 'bind')
        self.assertEqual(bind['arguments']['items'][0]['material_ids'], material_ids)
        fireplay.receipt(fixtures.CODE, 'bind', {'response': {'success': True},
                         'verification': {'serverTime': utc_now(), 'items': [
                             {'id': fixtures.RID, 'materials': [{'id': value} for value in material_ids]}]}},
                         self.root)
        self.assertEqual(len(project_storage.settled_upload_inputs(self.root)), 2)

    def test_partial_attribution_recovers_only_pending_material_without_repeating_write(self):
        material_ids, details = self.ready_attribution_batch()
        batch = fireplay.dispatch(fixtures.CODE, True, self.root)['operation']
        with self.assertRaisesRegex(WorkflowError, 'preview'):
            fireplay.receipt(fixtures.CODE, batch['id'],
                             {'response': {'preview': True, 'updated': material_ids}, 'verification': details},
                             self.root)
        result = fireplay.receipt(fixtures.CODE, batch['id'],
                                 {'response': {'updated': material_ids[1:], 'skipped': material_ids[:1]},
                                  'verification': [{'isError': True}, details[1]]}, self.root)
        self.assertEqual(result['verified'], ['attribute-2'])
        self.assertEqual(result['pending_material_ids'], material_ids[:1])
        pending = fireplay.dispatch(fixtures.CODE, True, self.root)
        self.assertEqual(pending['state'], 'needs_reconciliation')
        self.assertEqual(pending['operation']['id'], batch['id'])
        self.assertEqual(pending['pending_material_ids'], material_ids[:1])
        wrong_designer = {'material': {**details[0]['material'], 'designerIds': ['test', 'another']}}
        result = fireplay.receipt(fixtures.CODE, batch['id'], {'verification': [wrong_designer]}, self.root)
        self.assertEqual(result['pending_material_ids'], material_ids[:1])
        result = fireplay.receipt(fixtures.CODE, batch['id'], {'verification': details[:1]}, self.root)
        self.assertEqual(result['state'], 'verified')
        self.assertEqual(fireplay.dispatch(fixtures.CODE, root=self.root)['operation']['id'], 'bind')

    def test_ready_attribution_batch_proceeds_while_another_upload_is_unknown(self):
        locales = ('es', 'ko', 'fr')
        for view in ('summary', 'brief'):
            self.snap[view]['items'][0].update(locales=list(locales), quantity=len(locales))
        self.direct_ids(locales=locales)
        for number in (1, 2, 3):
            fireplay.dispatch(fixtures.CODE, True, self.root, package_index=number)
        for number, resource in ((2, fixtures.RESOURCE), (3, fixtures.THREAD)):
            fireplay.receipt(fixtures.CODE, f'upload-{number}', {'response': {
                'publicUrl': f'https://example.com/video-{number}.mp4', 'resourceId': resource}}, self.root)
        imported = fireplay.dispatch_import_batch(fixtures.CODE, True, self.root)['operation']
        fireplay.receipt(fixtures.CODE, imported['id'], {'response': {'results': [
            {'item_index': slot, 'success': True, 'material_imported': True, 'material_id': material_id}
            for slot, material_id in enumerate((fixtures.MID, fixtures.RID))]}}, self.root)

        dispatched = fireplay.dispatch(fixtures.CODE, True, self.root)
        self.assertEqual(dispatched['state'], 'dispatch_once')
        self.assertEqual(dispatched['operation']['operation_ids'], ['attribute-2', 'attribute-3'])
        pending = fireplay.dispatch(fixtures.CODE, True, self.root)
        self.assertEqual(pending['state'], 'needs_reconciliation')
        self.assertEqual(pending['operation']['id'], 'upload-1')
