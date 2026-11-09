"""Completed requirements can continue only genuine, explicitly requested repairs."""
import tempfile
import unittest
from pathlib import Path

from video_localizer.common import file_hash, write_json
from video_localizer.fireplay_revision import completed_repair_pending


class CompletedRepairTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.folder = self.root / 'state/fireplay/repair'
        self.previous = {'videos': [{'index': 1, 'targets': ['en', 'es'],
                                    'source': {'sha256': 'a' * 64}, 'members': ['repair-en', 'repair-es']}]}
        self.box = {'state': 'returned', 'operations': {'bind': {'state': 'verified'}},
                    'packages': [{'video_index': 1, 'locale': language, 'sha256': 'b' * 64}
                                 for language in ['en', 'es']]}
        self.path = self.folder / 'return-1.json'
        write_json(self.path, self.box)
        for language in ['en', 'es']:
            run = self.root / 'runs' / ('repair-' + language)
            write_json(run / 'inputs/request.json', {'target_language': language})
            final = run / 'outputs/final.mp4'
            final.parent.mkdir(parents=True, exist_ok=True)
            final.write_bytes(('synthetic repaired ' + language).encode())
            write_json(run / 'outputs/completion.json', {
                'state': 'delivered_with_issues', 'decode_passed': True,
                'source_sha256': 'a' * 64, 'video_sha256': file_hash(final)})

    def test_full_new_verified_bytes_are_pending_and_prior_receipts_unchanged(self):
        digest = file_hash(self.path)
        self.assertTrue(completed_repair_pending(self.previous, self.folder, self.root))
        self.assertEqual(file_hash(self.path), digest)

    def test_same_missing_wrong_source_or_changed_bytes_do_not_qualify(self):
        from video_localizer.common import read_json
        path = self.root / 'runs/repair-es/outputs/completion.json'
        valid = read_json(path)
        for key, value in [('video_sha256', 'b' * 64), ('source_sha256', 'c' * 64),
                           ('decode_passed', False), ('video_sha256', 'd' * 64)]:
            write_json(path, {**valid, key: value})
            self.assertFalse(completed_repair_pending(self.previous, self.folder, self.root))
        path.unlink()
        self.assertFalse(completed_repair_pending(self.previous, self.folder, self.root))

    def test_unknown_write_and_incomplete_prior_matrix_do_not_qualify(self):
        self.box['operations']['upload-1'] = {'state': 'unknown'}
        write_json(self.path, self.box)
        self.assertFalse(completed_repair_pending(self.previous, self.folder, self.root))
        self.box['operations'].pop('upload-1')
        self.box['packages'].pop()
        write_json(self.path, self.box)
        self.assertFalse(completed_repair_pending(self.previous, self.folder, self.root))

    def test_explicit_source_subset_preserves_other_settled_deliveries(self):
        second = {'index': 2, 'targets': ['ja'], 'source': {'sha256': 'e' * 64},
                  'members': ['untouched-ja']}
        self.previous['videos'].append(second)
        untouched = self.folder / 'return-2.json'
        write_json(untouched, {'state': 'returned', 'operations': {'bind': {'state': 'verified'}},
                              'packages': [{'video_index': 2, 'locale': 'ja', 'sha256': 'f' * 64}]})
        digest = file_hash(untouched)
        self.assertFalse(completed_repair_pending(self.previous, self.folder, self.root))
        self.assertTrue(completed_repair_pending(self.previous, self.folder, self.root, [1]))
        self.assertFalse(completed_repair_pending(self.previous, self.folder, self.root, [2]))
        for invalid in ([], [True], [1, 1], [3], '1'):
            self.assertFalse(completed_repair_pending(self.previous, self.folder, self.root, invalid))
        self.assertEqual(file_hash(untouched), digest)
