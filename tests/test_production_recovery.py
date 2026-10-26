import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_localizer import cli, work_packet, knowledge
from video_localizer.common import WorkflowError, file_hash, write_json


class ProductionRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name) / 'runs/recovery'
        self.run.mkdir(parents=True)
        source = self.run / 'source.mp4'
        source.write_bytes(b'source')
        write_json(self.run / 'run.json', {'source': 'source.mp4', 'source_sha256': file_hash(source)})
        write_json(self.run / 'inputs/request.json', {'target_language': 'en'})
        self.inventory = {'coverage': {k: {'status': 'reviewed'} for k in ('visual', 'speech', 'timeline')},
                          'shots': [{'id': 's001', 'prepared_video': {'path': 'master.mkv'}}]}
        write_json(self.run / 'analysis/inventory.json', self.inventory)

    def test_unreleased_master_resumes_review_instead_of_restarting_source(self):
        with patch('video_localizer.prepared.verify_for_production', side_effect=WorkflowError('unapproved master')):
            result = work_packet.build(self.run)
        self.assertEqual(result['state_hint'], 'needs_neutral_review')
        self.assertEqual(result['stage'], 'neutral')
        self.assertIn('unapproved master', str(result['blockers']))
        self.assertIsNone(result['candidate'])
        self.assertFalse((self.run / 'plan.json').exists())

    def test_reviewed_master_resumes_planning_without_creating_approval(self):
        with patch('video_localizer.prepared.verify_for_production'):
            self.assertEqual(cli.status(self.run)['state'], 'needs_planning')
        self.assertFalse((self.run / 'review/review.json').exists())

    def test_failed_unknown_charge_and_draft_are_visible_but_not_final(self):
        self.inventory['shots'] = []
        write_json(self.run / 'analysis/inventory.json', self.inventory)
        write_json(self.run / 'jobs/failed.json', {'id': 'failed', 'state': 'failed',
                   'estimated_credits': 20, 'credits_consumed': None, 'error': 'HTTP 524'})
        movie = self.run / 'outputs/experiment/preview.mp4'
        movie.parent.mkdir(parents=True)
        movie.write_bytes(b'preview')
        write_json(movie.parent / 'diagnostic-candidate.json',
                   {'path': 'outputs/experiment/preview.mp4', 'sha256': file_hash(movie)})
        result = work_packet.build(self.run)
        self.assertIsNone(result['candidate'])
        self.assertEqual(len(result['diagnostic_candidates']), 1)
        self.assertTrue(result['billing_pending'])
        self.assertIn('20', str(result['billing_pending']))
        self.assertFalse(result['automatic_pass'])
        movie.write_bytes(b'changed')
        result = work_packet.build(self.run)
        self.assertFalse(result['diagnostic_candidates'][0]['integrity_ok'])

    def test_partial_coverage_stays_at_source(self):
        self.inventory['coverage'].pop('speech')
        write_json(self.run / 'analysis/inventory.json', self.inventory)
        self.assertEqual(cli.status(self.run)['state'], 'awaiting_agent_inventory')

    def test_early_reflection_returns_resume_guidance_without_inventing_evidence(self):
        result = knowledge.reflect(self.run, self.run.parent.parent)
        self.assertEqual(result['status'], 'not_ready')
        self.assertIn('outputs/quality.json', result['missing'])
        self.assertIn('work-packet recovery', result['next_command'])
        self.assertIsNone(result['case'])
        self.assertFalse((self.run.parent.parent / 'knowledge').exists())

    def test_pending_provider_task_resumes_polling_not_translation(self):
        with patch.object(cli, 'status', return_value={'state': 'awaiting_model', 'jobs': [
                {'id': 'video-job', 'state': 'generating', 'task_id': 'provider-id'}]}):
            result = work_packet.build(self.run)
        self.assertEqual(result['stage'], 'render')
        self.assertEqual(result['next_action']['kind'], 'poll_existing')
        self.assertIn('video-job', str(result['next_action']))
        self.assertFalse(result['next_action']['new_paid_submission'])

    def test_review_and_delivery_guidance_does_not_start_another_render(self):
        for state, expected in [('needs_review', 'review_actual_candidate'),
                                ('ready_to_deliver', 'deliver'), ('delivered', 'delivery_complete')]:
            with self.subTest(state=state), patch.object(cli, 'status', return_value={'state': state, 'jobs': []}):
                result = work_packet.build(self.run)
            self.assertEqual(result['next_action']['kind'], expected)
            self.assertNotIn('production', str(result['next_action']))
            self.assertFalse(result['automatic_pass'])

    def test_unplanned_diagnostics_must_rejoin_formal_flow(self):
        self.inventory['shots'] = []
        write_json(self.run / 'analysis/inventory.json', self.inventory)
        result = work_packet.build(self.run)
        self.assertEqual(result['next_action']['kind'], 'plan')
        self.assertEqual(result['completion']['status'], 'internal_work_remaining')
        self.assertFalse(result['completion']['user_acceptance_claimed'])
