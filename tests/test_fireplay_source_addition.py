import copy
from pathlib import Path
import tempfile
import unittest

from video_localizer.common import WorkflowError, write_json
from video_localizer.fireplay_revision import append_reviewed_sources


class SourceAdditionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.folder = self.root / 'state/fireplay/TEST'
        self.folder.mkdir(parents=True)
        self.source = {'source_url': 'https://youtu.be/abcdefghijk', 'youtube_video_id': 'abcdefghijk',
                       'index': 1, 'targets': ['ar', 'de']}
        self.added = {'source_url': 'https://youtu.be/lmnopqrstuv', 'youtube_video_id': 'lmnopqrstuv',
                      'index': 2, 'targets': ['ar', 'de']}
        brief = {'title': 'Translate', 'description': self.source['source_url'], 'quantity': 2}
        self.previous = {'requirement_id': 'test-id', 'content_version': 'old-version',
                         'budget': 'original-pool', 'chat': {'state': 'ready'},
                         'videos': [self.source], 'targets': ['ar', 'de'],
                         'snapshot': {'brief': brief, 'row': {'assigneeIds': ['alice', 'bob']}}}
        self.snapshot = {'content_version': 'new-version', 'brief': {**brief, 'quantity': 4,
                         'description': brief['description'] + '\n' + self.added['source_url']},
                         'row': {'id': 'test-id', 'status': 'not_started', 'canBindMaterials': True,
                                 'assigneeIds': ['bob', 'alice']}}
        self.decision = {'review_source_addition': True, 'source_addition_authority': 'user',
                         'reviewed_content_version': 'old-version', 'revision_reason': 'Approved added source',
                         'approved_source_urls': [self.added['source_url']], 'authorization_ref': 'authority.json',
                         'source_quote': 'Include this second source with the same budget', 'keep_credit_limit': 120}
        write_json(self.root / 'authority.json', {'authority': 'user', 'source_quote': self.decision['source_quote'],
                   'requirement_id': 'test-id', 'approved_source_urls': [self.added['source_url']],
                   'budget_id': 'original-pool', 'credit_limit': 120})
        write_json(self.root / 'state/budgets/original-pool.json', {'state': 'open', 'credit_limit': 120})

    def append(self):
        return append_reviewed_sources(self.previous, self.snapshot, [self.source, self.added],
                                       self.decision, ['ar', 'de'], self.folder, self.root)

    def test_derived_quantity_and_reordered_same_assignees(self):
        before = copy.deepcopy(self.previous)
        result = self.append()
        self.assertEqual(len(result['videos']), 2)
        self.assertEqual(result['budget'], 'original-pool')
        self.assertEqual(self.previous, before)

    def test_unrelated_quantity_rejected(self):
        self.snapshot['brief']['quantity'] = 5
        with self.assertRaises(WorkflowError):
            self.append()

    def test_in_progress_preserves_existing_production_and_budget(self):
        self.snapshot['row']['status'] = 'in_progress'
        self.source['members'] = ['existing-run']
        budget = self.root / 'state/budgets/original-pool.json'
        budget_before = budget.read_bytes()
        result = self.append()
        self.assertEqual(result['videos'][0]['members'], ['existing-run'])
        self.assertEqual(result['videos'][0]['source_scope_content_version'], 'old-version')
        self.assertEqual(result['videos'][1]['source_scope_content_version'], 'new-version')
        self.assertEqual(result['chat'], self.previous['chat'])
        self.assertEqual(budget.read_bytes(), budget_before)

    def test_in_progress_with_existing_return_rejected(self):
        self.snapshot['row']['status'] = 'in_progress'
        write_json(self.folder / 'return-1.json', {'state': 'prepared'})
        with self.assertRaises(WorkflowError):
            self.append()

    def test_done_rejected(self):
        self.snapshot['row']['status'] = 'done'
        with self.assertRaises(WorkflowError):
            self.append()

    def test_real_assignee_change_rejected(self):
        self.snapshot['row']['assigneeIds'] = ['alice', 'charlie']
        with self.assertRaises(WorkflowError):
            self.append()
