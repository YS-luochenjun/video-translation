from pathlib import Path
from contextlib import redirect_stdout
import importlib.util
import io
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from video_localizer import ocr
from video_localizer.common import WorkflowError, read_json, write_json


class OcrCacheTests(unittest.TestCase):
    def test_compatibility_entry_prepares_codex_without_loading_ocr(self):
        import runpy
        with patch('video_localizer.cli.main', return_value=0) as entry, \
                patch('sys.argv', ['ocr.py', 'fixture']):
            with self.assertRaises(SystemExit) as result:
                runpy.run_path(str(Path(__file__).resolve().parents[1] / 'bin/ocr.py'), run_name='__main__')
        self.assertEqual(result.exception.code, 0)
        entry.assert_called_once_with(['codex-packet', 'fixture'])

    def test_exact_pixels_reuse_but_one_pixel_difference_does_not(self):
        engine = Mock(return_value=([([[0, 0], [8, 0], [8, 8], [0, 8]], 'Hello', .95)], 0))
        seen = {}
        a = Mock(); a.tobytes.return_value = b'pixel-A'
        b = Mock(); b.tobytes.return_value = b'pixel-B'
        first, reused = ocr.infer(a, engine, seen, 20)
        self.assertFalse(reused)
        second, reused = ocr.infer(a, engine, seen, 20)
        self.assertTrue(reused)
        self.assertEqual(second, first)
        self.assertEqual(second[0]['polygon'][0][1], 20)
        ocr.infer(b, engine, seen, 20)
        self.assertEqual(engine.call_count, 2)

    def test_track_summary_preserves_gaps_duplicate_positions_and_raw_frames(self):
        item = {'text': 'Hello', 'polygon': [[1, 1]], 'confidence': .9}
        data = {'source_sha256': 's', 'complete': True, 'frames': [
            {'time': 0, 'observations': [item]}, {'time': .2, 'observations': [item]},
            {'time': .4, 'observations': []}, {'time': .6, 'observations': [item, item]}]}
        report = ocr.summary(data)
        self.assertEqual(len(report['candidate_tracks']), 3)
        self.assertEqual(report['candidate_tracks'][0]['last_observed'], .2)
        self.assertEqual(len(data['frames']), 4)

    def test_cache_requires_complete_matching_model_source_and_parameters(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'cache.json'
            data = {'source_sha256': 'source', 'signature': {'step': .2, 'models': 'model-a'}, 'complete': False, 'frames': []}
            with self.assertRaisesRegex(WorkflowError, 'Partial'):
                ocr.store(path, data)
            data['complete'] = True
            ocr.store(path, data)
            self.assertEqual(ocr.cached(path, data['signature']), data)
            self.assertIsNone(ocr.cached(path, {'step': .1, 'models': 'model-a'}))
            self.assertIsNone(ocr.cached(path, {'step': .2, 'models': 'model-b'}))
            record = read_json(path); record['data']['frames'].append({'tampered': True}); write_json(path, record)
            with self.assertRaisesRegex(WorkflowError, 'corrupted'):
                ocr.cached(path, data['signature'])
