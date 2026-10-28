"""Publisher identity, endcard review and remove-without-replacement contracts."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from video_localizer import common, contracts, demo, knowledge, source_state, workflow
from video_localizer.common import ROOT, WorkflowError, read_json, write_json
from workspace_fixture import copy_project_knowledge


class PublisherMarkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'work/test-tmp')
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)
        (self.run / 'frame.txt').write_text('Synthetic evidence pointer only')
        self.mark = {'id': 't001', 'source_text': 'Apkzonic', 'target_text': '',
                     'text_role': 'publisher_mark', 'publisher_identity': 'apkzonic',
                     'mark_form': 'watermark', 'action': 'model_edit'}
        self.inv = {'text_instances': [self.mark], 'publisher_mark_review': {
            'status': 'reviewed', 'endcard_check': 'no_match',
            'reason': 'Synthetic endcard review', 'evidence': ['frame.txt']}}

    def test_static_mark_retrieves_required_successor_without_optional_slots(self):
        ctx = knowledge.context_for({'target_language': 'en'}, self.inv, ROOT)
        self.assertIn('publisher_watermark', ctx['features'])
        self.assertNotIn('moving_watermark', ctx['features'])
        ids = {e['id'] for e in knowledge.retrieve(ctx, limit=0, root=ROOT)}
        self.assertIn('publisher-watermark-removal-v2', ids)
        self.assertNotIn('moving-watermark-removal-v1', ids)

    def test_same_identity_keeps_separate_watermark_and_endcard_instances(self):
        endcard = {**self.mark, 'id': 't002', 'source_text': 'APKZONIC', 'mark_form': 'endcard_wordmark'}
        self.inv['text_instances'].append(endcard)
        with self.assertRaisesRegex(WorkflowError, 'Endcard match decision'):
            contracts.validate_publisher_marks(self.inv, self.run)
        self.inv['publisher_mark_review']['endcard_check'] = 'matched'
        contracts.validate_publisher_marks(self.inv, self.run)

    def test_missing_endcard_evidence_and_translated_watermark_are_rejected(self):
        self.inv['publisher_mark_review']['evidence'] = []
        with self.assertRaisesRegex(WorkflowError, 'endcard review'):
            contracts.validate_publisher_marks(self.inv, self.run)
        self.inv['publisher_mark_review']['evidence'] = ['frame.txt']
        self.mark['target_text'] = 'Translated publisher'
        with self.assertRaisesRegex(WorkflowError, 'no replacement text'):
            contracts.validate_publisher_marks(self.inv, self.run)

    def test_preserve_needs_explicit_instruction_but_unrelated_brand_is_unchanged(self):
        self.mark.update(action='preserve', target_text='Apkzonic')
        with self.assertRaisesRegex(WorkflowError, 'explicit user instruction'):
            contracts.validate_publisher_marks(self.inv, self.run)
        self.mark['preserve_authorization_ref'] = 'synthetic-explicit-user-exception'
        contracts.validate_publisher_marks(self.inv, self.run)
        contracts.validate_publisher_marks({'text_instances': [{
            'text_role': 'scene_text', 'source_text': 'Product Brand', 'action': 'preserve'}]}, self.run)

    def test_source_reuse_keeps_identity_but_not_removal_or_preserve_decisions(self):
        mark = {**self.mark, 'start': 0, 'end': 1, 'bbox': [0, 0, 10, 10],
                'preserve_authorization_ref': 'original-task-only'}
        neutral = source_state.observations({'source_sha256': 'synthetic-source',
                                            'text_instances': [mark]})
        cached = neutral['text_instances'][0]
        self.assertEqual(cached['publisher_identity'], 'apkzonic')
        self.assertEqual(cached['mark_form'], 'watermark')
        self.assertNotIn('action', cached)
        self.assertNotIn('target_text', cached)
        self.assertNotIn('preserve_authorization_ref', cached)


class PublisherPromptTests(unittest.TestCase):
    def test_full_plan_and_custom_prompt_erase_marks_without_replacing_them(self):
        import shutil
        with tempfile.TemporaryDirectory(dir=ROOT / 'work/test-tmp') as folder:
            root = Path(folder)
            for relative in ['config/workspace.json', 'config/quality.json',
                             'config/profiles/company-default/profile.json']:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, path)
            copy_project_knowledge(ROOT, root)
            with patch.object(common, 'ROOT', root), patch.object(demo, 'ROOT', root), \
                    patch.object(knowledge, 'ROOT', root), patch.object(workflow, 'ROOT', root):
                demo.create_demo('publisher-fixture', 'local_overlay', seconds=2)
                run = root / 'runs/publisher-fixture'
                inv = read_json(run / 'analysis/inventory.json')
                mark = copy.deepcopy(inv['text_instances'][0])
                mark.update(source_text='Synthetic publisher', target_text='', action='model_edit',
                            text_role='publisher_mark', publisher_identity='synthetic-publisher', mark_form='watermark')
                inv['text_instances'] = [mark, inv['text_instances'][-1]]
                inv['publisher_mark_review'] = {'status': 'reviewed', 'endcard_check': 'no_match',
                    'reason': 'Synthetic inventory contract test, not actual watermark detection',
                    'evidence': ['analysis/fixture-provenance.txt']}
                write_json(run / 'analysis/inventory.json', inv)
                workflow.build_plan(run)
                prompt = read_json(run / 'plan.json')['segments'][0]['prompt']
                self.assertIn('ERASE, leave no lettering', prompt)
                self.assertIn('no replacement text or logo', prompt)
                self.assertIn('Preserve this named brand exactly', prompt)
                inv['shots'][0]['model_prompt'] = 'Focused synthetic source-video repair.'
                write_json(run / 'analysis/inventory.json', inv)
                workflow.build_plan(run)
                prompt = read_json(run / 'plan.json')['segments'][0]['prompt']
                self.assertIn('Remove publisher mark', prompt)
                self.assertIn('no replacement text/logo', prompt)
