import tempfile
import unittest
from pathlib import Path

from video_localizer import ocr_supplement
from video_localizer.common import WorkflowError, read_json, write_json


class RetiredOcrTests(unittest.TestCase):
    def test_enabled_configuration_cannot_restart_retired_inference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(root / 'config/ocr.local.json', {'enabled': True})
            before = list(root.rglob('*'))
            with self.assertRaisesRegex(WorkflowError, 'retired'):
                ocr_supplement.supplement(root, enabled=True)
            self.assertEqual(list(root.rglob('*')), before)

    def test_historical_evidence_is_read_only_and_never_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            path = run / 'analysis/ocr-supplement.json'
            data = {'source_sha256': 'source', 'status': 'available',
                    'pending_checks': [{'time': 2, 'deferred_reason': 'offline'}]}
            write_json(path, data)
            result = ocr_supplement.context(run, 'source')
            self.assertEqual(result['status'], 'retired')
            self.assertEqual(result['provider'], 'codex')
            self.assertFalse(result['automatic_pass'])
            self.assertEqual(read_json(path), data)
            with self.assertRaisesRegex(WorkflowError, 'source mismatch'):
                ocr_supplement.context(run, 'other')

    def test_no_history_still_routes_to_codex(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = ocr_supplement.context(Path(tmp), 'source')
            self.assertIsNone(result['historical_evidence'])
            self.assertIn('codex-packet', result['next'])
