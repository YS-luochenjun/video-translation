import copy
import unittest

import test_fireplay as fixtures
from video_localizer import fireplay
from video_localizer.common import WorkflowError, read_json, write_json
from video_localizer.fireplay_materials import upload_metadata, verify_tags


class VideoUploadMetadataTests(unittest.TestCase):
    def setUp(self):
        self.defaults = read_json(fixtures.PROJECT / 'config/fireplay-intake.json')
        self.record = {'code': fixtures.CODE}
        self.spec = {'material_metadata': {'category': 'GAME', 'pid': '07',
                                          'evidence_ref': 'synthetic verified mapping'}}
        self.publication = {'policy': self.defaults['publication'], 'product_tag': 'Candy Crush'}
        self.attribution = {'designer_dids': 'D288+D299', 'creation_type': 'derivative'}

    def metadata(self, source_name=None):
        return upload_metadata(self.record, self.spec, self.defaults, self.publication,
                               self.attribution, source_name or fixtures.CODE, 'es')

    def test_title_and_english_tags_preserve_all_designers(self):
        result = self.metadata(fixtures.CODE + '-2')
        self.assertEqual(result['display_name'], f'es GAME 07 D288+D299 {fixtures.CODE}-2')
        self.assertEqual(result['tags'], ['es', 'Candy Crush', fixtures.CODE, 'derivative'])

    def test_verified_user_ids_require_actual_did_mapping(self):
        self.attribution = {'designer_ids': ['user-one', 'user-two'], 'creation_type': 'derivative'}
        result = self.metadata()
        self.assertNotIn('user-one', result['display_name'])
        self.assertNotIn('user-two', result['display_name'])
        self.assertIn('derivative', result['tags'])
        self.spec['material_metadata']['designer_did_map'] = {'user-one': 'D288', 'user-two': 'D299'}
        self.assertIn(' D288+D299 ', self.metadata()['display_name'])
        self.spec['material_metadata']['designer_did_map']['user-one'] = 'user-one'
        self.assertNotIn('user-one', self.metadata()['display_name'])

    def test_actual_unassigned_material_omits_did(self):
        self.attribution = {'unassigned': True}
        self.assertEqual(self.metadata()['display_name'], f'es GAME 07 {fixtures.CODE}')
        self.assertNotIn('derivative', self.metadata()['tags'])

    def test_missing_metadata_is_omitted_without_blocking_upload(self):
        for field in ('category', 'pid', 'evidence_ref'):
            with self.subTest(field=field):
                spec = copy.deepcopy(self.spec)
                del spec['material_metadata'][field]
                result = upload_metadata(self.record, spec, self.defaults, self.publication,
                                         self.attribution, fixtures.CODE, 'es')
                self.assertIn('es', result['display_name'])
                if field == 'category':
                    self.assertNotIn(' GAME ', f' {result["display_name"]} ')
                elif field == 'pid':
                    self.assertNotIn(' 07 ', f' {result["display_name"]} ')
                else:
                    self.assertIn('GAME', result['display_name'])
                    self.assertIn('07', result['display_name'])

    def test_missing_product_tag_is_omitted_without_blocking_upload(self):
        publication = {'policy': self.defaults['publication'], 'product_tag': ''}
        result = upload_metadata(self.record, self.spec, self.defaults, publication,
                                 self.attribution, fixtures.CODE, 'es')
        self.assertEqual(result['tags'], ['es', fixtures.CODE, 'derivative'])

    def test_unusable_optional_product_tag_is_omitted(self):
        for product in ('糖果消除', 'Not A Product Tag', 'https://example.invalid'):
            with self.subTest(product=product):
                self.publication['product_tag'] = product
                self.assertEqual(self.metadata()['tags'], ['es', fixtures.CODE, 'derivative'])

    def test_readback_requires_code_and_rejects_non_english_extras(self):
        expected = self.metadata()['tags']
        verify_tags(expected, set(expected) - {'es'} | {'ES'}, 'es', english_only=True)
        for actual in (set(expected) - {fixtures.CODE}, set(expected) | {'二创'}):
            with self.subTest(actual=actual), self.assertRaises(WorkflowError):
                verify_tags(expected, actual, 'es', english_only=True)


class VideoUploadMetadataIntegrationTests(unittest.TestCase):
    setUp = fixtures.FireplayTests.setUp
    register = fixtures.FireplayTests.register
    record = fixtures.FireplayTests.record
    save = fixtures.FireplayTests.save
    downloaded = fixtures.FireplayTests.downloaded
    returned_setup = fixtures.FireplayTests.returned_setup
    verify_upload = fixtures.FireplayTests.verify_upload

    def enable_current_policy(self):
        path = self.root / 'config/fireplay-intake.json'
        write_json(path, read_json(fixtures.PROJECT / 'config/fireplay-intake.json'))

    def test_existing_outbox_survives_policy_change_without_metadata_rewrite(self):
        spec = self.returned_setup()
        path = self.root / 'state/fireplay' / fixtures.CODE / 'return-1.json'
        fireplay.dispatch(fixtures.CODE, True, self.root)
        frozen = read_json(path)
        self.enable_current_policy()
        self.assertEqual(fireplay.prepare_return(fixtures.CODE, spec, self.root), frozen)

    def test_unstarted_batch_allows_missing_mapping_before_any_write(self):
        spec = self.returned_setup()
        self.enable_current_policy()
        spec['material_metadata'] = {}
        spec['product_tag'] = '没有可核验的英文产品名'
        result = fireplay.prepare_return(fixtures.CODE, spec, self.root)
        self.assertEqual(result['packages'][0]['name'], f'es {fixtures.CODE}')
        self.assertEqual(result['packages'][0]['tags'], ['es', fixtures.CODE])
        self.assertEqual(fireplay.dispatch(fixtures.CODE, root=self.root)['operation']['id'], 'upload-1')

    def test_new_batch_dispatches_current_title_and_requirement_tag(self):
        spec = self.returned_setup()
        self.enable_current_policy()
        spec['material_metadata'] = {'category': 'GAME', 'pid': '07', 'evidence_ref': 'synthetic mapping'}
        result = fireplay.prepare_return(fixtures.CODE, spec, self.root)
        self.assertEqual(result['packages'][0]['name'], f'es GAME 07 {fixtures.CODE}')
        self.assertEqual(result['packages'][0]['tags'], ['es', 'crush', fixtures.CODE])
        operation = fireplay.dispatch(fixtures.CODE, root=self.root)['operation']
        self.assertEqual(operation['id'], 'upload-1')
        fireplay.dispatch(fixtures.CODE, True, self.root)
        self.verify_upload('upload-1')
        operation = fireplay.dispatch(fixtures.CODE, True, self.root)['operation']
        self.assertEqual(operation['arguments']['items'][0]['name'], result['packages'][0]['name'])
        self.assertEqual(operation['arguments']['items'][0]['tags'], ['es', 'crush', fixtures.CODE])
        fireplay.receipt(fixtures.CODE, 'import-1', {'response': {'material_id': fixtures.MID}}, self.root)
        fireplay.dispatch(fixtures.CODE, True, self.root)
        material = {'id': fixtures.MID, 'name': result['packages'][0]['display_name'],
                    'isPublic': False, 'sharedDeptId': 'test', 'tags': ['es', 'crush', fixtures.CODE]}
        for tags in (['es', 'crush'], ['es', 'crush', fixtures.CODE, '二创']):
            with self.subTest(tags=tags), self.assertRaises(WorkflowError):
                fireplay.receipt(fixtures.CODE, 'verify-1',
                                 {'response': {'material': {**material, 'tags': tags}}}, self.root)
        self.assertEqual(fireplay.receipt(fixtures.CODE, 'verify-1',
                         {'response': {'material': material}}, self.root)['state'], 'verified')
