import copy
import tempfile
import unittest
from pathlib import Path

from video_localizer.common import WorkflowError, file_hash, read_json, write_json
from video_localizer.fireplay_transport import replace_rejected_upload


class TransportRecoveryTests(unittest.TestCase):
    def fixture(self, root, text=None):
        receipt = root / 'state/rejection.json'
        write_json(receipt, {'response': {'isError': True, 'content': [{'type': 'text', 'text': text or
            'Mcp error: ai-designer MCP returned HTTP 413: {"statusCode":413,"message":"request entity too large"}'}]}})
        old = {'packages': [{'video_index': 1, 'locale': 'de', 'sha256': 'kept'},
                            {'video_index': 1, 'locale': 'fr', 'sha256': 'old'}],
               'operations': {'upload-1': {'state': 'verified', 'result': {'resourceId': 'kept'}},
                              'upload-2': {'state': 'unknown', 'last_observed_receipt': 'state/rejection.json'}},
               'pending_locales': ['ja'], 'state': 'ready'}
        path = root / 'state/return-1.json'; write_json(path, old)
        grant = {'authority': 'agent', 'reviewer': 'Actual host', 'reason': 'Smaller reviewed encoding',
                 'previous_outbox_sha256': file_hash(path), 'rejection_receipt':
                 {'path': 'state/rejection.json', 'sha256': file_hash(receipt)}}
        value = {'packages': [{'video_index': 1, 'locale': 'fr', 'sha256': 'new'}]}
        return path, old, value, grant

    def test_413_preserves_other_locales_and_complete_prior_outbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path, old, value, grant = self.fixture(root)
            result = replace_rejected_upload(path, old, value, grant, root)
            self.assertEqual(result['packages'][0], old['packages'][0])
            self.assertEqual(result['operations']['upload-1'], old['operations']['upload-1'])
            self.assertNotIn('upload-2', result['operations'])
            self.assertEqual(old['operations']['upload-2']['state'], 'unknown')
            archive = root / result['transport_history'][0]['prior_outbox']
            self.assertEqual(read_json(archive), old)
            self.assertEqual(file_hash(archive), grant['previous_outbox_sha256'])

    def test_timeout_and_imported_or_bound_uploads_are_never_replaced(self):
        for case in ['timeout', 'imported', 'bound', 'verified']:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); path, old, value, grant = self.fixture(root,
                    'TimeoutError: result unknown' if case == 'timeout' else None)
                if case == 'imported': old['operations']['import-2'] = {'state': 'unknown'}
                if case == 'bound': old['operations']['bind'] = {'state': 'unknown'}
                if case == 'verified': old['operations']['upload-2']['state'] = 'verified'
                write_json(path, old); grant['previous_outbox_sha256'] = file_hash(path)
                with self.assertRaises(WorkflowError):
                    replace_rejected_upload(path, old, value, grant, root)
                self.assertEqual(read_json(path), old)


if __name__ == '__main__':
    unittest.main()
