import tempfile
import unittest
from pathlib import Path

from video_localizer.common import WorkflowError, file_hash, write_json
from video_localizer import prepared


class NeutralVisualGateTests(unittest.TestCase):
    def setUp(self):
        # Legacy preparation-envelope unit tests. The new gate has unmocked
        # synthetic media/reuse coverage in test_visual_audit.py.
        from unittest.mock import patch
        gate = patch('video_localizer.visual_audit.verify_neutral', return_value={})
        gate.start(); self.addCleanup(gate.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)
        (self.run / 'source.mp4').write_bytes(b'source')
        (self.run / 'master.mp4').write_bytes(b'neutral fixture')
        (self.run / 'frame.jpg').write_bytes(b'inspected frame fixture')
        self.source_sha = file_hash(self.run / 'source.mp4')
        self.record = {
            'source_sha256': self.source_sha, 'target_language': None,
            'contains_target_typography': False,
            'inputs': [{'path': 'source.mp4', 'sha256': self.source_sha}],
            'output': {'path': 'master.mp4', 'sha256': file_hash(self.run / 'master.mp4')},
        }
        self.asset = {
            **self.record['output'], 'record': 'preparation.json',
            'record_sha256': '',
        }
        self.persist()

    def persist(self):
        write_json(self.run / 'preparation.json', self.record)
        self.asset['record_sha256'] = file_hash(self.run / 'preparation.json')

    def approve(self):
        self.review = {
            'source_sha256': self.source_sha, 'video_sha256': self.asset['sha256'],
            'decision': 'pass', 'reviewer': 'test reviewer',
            'checks': {k: 'pass' for k in (
                'source_text_removal', 'texture_and_color',
                'foreground_motion', 'temporal_boundaries')},
            'evidence': [{'path': 'frame.jpg', 'sha256': file_hash(self.run / 'frame.jpg')}],
        }
        self.save_review()

    def save_review(self):
        write_json(self.run / 'review.json', self.review)
        self.record.update(approved_for_reuse=True, visual_review={
            'path': 'review.json', 'sha256': file_hash(self.run / 'review.json')})
        self.record['inputs'] = [
            {'path': 'source.mp4', 'sha256': self.source_sha},
            *self.review['evidence'],
        ]
        self.persist()

    def test_failed_and_unreviewed_archives_remain_readable_but_cannot_render(self):
        for flag in (None, False):
            if flag is not None:
                self.record['approved_for_reuse'] = flag
            self.persist()
            self.assertTrue(prepared.verify(self.run, self.asset, self.source_sha).exists())
            with self.assertRaisesRegex(WorkflowError, 'not approved'):
                prepared.verify_for_production(self.run, self.asset, self.source_sha)

    def test_boolean_approval_without_review_is_insufficient(self):
        self.record['approved_for_reuse'] = True
        self.persist()
        with self.assertRaisesRegex(WorkflowError, 'bound visual review'):
            prepared.verify_for_production(self.run, self.asset, self.source_sha)

    def test_renderer_stops_before_media_work_for_unapproved_master(self):
        with self.assertRaisesRegex(WorkflowError, 'not approved'):
            prepared.render(self.run, {'prepared_video': self.asset}, [], {},
                            self.run / 'unused-render-directory', self.source_sha)
        self.assertFalse((self.run / 'unused-render-directory').exists())

    def test_foreground_failure_and_wrong_video_are_rejected(self):
        self.approve()
        self.review['checks']['foreground_motion'] = 'revise'
        self.save_review()
        with self.assertRaisesRegex(WorkflowError, 'foreground_motion'):
            prepared.verify_for_production(self.run, self.asset, self.source_sha)
        self.review['checks']['foreground_motion'] = 'pass'
        self.review['video_sha256'] = 'another-video'
        self.save_review()
        with self.assertRaisesRegex(WorkflowError, 'another source or video'):
            prepared.verify_for_production(self.run, self.asset, self.source_sha)

    def test_bound_pass_and_tampered_evidence(self):
        self.approve()
        self.assertTrue(prepared.verify_for_production(self.run, self.asset, self.source_sha).exists())
        (self.run / 'frame.jpg').write_bytes(b'replaced evidence')
        with self.assertRaisesRegex(WorkflowError, 'input changed'):
            prepared.verify_for_production(self.run, self.asset, self.source_sha)

    def test_review_evidence_must_survive_archive_closure(self):
        self.approve()
        self.record['inputs'] = self.record['inputs'][:1]
        self.persist()
        with self.assertRaisesRegex(WorkflowError, 'portable reuse'):
            prepared.verify_for_production(self.run, self.asset, self.source_sha)

    def test_reviewed_master_and_evidence_are_in_asset_closure(self):
        from video_localizer.library import _asset_closure
        self.approve()
        closure = _asset_closure(self.run, [
            (self.run / self.asset['path'], self.asset['sha256']),
            (self.run / self.asset['record'], self.asset['record_sha256']),
        ])
        self.assertIn('review.json', closure)
        self.assertIn('frame.jpg', closure)
