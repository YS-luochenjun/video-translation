from pathlib import Path
import tempfile
import unittest

from video_localizer import prepared, reuse
from video_localizer.common import WorkflowError, file_hash, read_json, write_json


class NeutralReuseTests(unittest.TestCase):
    def setUp(self):
        # Fake byte files isolate copying; real-media audit portability is tested separately.
        from unittest.mock import patch
        gate = patch('video_localizer.visual_audit.verify_neutral', return_value={})
        gate.start(); self.addCleanup(gate.stop)
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'work/test-tmp')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'runs/source'
        self.target = self.root / 'runs/target'
        for run in (self.source, self.target):
            run.mkdir(parents=True)
            (run / 'source.mp4').write_bytes(b'original')
            write_json(run / 'run.json', {'source': 'source.mp4', 'source_sha256': file_hash(run / 'source.mp4')})
        sha = file_hash(self.source / 'source.mp4')
        (self.source / 'master.mp4').write_bytes(b'neutral')
        (self.source / 'frame.jpg').write_bytes(b'observed evidence fixture')
        evidence = {'path': 'frame.jpg', 'sha256': file_hash(self.source / 'frame.jpg')}
        write_json(self.source / 'visual-review.json', {'source_sha256': sha,
            'video_sha256': file_hash(self.source / 'master.mp4'), 'decision': 'pass', 'reviewer': 'synthetic fixture',
            'checks': {key: 'pass' for key in ('source_text_removal','texture_and_color','foreground_motion','temporal_boundaries')},
            'evidence': [evidence]})
        record = {'source_sha256': sha, 'target_language': None, 'contains_target_typography': False,
            'output': {'path': 'master.mp4', 'sha256': file_hash(self.source / 'master.mp4')},
            'inputs': [evidence], 'approved_for_reuse': True,
            'visual_review': {'path': 'visual-review.json', 'sha256': file_hash(self.source / 'visual-review.json')}}
        write_json(self.source / 'preparation.json', record)
        asset = {**record['output'], 'record': 'preparation.json', 'record_sha256': file_hash(self.source / 'preparation.json')}
        write_json(self.source / 'analysis/inventory.json', {'shots': [{'id': 's1', 'start': 0, 'end': 2, 'prepared_video': asset}]})
        write_json(self.target / 'analysis/inventory.json', {'shots': [{'id': 't1', 'start': 0, 'end': 2}],
            'text_instances': [{'target_text': 'new locale copy'}], 'audio': {'strategy': 'pending'}})

    def test_reuse_copies_bound_evidence_keeps_target_decisions_and_survives_source_changes(self):
        result = reuse.neutral(self.target, self.source, 's1', 't1')
        inventory = read_json(self.target / 'analysis/inventory.json')
        self.assertEqual(inventory['text_instances'][0]['target_text'], 'new locale copy')
        self.assertEqual(inventory['audio']['strategy'], 'pending')
        self.assertFalse((self.target / 'review/review.json').exists())
        (self.source / 'master.mp4').write_bytes(b'later change')
        prepared.verify_for_production(self.target, result['prepared_video'], file_hash(self.target / 'source.mp4'), self.root)

    def test_different_source_or_timeline_does_not_import(self):
        inventory = read_json(self.target / 'analysis/inventory.json')
        inventory['shots'][0]['end'] = 3
        write_json(self.target / 'analysis/inventory.json', inventory)
        with self.assertRaisesRegex(WorkflowError, 'timeline'):
            reuse.neutral(self.target, self.source, 's1', 't1')
        self.assertNotIn('prepared_video', read_json(self.target / 'analysis/inventory.json')['shots'][0])
