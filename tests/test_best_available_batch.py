"""A finalized imperfect pilot permits output, never quality or master inheritance."""
import tempfile
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from video_localizer import batches
from video_localizer.common import WorkflowError, file_hash, read_json, write_json


class BestAvailableBatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.pilot = self.root / 'runs/pilot'
        self.child = self.root / 'runs/child'
        write_json(self.root / 'config/workspace.json', {'output_policy': 'best_available_required'})
        for run in (self.pilot, self.child):
            (run / 'inputs').mkdir(parents=True)
            (run / 'inputs/source.mp4').write_bytes(b'synthetic source')
            write_json(run / 'run.json', {'source': 'inputs/source.mp4',
                       'source_sha256': file_hash(run / 'inputs/source.mp4')})
            write_json(run / 'inputs/request.json', {'delivery_mode': 'fast', 'require_target_audio': True})
            write_json(run / 'inputs/batch.json', {'id': 'fixture'})
        self.source = file_hash(self.pilot / 'inputs/source.mp4')
        write_json(self.pilot / 'analysis/inventory.json', {'speech_segments': [{'id': 'a001'}], 'text_instances': []})
        (self.pilot / 'outputs').mkdir()
        (self.pilot / 'outputs/translated.mp4').write_bytes(b'synthetic translated video')
        (self.pilot / 'outputs/final.mp4').write_bytes(b'synthetic translated video')
        write_json(self.pilot / 'review/observations.json', {'fixture': 'Actual evidence binding test, no media acceptance'})
        self.spec = {'source_sha256': self.source,
            'inventory_sha256': file_hash(self.pilot / 'analysis/inventory.json'),
            'request_sha256': file_hash(self.pilot / 'inputs/request.json'),
            'video': {'path': 'outputs/translated.mp4', 'sha256': file_hash(self.pilot / 'outputs/translated.mp4')},
            'reviewer': 'fixture', 'reason': 'Bounded route ended', 'text_ids': [], 'speech_ids': ['a001'],
            'speech_mode': 'dubbed', 'evidence': [{'path': 'review/observations.json',
                'sha256': file_hash(self.pilot / 'review/observations.json')}], 'limitations': ['Cosmetic repair visible']}
        self.save_completion()
        self.record = {'id': 'fixture', 'pilot': 'pilot', 'members': ['pilot', 'child'],
                       'source_sha256': self.source, 'state': 'pilot_pending'}
        self.path = self.root / 'state/batches/fixture.json'
        write_json(self.path, self.record)

    def save_completion(self):
        write_json(self.pilot / 'review/finalization.json', self.spec)
        write_json(self.pilot / 'outputs/completion.json', {'state': 'delivered_with_issues',
            'decode_passed': True, 'quality_passed': False, 'spec': 'review/finalization.json',
            'spec_sha256': file_hash(self.pilot / 'review/finalization.json'),
            'video_sha256': self.spec['video']['sha256'], 'source_sha256': self.source,
            'inventory_sha256': self.spec['inventory_sha256'], 'request_sha256': self.spec['request_sha256']})

    def test_explicit_output_release_keeps_issues_and_rejects_master_inheritance(self):
        result = batches.approve('fixture', self.root, best_available=True)
        self.assertFalse(result['pilot_release']['quality_passed'])
        self.assertFalse(result['pilot_release']['neutral_approval'])
        self.assertEqual(read_json(self.path)['state'], 'pilot_completed_with_issues')
        batches.gate(self.child, {'segments': []})
        with self.assertRaisesRegex(WorkflowError, 'master differs'):
            batches.gate(self.child, {'segments': [{'start': 0, 'end': 1, 'prepared_video': {'sha256': 'unapproved'}}]})

    def test_changed_completed_video_revokes_release(self):
        batches.approve('fixture', self.root, best_available=True)
        (self.pilot / 'outputs/final.mp4').write_bytes(b'changed')
        with self.assertRaisesRegex(WorkflowError, 'video changed'):
            batches.gate(self.child)

    def test_missing_or_invalid_completion_cannot_expand(self):
        (self.pilot / 'outputs/completion.json').unlink()
        with self.assertRaisesRegex(WorkflowError, 'Finalize the complete'):
            batches.approve('fixture', self.root, best_available=True)
        self.spec['speech_mode'] = 'subtitled'
        self.save_completion()
        with self.assertRaisesRegex(WorkflowError, 'Target audio is required'):
            batches.approve('fixture', self.root, best_available=True)

    def test_other_source_or_changed_evidence_is_rejected(self):
        record = {**self.record, 'source_sha256': 'different'}
        with self.assertRaisesRegex(WorkflowError, 'another source'):
            batches._finalized_pilot_snapshot(record, self.root)
        write_json(self.pilot / 'review/observations.json', {'changed': True})
        with self.assertRaisesRegex(WorkflowError, 'asset changed'):
            batches._finalized_pilot_snapshot(self.record, self.root)

    def test_strict_child_cannot_inherit_best_available_scope(self):
        batches.approve('fixture', self.root, best_available=True)
        write_json(self.child / 'inputs/request.json', {'delivery_mode': 'strict'})
        with self.assertRaisesRegex(WorkflowError, 'strict expansion'):
            batches.gate(self.child)
