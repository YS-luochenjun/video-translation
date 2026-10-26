import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_localizer.common import read_json, write_json


class AtomicJournalTests(unittest.TestCase):
    def test_invalid_record_identifies_file_without_exposing_content_or_repairing(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'capture.json'
            for contents in ('', '{"private": "secret-value", broken}'):
                with self.subTest(contents=bool(contents)):
                    path.write_text(contents, encoding='utf-8')
                    with self.assertRaises(json.JSONDecodeError) as raised:
                        read_json(path)
                    self.assertIn(str(path), str(raised.exception))
                    self.assertNotIn('secret-value', str(raised.exception))
                    self.assertEqual(path.read_text(), contents)

    def test_transient_windows_reader_keeps_old_record_until_replace(self):
        import os
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'journal.json'
            write_json(path, {'state': 'submitting'})
            replace = os.replace
            blocked = PermissionError('temporary reader')
            blocked.winerror = 32
            calls = []

            def transient(source, target):
                calls.append(source)
                self.assertEqual(read_json(path), {'state': 'submitting'})
                if len(calls) < 3:
                    raise blocked
                return replace(source, target)

            with patch('video_localizer.common.os.replace', side_effect=transient), patch('video_localizer.common.time.sleep'):
                write_json(path, {'state': 'response_received'})
            self.assertEqual(read_json(path), {'state': 'response_received'})
            self.assertEqual(len(set(calls)), 1)

    def test_permanent_denial_leaves_old_journal_and_propagates(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'journal.json'
            write_json(path, {'state': 'submitting'})
            denied = PermissionError('denied')
            denied.winerror = 5
            with patch('video_localizer.common.os.replace', side_effect=denied) as replace, patch('video_localizer.common.time.sleep'):
                with self.assertRaises(PermissionError):
                    write_json(path, {'state': 'success'})
            self.assertEqual(replace.call_count, 5)
            self.assertEqual(read_json(path), {'state': 'submitting'})
            self.assertEqual(list(Path(folder).glob('*.tmp')), [])
