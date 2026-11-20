import copy
import tempfile
import unittest
from pathlib import Path

from video_localizer.common import WorkflowError, file_hash, read_json, write_json
from video_localizer.fireplay_transport import replace_rejected_upload, reroute_unsent


class TransportRecoveryTests(unittest.TestCase):
    def test_prepared_upload_requires_exact_host_non_execution_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'state/return.json'
            old = {'packages': [{'locale': 'ar', 'sha256': 'video'}],
                   'operations': {'upload-1': {'state': 'unknown'}}, 'state': 'ready'}
            revised = {'packages': [{'locale': 'ar', 'sha256': 'video', 'upload_route': 'presign'}]}
            write_json(path, old)
            proof = root / 'state/nonexecution.json'
            evidence = {'outbox_sha256': file_hash(path), 'reviewer': 'host agent',
                        'basis': 'direct observation', 'external_call_executed': False,
                        'file_selected': False, 'operation_ids': ['upload-1']}
            write_json(proof, evidence)
            grant = {'authority': 'agent', 'reviewer': 'host agent', 'reason': 'binary transport',
                     'previous_outbox_sha256': file_hash(path),
                     'host_non_execution': {'path': 'state/nonexecution.json', 'sha256': file_hash(proof)}}
            for field, bad in [('external_call_executed', True), ('file_selected', True),
                               ('operation_ids', []), ('outbox_sha256', 'different')]:
                invalid = dict(evidence, **{field: bad})
                write_json(proof, invalid)
                grant['host_non_execution']['sha256'] = file_hash(proof)
                with self.assertRaises(WorkflowError):
                    reroute_unsent(path, old, revised, grant, root)
            write_json(proof, evidence)
            grant['host_non_execution']['sha256'] = file_hash(proof)
            result = reroute_unsent(path, old, revised, grant, root)
            self.assertEqual(result['operations'], {})
            self.assertEqual(read_json(root / result['transport_history'][0]['prior_outbox']), old)

    def test_unsent_transport_change_preserves_identity_and_rejects_dispatched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'state/return-2.json'
            old = {'packages': [{'locale': 'es', 'sha256': 'video'}], 'operations': {}, 'state': 'ready'}
            write_json(path, old)
            grant = {'authority': 'agent', 'reviewer': 'Codex', 'reason': 'Host supports presigned uploads',
                     'previous_outbox_sha256': file_hash(path)}
            revised = {'packages': [{'locale': 'es', 'sha256': 'video', 'upload_route': 'presign'}]}
            result = reroute_unsent(path, old, revised, grant, root)
            self.assertEqual(read_json(root / result['transport_history'][0]['prior_outbox']), old)
            self.assertEqual(result['packages'], revised['packages'])
            for change in ('dispatched', 'different_video'):
                blocked = copy.deepcopy(old)
                candidate = copy.deepcopy(revised)
                if change == 'dispatched':
                    blocked['operations'] = {'upload-1': {'state': 'unknown'}}
                else:
                    candidate['packages'][0]['sha256'] = 'different'
                write_json(path, blocked)
                grant['previous_outbox_sha256'] = file_hash(path)
                with self.assertRaises(WorkflowError):
                    reroute_unsent(path, blocked, candidate, grant, root)

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

    def test_413_can_replace_explicitly_unsent_siblings_without_discarding_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path, old, value, grant = self.fixture(root)
            old['packages'].append({'video_index': 1, 'locale': 'ja', 'sha256': 'large-unsent'})
            write_json(path, old); grant['previous_outbox_sha256'] = file_hash(path)
            grant['include_unsent_packages'] = True
            value['packages'].append({'video_index': 1, 'locale': 'ja', 'sha256': 'small-reviewed'})
            result = replace_rejected_upload(path, old, value, grant, root)
            self.assertEqual(result['packages'][2]['sha256'], 'small-reviewed')
            self.assertEqual(result['operations']['upload-1'], old['operations']['upload-1'])
            self.assertIsNone(result['transport_history'][1]['prior_operation'])
            self.assertEqual(read_json(root / result['transport_history'][1]['prior_outbox']), old)

    def test_unsent_sibling_option_never_replaces_dispatched_or_historical_writes(self):
        for state in ['verified', 'unknown', 'attempt_history', 'transport_history']:
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); path, old, value, grant = self.fixture(root)
                prior = {'video_index': 1, 'locale': 'ja', 'sha256': 'large'}
                old['packages'].append(prior)
                if state in ['verified', 'unknown']:old['operations']['upload-3'] = {'state': state}
                if state == 'attempt_history':old['upload_attempts'] = {'upload-3': [{}]}
                if state == 'transport_history':old['transport_history'] = [{'prior_package': prior}]
                write_json(path, old); grant.update(previous_outbox_sha256=file_hash(path), include_unsent_packages=True)
                value['packages'].append({'video_index': 1, 'locale': 'ja', 'sha256': 'small'})
                with self.assertRaises(WorkflowError):replace_rejected_upload(path, old, value, grant, root)
                self.assertEqual(read_json(path), old)

    def test_unsent_sibling_replacement_requires_opt_in_and_unique_locales(self):
        for case in ['not_enabled', 'duplicate']:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); path, old, value, grant = self.fixture(root)
                old['packages'].append({'video_index': 1, 'locale': 'ja', 'sha256': 'large'})
                value['packages'].append({'video_index': 1, 'locale': 'ja', 'sha256': 'small'})
                if case == 'duplicate':
                    grant['include_unsent_packages'] = True
                    value['packages'].append(copy.deepcopy(value['packages'][1]))
                write_json(path, old); grant['previous_outbox_sha256'] = file_hash(path)
                with self.assertRaises(WorkflowError):replace_rejected_upload(path, old, value, grant, root)
                self.assertEqual(read_json(path), old)


if __name__ == '__main__':
    unittest.main()
