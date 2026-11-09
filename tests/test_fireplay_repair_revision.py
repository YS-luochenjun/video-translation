"""Explicit repaired deliveries must preserve settled platform history."""
import copy
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_fireplay as fixtures
from video_localizer import bundles, fireplay
from video_localizer.common import WorkflowError, file_hash, read_json, write_json


class RepairReturnTests(unittest.TestCase):
    def setUp(self):
        self.fx = fixtures.FireplayTests(methodName='runTest')
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.root = self.fx.root
        self.spec = self.fx.returned_setup()
        self.path = self.root / 'state/fireplay' / fixtures.CODE / 'return-1.json'
        self.old = read_json(self.path)
        self.old.update(state='returned', pending_locales=[])
        self.old['operations'] = {'bind': {'state': 'verified', 'result': {'material_ids': [fixtures.MID]}}}
        write_json(self.path, self.old)
        self.digest = file_hash(self.path)
        revised = []
        for item in self.spec['packages']:
            lang = item['locale']
            movie = self.root / f'work/{lang}-repaired.mp4'
            movie.write_bytes(('repaired synthetic ' + lang).encode())
            quality = self.root / f'work/{lang}-repaired-quality.json'
            write_json(quality, {'decision': 'pass', 'video_sha256': file_hash(movie)})
            package = self.root / f'outputs/repaired/{lang}'
            bundles.create(package, 'delivery', file_hash(movie),
                           {'final.mp4': movie, 'payload/outputs/quality.json': quality}, {
                               'status': 'delivered', 'technical_decision': 'pass',
                               'source_sha256': self.fx.record()['videos'][0]['source']['sha256'],
                               'video_sha256': file_hash(movie), 'target_language': lang})
            revised.append({**item, 'package': str(package.relative_to(self.root))})
        self.new = {**self.spec, 'packages': revised, 'repair_revision': {
            'authority': 'user', 'authorization_ref': 'synthetic:repair-request',
            'source_quote': 'Synthetic offline repair instruction', 'reason': 'Repair rejected CTA',
            'previous_outbox_sha256': self.digest}}

    def test_reviewed_repair_archives_receipts_and_starts_new_operations(self):
        new = fireplay.prepare_return(fixtures.CODE, self.new, self.root)
        self.assertEqual(new['operations'], {})
        self.assertEqual(new['state'], 'ready')
        prior = new['revision_history'][-1]
        archive = self.root / prior['prior_outbox']
        self.assertEqual(file_hash(archive), self.digest)
        self.assertEqual(read_json(archive), self.old)
        self.assertEqual(fireplay.prepare_return(fixtures.CODE, self.new, self.root), new)

    def test_stale_grant_unknown_operation_and_missing_locale_do_not_mutate(self):
        stale = copy.deepcopy(self.new)
        stale['repair_revision']['previous_outbox_sha256'] = '0' * 64
        with self.assertRaisesRegex(WorkflowError, 'exact previous'):
            fireplay.prepare_return(fixtures.CODE, stale, self.root)
        self.assertEqual(file_hash(self.path), self.digest)
        partial = {**self.new, 'partial': True, 'packages': self.new['packages'][:1]}
        with self.assertRaisesRegex(WorkflowError, 'retain every'):
            fireplay.prepare_return(fixtures.CODE, partial, self.root)
        self.assertEqual(file_hash(self.path), self.digest)
        unknown = copy.deepcopy(self.old)
        unknown['operations']['upload-1'] = {'state': 'unknown'}
        write_json(self.path, unknown)
        unknown_digest = file_hash(self.path)
        grant = copy.deepcopy(self.new)
        grant['repair_revision']['previous_outbox_sha256'] = unknown_digest
        with self.assertRaisesRegex(WorkflowError, 'Settle all'):
            fireplay.prepare_return(fixtures.CODE, grant, self.root)
        self.assertEqual(file_hash(self.path), unknown_digest)

    def test_unchanged_reencoded_selection_cannot_replace_other_locale(self):
        mixed = copy.deepcopy(self.new)
        mixed['packages'][0] = self.spec['packages'][0]
        with self.assertRaisesRegex(WorkflowError, 'new reviewed video bytes'):
            fireplay.prepare_return(fixtures.CODE, mixed, self.root)
        self.assertEqual(file_hash(self.path), self.digest)

    def test_reviewed_unbound_import_can_be_repaired_without_binding_rejected_video(self):
        old = copy.deepcopy(self.old)
        old['state'] = 'ready'
        old['operations'] = {f'{phase}-{i}': {'state': 'verified'}
                             for i, _ in enumerate(old['packages'], 1)
                             for phase in ('upload', 'import', 'attribute', 'verify')}
        write_json(self.path, old)
        grant = copy.deepcopy(self.new)
        grant['repair_revision'].update(previous_outbox_sha256=file_hash(self.path),
                                        unbound_reviewed_repair=True)
        new = fireplay.prepare_return(fixtures.CODE, grant, self.root)
        archive = self.root / new['revision_history'][-1]['prior_outbox']
        self.assertEqual(read_json(archive), old)
        self.assertEqual(new['operations'], {})

    def test_unbound_repair_rejects_unknown_import_or_dispatched_binding(self):
        for phase in ('import-1', 'bind'):
            old = copy.deepcopy(self.old)
            old['state'] = 'ready'
            old['operations'] = {f'{p}-{i}': {'state': 'verified'}
                                 for i, _ in enumerate(old['packages'], 1)
                                 for p in ('upload', 'import', 'verify')}
            old['operations'][phase] = {'state': 'unknown'}
            write_json(self.path, old)
            digest = file_hash(self.path)
            grant = copy.deepcopy(self.new)
            grant['repair_revision'].update(previous_outbox_sha256=digest,
                                            unbound_reviewed_repair=True)
            with self.assertRaisesRegex(WorkflowError, 'Settle all'):
                fireplay.prepare_return(fixtures.CODE, grant, self.root)
            self.assertEqual(file_hash(self.path), digest)


if __name__ == '__main__':
    unittest.main()
