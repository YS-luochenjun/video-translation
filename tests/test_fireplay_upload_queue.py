import tempfile
import unittest
from pathlib import Path

from video_localizer.fireplay_upload_queue import acquire, release, status


class FireplayUploadQueueTests(unittest.TestCase):
    def test_second_upload_waits_until_first_receipt_releases_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = acquire('APC-20261119-001', 1, 'upload-1',
                            {'locale': 'es', 'sha256': 'a' * 64, 'outbox': 'state/a.json'}, root)
            second = acquire('MOG-20261119-002', 1, 'upload-1',
                             {'locale': 'de', 'sha256': 'b' * 64, 'outbox': 'state/b.json'}, root)
            self.assertTrue(first['acquired'])
            self.assertFalse(second['acquired'])
            self.assertEqual(second['position'], 1)
            release('APC-20261119-001', 1, 'upload-1', 'verified', root)
            third = acquire('MOG-20261119-002', 1, 'upload-1',
                            {'locale': 'de', 'sha256': 'b' * 64, 'outbox': 'state/b.json'}, root)
            self.assertTrue(third['acquired'])
            self.assertEqual(len(status(root)['active']), 1)

    def test_same_upload_is_idempotent_while_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = {'locale': 'es', 'sha256': 'a' * 64, 'outbox': 'state/a.json'}
            first = acquire('APC-20261119-001', 1, 'upload-1', args, root)
            again = acquire('APC-20261119-001', 1, 'upload-1', args, root)
            self.assertTrue(first['acquired'])
            self.assertTrue(again['acquired'])
            self.assertEqual(len(status(root)['active']), 1)


if __name__ == '__main__':
    unittest.main()
