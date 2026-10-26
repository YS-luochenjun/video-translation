import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_localizer.common import read_json, write_json


class AtomicJournalTests(unittest.TestCase):
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
