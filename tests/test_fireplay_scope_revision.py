import copy
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_fireplay import CODE, RID, THREAD, fixture
from video_localizer import fireplay
from video_localizer.common import WorkflowError, file_hash, read_json, write_json
from video_localizer.fireplay_scope_revision import accept_narration_only


class FundedNarrationRevisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(Path(__file__).resolve().parents[1] / 'config', self.root / 'config',
                        ignore=shutil.ignore_patterns('*.local.json'))
        self.dns = patch('video_localizer.kie.socket.getaddrinfo',
                         return_value=[(2, 1, 6, '', ('93.184.216.34', 443))])
        self.dns.start()
        self.addCleanup(self.dns.stop)
        self.raw = fixture()
        fireplay.register(CODE, self.raw, root=self.root)
        self.folder = self.root / 'state/fireplay' / CODE
        self.old = read_json(self.folder / 'request.json')
        self.old['budget'] = 'original-budget'
        self.old['videos'][0].update(source={'sha256': 'a' * 64, 'path': 'runs/pilot/inputs/source.mp4'},
                                      chat={'threadId': THREAD, 'hostId': 'local', 'state': 'ready'},
                                      members=['pilot-es', 'pilot-ko'])
        write_json(self.folder / 'request.json', self.old)
        self.budget_path = self.root / 'state/budgets/original-budget.json'
        write_json(self.budget_path, {'credit_limit': 120, 'reservations': {'unknown': {'state': 'ambiguous', 'estimate': 2}}})
        self.raw['brief']['items'][0]['description'] = '只翻译文案的口播，' + self.raw['brief']['items'][0]['description']
        self.snap = fireplay.snapshot(CODE, self.raw)
        self.decision = {'review_scope_narrowing': True, 'scope': 'ad_narration_only',
                         'authorization_ref': 'human:exact-scope-review', 'source_quote': 'Apply restricted narrowing',
                         'reviewed_content_version': self.old['content_version'], 'revision_reason': 'Exact reviewed narrowing',
                         'scope_revision_authority': 'work/authority.json'}
        self.authority = {'authority': 'user', 'action': 'accept_funded_narration_only_revision',
                          'requirement_id': RID, 'previous_content_version': self.old['content_version'],
                          'next_content_version': self.snap['content_version'], 'budget_id': 'original-budget',
                          'credit_limit': 120, 'targets': self.old['targets'], 'source_sha256s': ['a' * 64],
                          'authorization_ref': 'human:exact-scope-review', 'source_quote': 'Apply the restricted revision and continue'}
        write_json(self.root / 'work/authority.json', self.authority)

    def accept(self, old=None, snap=None, decision=None, targets=None):
        return accept_narration_only(old or self.old, snap or self.snap, copy.deepcopy(self.old['videos']),
                                     decision or self.decision, targets or self.old['targets'], self.folder, self.root)

    def test_register_accepts_exact_human_authorized_narrowing_without_reset(self):
        budget_hash = file_hash(self.budget_path)
        result = fireplay.register(CODE, self.raw, self.decision, self.root)
        current = read_json(self.folder / 'request.json')
        self.assertEqual(current['content_version'], self.snap['content_version'])
        self.assertEqual(current['budget'], self.old['budget'])
        self.assertEqual(current['videos'], self.old['videos'])
        self.assertEqual(file_hash(self.budget_path), budget_hash)
        self.assertEqual(current['production_scope']['speech'], 'advertising_narration_only')
        self.assertEqual(read_json(self.root / current['revision_history'][-1]['path']), self.old)
        self.assertFalse(result['blockers'])

    def test_other_scope_changes_and_missing_authority_remain_blocked(self):
        for field, value in [('quantity', 3), ('title', 'Different product'), ('description', 'Different task')]:
            snap = copy.deepcopy(self.snap)
            snap['brief'][field] = value
            with self.subTest(field=field), self.assertRaises(WorkflowError):
                self.accept(snap=snap)
        with self.assertRaises(WorkflowError):
            self.accept(targets=self.old['targets'] + ['ja'])
        bad = copy.deepcopy(self.authority)
        bad['credit_limit'] = 180
        write_json(self.root / 'work/authority.json', bad)
        with self.assertRaises(WorkflowError):
            self.accept()
        self.assertEqual(read_json(self.folder / 'request.json'), self.old)
        self.assertFalse((self.folder / 'revisions').exists())

    def test_prior_returns_and_wrong_version_cannot_be_reinterpreted(self):
        decision = {**self.decision, 'reviewed_content_version': 'wrong'}
        with self.assertRaises(WorkflowError):
            self.accept(decision=decision)
        write_json(self.folder / 'return-1.json', {'state': 'unknown'})
        with self.assertRaises(WorkflowError):
            self.accept()
        self.assertEqual(read_json(self.folder / 'request.json'), self.old)
