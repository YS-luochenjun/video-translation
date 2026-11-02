"""Prospective cohorts and honest wall-time accounting, without making media."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_localizer.benchmark import timing, seconds, costs, describe
from video_localizer.ledger import Ledger

START = '2026-11-01T00:00:00Z'
RECEIVED = '2026-11-01T01:00:00Z'
END = '2026-11-01T01:10:00Z'
LATER = '2026-11-01T01:20:00Z'


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ledger = Ledger(self.root)

    def req(self, name='new', received=RECEIVED, end=None, scope='v1'):
        return {'id': name, 'code': name, 'countable': True, 'scope_id': scope,
                'scope': [{'video_id': 's1', 'source_sha256': 'a'*64, 'targets': ['es', 'ja']}],
                'videos': [{'id': 's1', 'targets': ['es', 'ja']}], 'received_at': received,
                'state': 'complete' if end else 'executing', 'video_count': 1, 'task_count': 2,
                'first_scope_output_at': end, 'first_started_at': None,
                'benchmark_sources': [{'video_id': 's1', 'source_sha256': 'a'*64,
                                       'duration_seconds': 25, 'content_features': ['artistic_typography']}],
                'budget_ids': ['budget'], 'evidence': ['actual request']}

    def tasks(self, quality='issues'):
        return [{'id': 'new:s1:'+locale, 'requirement_id': 'new', 'video_id': 's1', 'locale': locale,
                 'runs': ['run-'+locale], 'versions': [{'at': END, 'sha256': (locale[0]*64),
                                                       'quality': quality, 'run_id': 'run-'+locale}]} for locale in ['es', 'ja']]

    def sync(self, reqs, tasks=(), at=LATER):
        with patch('video_localizer.benchmark.now', return_value=at), patch('video_localizer.benchmark.revision', return_value='d'*40):
            self.ledger.reconcile(reqs, tasks, {})
            self.ledger.update_benchmark()

    def enable(self):
        self.sync([self.req('baseline', START)], at=START)

    def test_future_only_restart_late_discovery_and_baseline_revision(self):
        self.enable()
        self.sync([self.req('baseline', RECEIVED), self.req('late-old', START), self.req('unknown', None), self.req()])
        report = Ledger(self.root).benchmark(at=LATER)
        self.assertEqual(report['started_at'], START)
        self.assertEqual(report['baseline_excluded'], 1)
        self.assertEqual([s['code'] for s in report['samples']], ['new'])
        self.assertEqual(report['pending_samples'], 1)
        self.assertEqual(report['cohorts'], [])
        self.sync([self.req()])
        self.assertEqual(len(self.ledger.benchmark(at=LATER)['samples']), 1)

    def test_first_output_quality_freeze_expiry_and_scope_change(self):
        self.enable()
        self.sync([self.req()], self.tasks())
        self.sync([self.req(end=END)], self.tasks())
        report = self.ledger.benchmark(at=LATER)
        self.assertEqual(report['completed_samples'], 1)
        self.assertEqual(report['samples'][0]['first_output']['quality_pass_count'], 0)
        self.sync([self.req(end=LATER)], self.tasks('pass'))
        report = self.ledger.benchmark(at=LATER)
        self.assertEqual(report['samples'][0]['first_output']['at'], END)
        self.assertEqual(report['samples'][0]['first_output']['quality_pass_count'], 0)
        # Expired/corrupt files cannot erase a previously observed first output.
        self.sync([self.req()], [])
        self.assertEqual(self.ledger.benchmark(at=LATER)['completed_samples'], 1)
        self.sync([self.req(scope='v2')], [])
        sample = self.ledger.benchmark(at=LATER)['samples'][0]
        self.assertTrue(sample['scope_changed'])
        self.assertEqual(sample['scope_id'], 'v1')
        self.assertEqual(sample['first_output']['at'], END)

    def test_no_completion_from_partial_output_and_scope_change(self):
        self.enable()
        self.sync([self.req()], self.tasks()[:1])
        self.sync([self.req(scope='v2')], self.tasks())
        report = self.ledger.benchmark(at=LATER)
        self.assertEqual(report['completed_samples'], 0)
        self.assertEqual(report['pending_samples'], 0)
        self.assertEqual(report['stopped_samples'], 1)
        self.assertEqual(report['cohorts'], [])

    def event(self, kind, at, **data):
        return {'id': str(at)+kind, 'kind': kind, 'occurred_at': at, 'recorded_at': at, 'data': data}

    def test_overlap_nested_straddling_first_output_and_explicit_wait(self):
        sample = {'received_at': RECEIVED, 'scope_id': 'v1', 'first_output': {'at': END}, 'run_ids': ['run']}
        def stage(a, b, parent=None):
            return self.event('stage_recorded', b, started_at=a, ended_at=b, parent_id=parent)
        events = [self.event('claim', '2026-11-01T01:00:30Z'),
                  stage('2026-11-01T01:01:00Z', '2026-11-01T01:03:00Z'),
                  stage('2026-11-01T01:02:00Z', '2026-11-01T01:04:00Z'),
                  stage('2026-11-01T01:02:00Z', '2026-11-01T01:03:00Z', 'parent'),
                  stage('2026-11-01T01:09:00Z', '2026-11-01T01:11:00Z'),
                  self.event('block', '2026-11-01T01:03:00Z'),
                  self.event('block', '2026-11-01T01:04:00Z'),
                  self.event('resume', '2026-11-01T01:05:00Z')]
        result = timing(sample, events, seconds(LATER))
        self.assertEqual(result['received_to_first_output_seconds'], 600)
        self.assertEqual(result['first_production_span_seconds'], 570)
        self.assertEqual(result['recorded_first_executor_seconds'], 240)
        self.assertEqual(result['recorded_first_wait_seconds'], 120)
        self.assertEqual(result['unclassified_first_seconds'], 300)
        self.assertEqual(result['recorded_rework_executor_seconds'], 60)
        self.assertEqual(result['timing_records'], 3)

    def test_missing_wait_and_unfinished_timing_are_not_zero_work(self):
        sample = {'received_at': RECEIVED, 'scope_id': 'v1', 'first_output': None}
        result = timing(sample, [self.event('stage_recorded', END, status='running', started_at=RECEIVED)], seconds(LATER))
        self.assertIsNone(result['recorded_first_executor_seconds'])
        self.assertIsNone(result['recorded_first_wait_seconds'])
        self.assertIsNone(result['first_production_span_seconds'])
        self.assertEqual(result['unfinished_timing_records'], 1)
        self.assertEqual(result['unclassified_first_seconds'], 1200)
        result = timing(sample, [self.event('block', END)], seconds(LATER))
        self.assertTrue(result['open_wait'])
        self.assertEqual(result['recorded_first_wait_seconds'], 600)

    def test_other_scope_and_unrelated_run_do_not_contaminate(self):
        sample = {'received_at': RECEIVED, 'scope_id': 'v1', 'first_output': {'at': END}, 'run_ids': ['ours']}
        events = [self.event('claim', RECEIVED, scope_id='v2'),
                  {**self.event('stage_recorded', END, started_at=RECEIVED, ended_at=END), 'run_id': 'theirs'}]
        result = timing(sample, events, seconds(LATER))
        self.assertIsNone(result['first_production_span_seconds'])
        self.assertIsNone(result['recorded_first_executor_seconds'])

    def test_source_duration_not_multiplied_by_locales_unknown_features(self):
        req = self.req()
        sample = {**req, 'sources': req['benchmark_sources'], 'profile_version': 'test'}
        d = describe(sample, {'duration_bands_seconds': [30, 60]})
        self.assertEqual(d['total_source_seconds'], 25)
        self.assertEqual(d['complexity'], 'styled/surface')
        sample['sources'][0]['content_features'] = None
        self.assertEqual(describe(sample, {'duration_bands_seconds': [30, 60]})['complexity'], 'unknown')

    def test_small_sample_p90_and_filters(self):
        self.enable()
        self.sync([self.req(end=END)], self.tasks())
        report = self.ledger.benchmark(at=LATER)
        self.assertEqual(report['cohorts'][0]['n'], 1)
        self.assertTrue(report['cohorts'][0]['exploratory'])
        self.assertIsNone(report['cohorts'][0]['p90_first_cycle_seconds'])
        self.assertEqual(self.ledger.benchmark(rows=[], at=LATER)['samples'], [])

    def test_cost_unknown_stays_unknown_including_nonterminal_billing(self):
        path = self.root/'state/budgets/budget.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'reservations': {'one': {'actual_credits': 3, 'state': 'success'}, 'two': {'actual_credits': None, 'state': 'ambiguous'}}}))
        result = costs(self.root, {'budget_ids': ['budget']})
        self.assertFalse(result['complete'])
        self.assertEqual(result['known_actual_credits'], 3)
        self.assertEqual(result['unknown_reservations'], 1)
        self.assertIsNone(costs(self.root, {})['known_actual_credits'])
        path.write_text(json.dumps({'reservations': {'one': {'actual_credits': 3, 'state': 'submitting'}}}))
        self.assertFalse(costs(self.root, {'budget_ids': ['budget']})['complete'])

    def test_p90_requires_twenty_comparable_completed_requests(self):
        self.enable()
        self.sync([self.req('request-'+str(i), end=END) for i in range(20)])
        report = self.ledger.benchmark(at=LATER)
        self.assertEqual(len(report['cohorts']), 1)
        self.assertEqual(report['cohorts'][0]['n'], 20)
        self.assertEqual(report['cohorts'][0]['p90_first_cycle_seconds'], 600)
        self.assertFalse(report['cohorts'][0]['exploratory'])

    def test_invalid_config_cannot_enable_misleading_cohorts(self):
        p = self.root/'config/ledger.json'
        p.parent.mkdir()
        p.write_text(json.dumps({'benchmark': {'duration_bands_seconds': [60, 30]}}))
        with self.assertRaisesRegex(ValueError, 'Invalid benchmark'):
            self.sync([], at=START)
        self.assertFalse(self.ledger.benchmark(at=LATER)['enabled'])

    def test_negative_cycle_is_pending_not_a_fast_completed_sample(self):
        self.enable()
        self.sync([self.req(received=END, end=RECEIVED)])
        report = self.ledger.benchmark(at=LATER)
        self.assertEqual(report['completed_samples'], 0)
        self.assertEqual(report['samples'][0]['invalid_first_output_at'], RECEIVED)

    def test_query_does_not_enable_or_trigger_sampling(self):
        self.assertFalse(self.ledger.benchmark(at=LATER)['enabled'])
        with self.ledger.connection() as db:
            self.assertIsNone(db.execute("SELECT value FROM meta WHERE key='benchmark:activation'").fetchone())


if __name__ == '__main__':
    unittest.main()
