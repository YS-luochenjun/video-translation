import shutil
import tempfile
import unittest
from pathlib import Path

from video_localizer import bundles, failure_closure
from video_localizer.common import WorkflowError, file_hash, read_json, write_json


class FailureClosureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.run = self.root / 'runs/fixture'
        (self.run / 'inputs').mkdir(parents=True)
        (self.run / 'inputs/source.bin').write_bytes(b'source')
        self.sha = file_hash(self.run / 'inputs/source.bin')
        write_json(self.run / 'run.json', {'source': 'inputs/source.bin', 'source_sha256': self.sha})
        write_json(self.run / 'inputs/request.json', {'target_language': 'es'})
        write_json(self.run / 'review/observed.json', {'finding': 'Visible residual outline in sampled frame'})
        self.spec = {'source_sha256': self.sha, 'stage': 'neutral', 'reviewer': 'test reviewer',
                     'review_type': 'same_agent', 'reason': 'Neutral repair failed before final rendering',
                     'hypothesis': 'Mask omitted the outer stroke; inspect the full envelope',
                     'unreviewed_scope': ['Unsampled motion and full output audio'],
                     'observations': [{'observation': 'Residual source lettering in observed frame',
                                       'evidence': [{'path': 'review/observed.json',
                                                     'sha256': file_hash(self.run / 'review/observed.json')}]}]}
        self.save()

    def save(self):
        write_json(self.run / 'inputs/failure.json', self.spec)

    def close(self):
        return failure_closure.close(self.run, 'inputs/failure.json')

    def test_preproduction_failure_is_idempotent_and_survives_run_deletion(self):
        first = self.close()
        self.assertEqual(first, self.close())
        self.assertFalse((self.run / 'outputs/quality.json').exists())
        self.assertFalse((self.run / 'outputs/candidate.json').exists())
        shutil.rmtree(self.run)
        manifest = bundles.verify(self.root / first['case'])
        self.assertEqual(manifest['metadata']['status'], 'candidate')
        self.assertEqual(manifest['metadata']['required_external_files'], [])

    def test_changed_failure_creates_new_case_without_overwriting_old(self):
        first = self.close()
        old = file_hash(self.root / first['case'] / 'manifest.json')
        self.spec['reason'] = 'New bounded retry still changes foreground hair'
        self.save()
        second = self.close()
        self.assertNotEqual(first['case'], second['case'])
        self.assertEqual(file_hash(self.root / first['case'] / 'manifest.json'), old)

    def test_missing_tampered_outside_evidence_and_empty_scope_reject(self):
        for changes in [{'unreviewed_scope': []}, {'observations': []}, {'source_sha256': 'wrong'}]:
            write_json(self.run / 'inputs/failure.json', {**self.spec, **changes})
            with self.assertRaises(WorkflowError): self.close()
        self.save()
        (self.run / 'review/observed.json').write_bytes(b'tampered')
        with self.assertRaisesRegex(WorkflowError, 'evidence'):
            self.close()

    def test_existing_candidate_requires_normal_reflect_and_budgets_untouched(self):
        write_json(self.root / 'state/budgets/fixture.json', {'actual': None, 'reserved': 20})
        before = file_hash(self.root / 'state/budgets/fixture.json')
        self.close()
        self.assertEqual(file_hash(self.root / 'state/budgets/fixture.json'), before)
        write_json(self.run / 'outputs/candidate.json', {'path': 'outputs/final.mp4'})
        with self.assertRaisesRegex(WorkflowError, 'reflect'):
            self.close()
