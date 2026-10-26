import tempfile
import unittest
from pathlib import Path
from video_localizer.library import source_folder
from video_localizer.common import WorkflowError, write_json

class DeliveryFoldersTests(unittest.TestCase):
    def test_named_sources_and_unregistered_legacy_source(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            write_json(root/'state/delivery-folders.json', {'sources': {'a'*64:'需求 A'}})
            self.assertEqual(source_folder(root, 'a'*64), '需求 A')
            self.assertEqual(source_folder(root, 'b'*64), 'b'*16)

    def test_path_escape_reserved_name_and_case_collision_fail_closed(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            for names in ({'a':'../outside'}, {'a':'reports'}, {'a':'bad/name'}, {'a':'Demo','b':'demo'}):
                write_json(root/'state/delivery-folders.json', {'sources':names})
                with self.assertRaises(WorkflowError):
                    source_folder(root, 'a')
