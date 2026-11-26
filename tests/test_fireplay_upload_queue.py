import tempfile
import unittest
from pathlib import Path

from video_localizer.common import write_json, read_json
from video_localizer.fireplay_upload_queue import acquire, migrate, release, status


class FireplayUploadQueueTests(unittest.TestCase):
    def test_second_upload_proceeds_while_first_is_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = acquire('APC-20261119-001', 1, 'upload-1',
                            {'locale': 'es', 'sha256': 'a' * 64, 'outbox': 'state/a.json'}, root)
            second = acquire('MOG-20261119-002', 1, 'upload-1',
                             {'locale': 'de', 'sha256': 'b' * 64, 'outbox': 'state/b.json'}, root)
            self.assertTrue(first['acquired'])
            self.assertTrue(second['acquired'])
            self.assertIsNone(status(root)['max_active'])
            self.assertEqual(len(status(root)['active']), 2)
            release('APC-20261119-001', 1, 'upload-1', 'verified', root)
            third = acquire('MOG-20261119-002', 1, 'upload-1',
                            {'locale': 'de', 'sha256': 'b' * 64, 'outbox': 'state/b.json'}, root)
            self.assertTrue(third['acquired'])
            self.assertEqual(len(status(root)['active']), 1)

    def test_legacy_waiters_resume_without_clearing_unknown_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queue = root / 'state/fireplay/upload-queue.json'
            write_json(root / 'state/a.json', {'operations': {'upload-1': {'state': 'unknown'}}})
            write_json(queue, {'schema_version': 1, 'max_active': 1, 'entries': [
                {'key': 'APC:1:upload-1', 'operation_id': 'upload-1', 'outbox': 'state/a.json',
                 'locale': 'es', 'state': 'active'},
                {'key': 'MOG:1:upload-1', 'operation_id': 'upload-1', 'outbox': 'state/b.json',
                 'locale': 'de', 'state': 'queued', 'queued_at': 'original'},
                {'key': 'WOW:1:upload-1', 'operation_id': 'upload-1', 'state': 'completed'},
            ]})
            migrate(root)
            self.assertEqual(status(root)['queued'], [])
            self.assertEqual(status(root)['ready'][0]['queued_at'], 'original')
            self.assertTrue(acquire('MOG', 1, 'upload-1', {}, root)['acquired'])
            self.assertEqual(len(status(root)['active']), 2)
            self.assertEqual(read_json(queue)['entries'][2]['state'], 'completed')
            self.assertEqual(read_json(root / 'state/a.json')['operations']['upload-1']['state'], 'unknown')

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
