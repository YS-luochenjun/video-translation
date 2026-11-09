import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_localizer.common import WorkflowError, file_hash, write_json
from video_localizer.fireplay_revision import return_revision


class UnsentQualityRepairTests(unittest.TestCase):
    def test_only_explicit_host_attestation_and_active_hold_allow_unsent_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'state/return-1.json'
            old = {'state': 'ready', 'packages': [{'video_index': 1, 'locale': 'ar',
                    'package': 'outputs/old', 'sha256': 'old-video'}],
                   'operations': {'upload-1': {'state': 'unknown'}}}
            write_json(path, old)
            digest = file_hash(path)
            observation = {'outbox_sha256': digest, 'reviewer': 'Actual host operator',
                           'basis': 'Reviewed this operation tool history; no external call or file selection.',
                           'external_call_executed': False, 'file_selected': False,
                           'operation_ids': ['upload-1']}
            note = root / 'work/non-execution.json'
            write_json(note, observation)
            grant = {'authority': 'user', 'authorization_ref': 'actual-user-repair',
                     'source_quote': 'Fix the rejected version and upload.', 'reason': 'Quality repair',
                     'previous_outbox_sha256': digest, 'unexecuted_quality_repair': True,
                     'host_non_execution': {'path': 'work/non-execution.json', 'sha256': file_hash(note)}}
            value = {'packages': [{'video_index': 1, 'locale': 'ar', 'sha256': 'new-video'}],
                     'operations': {}}
            manifest = {'metadata': {'source_sha256': 'source', 'video_sha256': 'old-video'}}
            with patch('video_localizer.bundles.verify', return_value=manifest), \
                    patch('video_localizer.quality_holds.active', return_value=[{'id': 'real-hold'}]):
                invalid = {**grant, 'host_non_execution': {}}
                with self.assertRaises(WorkflowError):
                    return_revision(path, old, value, invalid, root)
                observation['external_call_executed'] = True
                write_json(note, observation)
                grant['host_non_execution']['sha256'] = file_hash(note)
                with self.assertRaises(WorkflowError):
                    return_revision(path, old, value, grant, root)
                observation['external_call_executed'] = False
                write_json(note, observation)
                grant['host_non_execution']['sha256'] = file_hash(note)
                result = return_revision(path, old, value, grant, root)
                archive = root / result['revision_history'][0]['prior_outbox']
                self.assertEqual(file_hash(archive), digest)
                self.assertEqual(result['operations'], {})
            self.assertEqual(old['operations']['upload-1']['state'], 'unknown')

    def test_plain_unknown_dispatch_still_cannot_be_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path = root / 'return-1.json'
            old = {'packages': [], 'operations': {'upload-1': {'state': 'unknown'}}}
            write_json(path, old)
            grant = {'authority': 'user', 'authorization_ref': 'repair', 'source_quote': 'Repair',
                     'reason': 'Repair', 'previous_outbox_sha256': file_hash(path)}
            with self.assertRaises(WorkflowError):
                return_revision(path, old, {'packages': []}, grant, root)


if __name__ == '__main__':
    unittest.main()
