import copy
import tempfile
import unittest
from pathlib import Path

from video_localizer.common import WorkflowError, file_hash, read_json, write_json
from video_localizer.fireplay_locale_revision import accept, extend_batch


class FundedLocaleAdditionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / 'state/fireplay/REQ'
        source = self.root / 'runs/REQ-01/inputs/source.mp4'
        source.parent.mkdir(parents=True)
        source.write_bytes(b'unchanged original source fixture')
        self.sha = file_hash(source)
        brief = {'id': 'requirement', 'code': 'REQ', 'deptId': 'dept', 'title': 'Translate',
                 'description': 'Full advertisement', 'refText': 'https://youtu.be/abcdefghijk',
                 'locales': ['es', 'ja']}
        video = {'index': 1, 'source_url': brief['refText'],
                 'source': {'path': 'runs/REQ-01/inputs/source.mp4', 'sha256': self.sha},
                 'targets': ['es', 'ja'], 'members': ['REQ-01', 'REQ-02'], 'pilot': 'REQ-01',
                 'chat': {'threadId': 'same-owner', 'state': 'ready'}}
        self.old = {'requirement_id': 'requirement', 'content_version': 'old-version',
                    'budget': 'original-budget', 'targets': ['es', 'ja'],
                    'requested_targets': ['es', 'ja'], 'videos': [video],
                    'snapshot': {'brief': brief}, 'chat': {'threadId': 'same-owner'},
                    'revision_history': [{'scope': 'earlier-history'}]}
        write_json(self.folder / 'request.json', self.old)
        after = {**brief, 'locales': ['es', 'ja', 'nl']}
        self.snap = {'content_version': 'new-version', 'brief': after,
                     'row': {'canBindMaterials': True, 'status': 'not_started'}}
        self.sources = [{'source_url': video['source_url'], 'targets': ['es', 'ja', 'nl']}]
        self.grant = {'authority': 'user', 'action': 'accept_funded_locale_addition',
                      'requirement_id': 'requirement', 'previous_content_version': 'old-version',
                      'next_content_version': 'new-version', 'budget_id': 'original-budget',
                      'credit_limit': 120, 'previous_targets': ['es', 'ja'],
                      'targets': ['es', 'ja', 'nl'], 'source_sha256s': [self.sha],
                      'authorization_ref': 'human:append-nl-same-cap',
                      'source_quote': 'Add Dutch within the original 120-credit pool'}
        write_json(self.root / 'work/grant.json', self.grant)
        self.budget = {'id': 'original-budget', 'credit_limit': 120,
                       'budget_basis': {'targets': ['es', 'ja', 'nl']},
                       'reservations': {'unknown': {'state': 'ambiguous', 'reserved_credits': 2}},
                       'authorized_amendments': [{'authorization_ref': self.grant['authorization_ref'],
                                                 'targets': ['es', 'ja', 'nl'],
                                                 'previous_limit': 120, 'new_total_credit_limit': 120}]}
        self.budget_path = self.root / 'state/budgets/original-budget.json'
        write_json(self.budget_path, self.budget)
        self.decision = {'review_locale_addition': True, 'reviewed_content_version': 'old-version',
                         'revision_reason': 'Only appended Dutch, explicitly approved at unchanged cap',
                         'locale_revision_authority': 'work/grant.json'}

    def call(self, old=None, snap=None, sources=None, targets=None):
        return accept(old or self.old, snap or self.snap, sources or self.sources,
                      self.decision, targets or ['es', 'ja', 'nl'], self.folder, self.root)

    def test_preserves_funded_work_and_unknown_costs_without_mutating_request(self):
        result = self.call()
        self.assertEqual(result['targets'], ['es', 'ja', 'nl'])
        self.assertEqual(result['videos'][0]['members'], ['REQ-01', 'REQ-02'])
        self.assertEqual(result['videos'][0]['chat'], self.old['videos'][0]['chat'])
        self.assertEqual(result['budget'], self.old['budget'])
        self.assertEqual(result['chat'], self.old['chat'])
        self.assertEqual(read_json(self.folder / 'request.json'), self.old)
        self.assertEqual(read_json(self.budget_path), self.budget)
        archive = self.root / result['revision_history'][-1]['path']
        self.assertEqual(read_json(archive), self.old)

    def test_platform_text_is_not_user_authority(self):
        self.grant['authority'] = 'platform'
        write_json(self.root / 'work/grant.json', self.grant)
        with self.assertRaises(WorkflowError):
            self.call()
        self.assertFalse((self.folder / 'revisions').exists())

    def test_native_sorted_budget_targets_do_not_reorder_existing_run_slots(self):
        budget = copy.deepcopy(self.budget)
        budget['budget_basis']['targets'] = ['es', 'ja', 'nl']
        # Native budget canonicalization sorts; production keeps the original run order.
        old = copy.deepcopy(self.old)
        old['targets'] = old['videos'][0]['targets'] = ['ja', 'es']
        grant = copy.deepcopy(self.grant)
        grant['previous_targets'] = ['ja', 'es']
        grant['targets'] = ['ja', 'es', 'nl']
        write_json(self.root / 'work/grant.json', grant)
        write_json(self.budget_path, budget)
        sources = [{**self.sources[0], 'targets': ['ja', 'es', 'nl']}]
        result = self.call(old=old, sources=sources, targets=['ja', 'es', 'nl'])
        self.assertEqual(result['targets'], ['ja', 'es', 'nl'])
        self.assertEqual(result['videos'][0]['members'], ['REQ-01', 'REQ-02'])

    def test_requires_same_cap_native_budget_amendment(self):
        for changed in [[], [{**self.budget['authorized_amendments'][0], 'previous_limit': 60}],
                        [{**self.budget['authorized_amendments'][0], 'authorization_ref': 'not-user-grant'}]]:
            budget = {**self.budget, 'authorized_amendments': changed}
            write_json(self.budget_path, budget)
            with self.subTest(changed=changed), self.assertRaises(WorkflowError):
                self.call()
        self.assertEqual(read_json(self.folder / 'request.json'), self.old)

    def test_rejects_mixed_business_edits_and_changed_source(self):
        for key, value in [('description', 'Narration only'), ('refText', 'https://youtu.be/other-video'),
                           ('quantity', 2)]:
            snap = copy.deepcopy(self.snap)
            snap['brief'][key] = value
            with self.subTest(field=key), self.assertRaises(WorkflowError):
                self.call(snap=snap)
        source = self.root / self.old['videos'][0]['source']['path']
        source.write_bytes(b'different source')
        with self.assertRaises(WorkflowError):
            self.call()

    def test_rejects_reordering_removal_wrong_version_and_existing_returns(self):
        for targets in [['ja', 'es', 'nl'], ['es', 'nl']]:
            with self.subTest(targets=targets), self.assertRaises(WorkflowError):
                self.call(targets=targets)
        old = {**self.old, 'content_version': 'unreviewed-version'}
        with self.assertRaises(WorkflowError):
            self.call(old=old)
        write_json(self.folder / 'return-1.json', {'state': 'unknown'})
        with self.assertRaises(WorkflowError):
            self.call()

    def test_batch_addition_retains_original_pilot_state_members_and_cost_limit(self):
        record = self.call()
        batch = {'request_budget': 'original-budget', 'source_sha256': self.sha,
                 'targets': ['es', 'ja'], 'members': ['REQ-01', 'REQ-02'], 'pilot': 'REQ-01',
                 'credit_limit': 120, 'state': 'pilot_pending', 'pilot_review': {'decision': 'revise'}}
        result = extend_batch(record, record['videos'][0], batch,
                              ['REQ-01', 'REQ-02', 'REQ-03'], self.root)
        self.assertEqual(result['members'], ['REQ-01', 'REQ-02', 'REQ-03'])
        for key in ['pilot', 'pilot_review', 'state', 'credit_limit', 'request_budget']:
            self.assertEqual(result[key], batch[key])
        self.assertNotIn('locale_revision_history', batch)
        for changed in [{'request_budget': 'new-budget'}, {'credit_limit': 180},
                        {'members': ['REQ-01', 'other-run']}]:
            with self.subTest(changed=changed), self.assertRaises(WorkflowError):
                extend_batch(record, record['videos'][0], {**batch, **changed},
                             ['REQ-01', 'REQ-02', 'REQ-03'], self.root)
        self.grant['targets'] = ['es', 'ja', 'ru']
        write_json(self.root / 'work/grant.json', self.grant)
        with self.assertRaises(WorkflowError):
            extend_batch(record, record['videos'][0], batch,
                         ['REQ-01', 'REQ-02', 'REQ-03'], self.root)
