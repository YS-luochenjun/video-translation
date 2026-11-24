import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_localizer import batches, cli, work_packet, knowledge, plan_inputs, workflow
from video_localizer.common import WorkflowError, file_hash, read_json, write_json


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

    def test_checkpoint_repeats_gates_only_and_reloads_on_state_change(self):
        first = work_packet.build(self.run, checkpoint=True)
        token = first['packet_checkpoint']['token']
        delta = work_packet.build(self.run, since=token)
        self.assertEqual(delta['packet_checkpoint']['mode'], 'delta')
        self.assertIn('knowledge', delta['packet_checkpoint']['unchanged_sections'])
        self.assertNotIn('knowledge', delta)
        self.assertIn('text_timing', delta['packet_checkpoint']['unchanged_sections'])
        self.assertNotIn('text_timing', delta)
        self.assertEqual(delta['blockers'], first['blockers'])
        self.assertEqual(delta['next_action'], first['next_action'])
        self.assertEqual(delta['automatic_pass'], first['automatic_pass'])
        self.inventory['coverage'].pop('speech')
        write_json(self.run / 'analysis/inventory.json', self.inventory)
        refreshed = work_packet.build(self.run, since=token)
        self.assertEqual(refreshed['packet_checkpoint']['mode'], 'full')
        self.assertIn('knowledge', refreshed)

    def test_checkpoint_returns_changed_diagnostics_and_resets_on_fast_candidate_change(self):
        result = {'run': self.run.name, 'stage_focus': {'stage': 'review'}, 'state_hint': 'needs_review',
                  'plan_id': 'fast-plan', 'improvement_loop': {'candidate_sha256': 'a' * 64},
                  'text_timing': {'risk_count': 0}, 'knowledge': [{'id': 'recorded-rule'}]}
        with patch.object(work_packet, '_build', side_effect=lambda *args: dict(result)):
            first = work_packet.build(self.run, checkpoint=True)
            result['text_timing'] = {'risk_count': 1}
            changed = work_packet.build(self.run, since=first['packet_checkpoint']['token'])
            self.assertEqual(changed['packet_checkpoint']['mode'], 'delta')
            self.assertEqual(changed['text_timing'], {'risk_count': 1})
            self.assertNotIn('knowledge', changed)
            result['improvement_loop'] = {'candidate_sha256': 'b' * 64}
            new_video = work_packet.build(self.run, since=changed['packet_checkpoint']['token'])
            self.assertEqual(new_video['packet_checkpoint']['mode'], 'full')
            self.assertEqual(new_video['knowledge'], result['knowledge'])
            self.assertEqual(new_video['text_timing'], result['text_timing'])

    def test_work_packet_shares_navigation_reads_and_reloads_review_data_on_resume(self):
        root = self.run.parent.parent
        progress = root / 'state/review-progress' / self.run.name / 'manifest.json'
        write_json(progress, {'reviewed': []})
        inventory = self.run / 'analysis/inventory.json'
        quality = self.run / 'outputs/quality.json'
        write_json(quality, {'failures': []})
        with patch.object(work_packet, 'read_json', wraps=read_json) as load:
            first = work_packet.build(self.run, checkpoint=True)
        for path in (inventory, quality):
            self.assertEqual(load.call_args_list.count(((path,), {})), 1)
        write_json(progress, {'reviewed': ['headline']})
        write_json(quality, {'failures': ['listen to the ending']})
        with patch.object(work_packet.resources, 'status', return_value={'free_bytes': 1024**3}):
            delta = work_packet.build(self.run, since=first['packet_checkpoint']['token'])
            fresh = work_packet.build(self.run)
        merged = {**first, **delta}
        checkpoint = merged.pop('packet_checkpoint')
        for key in checkpoint['removed_sections']:
            merged.pop(key, None)
        self.assertEqual(checkpoint['mode'], 'delta')
        self.assertEqual(merged, fresh)
        self.assertEqual(delta['review_cursor'][0]['instances'], {'reviewed': ['headline']})
        self.assertEqual(delta['quality_failures'], ['listen to the ending'])
        self.assertEqual(delta['improvement_loop']['quality_record']['failures'], delta['quality_failures'])

    def test_work_packet_hashes_actual_source_once_before_planning_and_rejects_a_change(self):
        source = self.run / 'source.mp4'
        with patch.object(workflow, 'file_hash', wraps=file_hash) as digest:
            work_packet.build(self.run)
        digest.assert_called_once_with(source)
        source.write_bytes(b'changed')
        with self.assertRaisesRegex(WorkflowError, 'Source changed'):
            work_packet.build(self.run)

    def test_unchanged_plan_inputs_share_only_frozen_bytes(self):
        source = self.run / 'inputs/request.json'
        plan_inputs.freeze(self.run, 'first', 'request.json', source)
        plan_inputs.freeze(self.run, 'second', 'request.json', source)
        first = self.run / 'plans/first/inputs/request.json'
        second = self.run / 'plans/second/inputs/request.json'
        self.assertTrue(first.samefile(second))
        self.assertFalse(first.samefile(source))
        write_json(source, {'target_language': 'fr'})
        plan_inputs.freeze(self.run, 'third', 'request.json', source)
        third = self.run / 'plans/third/inputs/request.json'
        self.assertEqual(read_json(second)['target_language'], 'en')
        self.assertEqual(read_json(third)['target_language'], 'fr')
        self.assertFalse(second.samefile(third))

    def test_batch_poll_journals_known_task_and_reports_missing_id_independently(self):
        missing, recorded = 'a' * 64, 'b' * 64
        write_json(self.run / 'jobs' / f'{missing}.json', {'id': missing, 'state': 'ambiguous'})
        path = self.run / 'jobs' / f'{recorded}.json'
        write_json(path, {'id': recorded, 'state': 'submitted', 'task_id': 'recorded-task-id'})
        with patch('video_localizer.batches.sync'), patch.object(workflow, 'KieClient') as client:
            client.return_value.status.return_value = {'state': 'generating', 'creditsConsumed': None}
            result = workflow.poll_batch(self.run, [missing, recorded, recorded])
            client.return_value.status.assert_called_once_with('recorded-task-id')
        self.assertEqual([item['state'] for item in result['jobs']], ['poll_error', 'generating'])
        self.assertEqual(read_json(path)['state'], 'generating')
        self.assertFalse(result['new_paid_submission'])

    def test_poll_pending_checks_multiple_runs_and_preserves_unknown_billing(self):
        root = self.run.parent.parent
        second = self.run.with_name('second')
        source_record = read_json(self.run / 'run.json')
        write_json(second / 'run.json', source_record)
        write_json(root / 'state/batches/example.json',
                   {'state': 'pilot_pending', 'source_sha256': source_record['source_sha256'],
                    'members': [self.run.name, 'missing', second.name]})
        pending, ambiguous, collected, uncollected = (letter * 64 for letter in 'abcd')

        def job(run, identity, state, **fields):
            path = run / 'jobs' / f'{identity}.json'
            write_json(path, {'id': identity, 'state': state, **fields})
            return path

        pending_path = job(self.run, pending, 'submitted', task_id='pending-task')
        unknown_path = job(self.run, ambiguous, 'ambiguous', estimated_credits=3)
        job(second, collected, 'success', task_id='old-task', result='outputs/collected.mp4', credits_consumed=0.4)
        uncollected_path = job(second, uncollected, 'success', task_id='uncollected-task',
                               credits_consumed=0.8, task_result_kind='audio')

        def provider(task_id):
            if task_id == 'pending-task':
                return {'state': 'generating'}
            return {'state': 'success', 'creditsConsumed': 0.8}

        def collect(run, record, urls):
            record['result'] = 'outputs/recovered.wav'

        with (patch.object(workflow, 'KieClient') as client, patch('video_localizer.batches.sync') as sync,
              patch.object(workflow, 'result_urls', return_value=['https://example.invalid/recovered']),
              patch('video_localizer.model_tasks.collect', side_effect=collect)):
            client.return_value.status.side_effect = provider
            result = batches.poll_pending('example', root)
            self.assertEqual([call.args[0] for call in client.return_value.status.call_args_list],
                             ['pending-task', 'uncollected-task'])
            client.return_value.create.assert_not_called()
            client.return_value.upload.assert_not_called()
            self.assertEqual([call.args[0] for call in sync.call_args_list], [self.run, second])

        self.assertEqual(result['runs_in_batch'], 3)
        self.assertEqual([(item['run'], item['state']) for item in result['jobs']],
                         [('recovery', 'generating'), ('second', 'success')])
        self.assertEqual([item['state'] for item in result['attention']], ['ambiguous', 'run_error'])
        self.assertFalse(result['new_paid_submission'])
        self.assertEqual(read_json(unknown_path), {'id': ambiguous, 'state': 'ambiguous', 'estimated_credits': 3})
        self.assertEqual(read_json(pending_path)['state'], 'generating')
        self.assertEqual(read_json(uncollected_path)['result'], 'outputs/recovered.wav')

    def test_pending_only_rechecks_journal_before_query(self):
        job_id = 'e' * 64
        write_json(self.run / 'jobs' / f'{job_id}.json',
                   {'id': job_id, 'state': 'success', 'task_id': 'finished-elsewhere',
                    'credits_consumed': 0, 'result': 'outputs/completed.mp4'})
        with patch.object(workflow, 'KieClient') as client:
            result = workflow.poll_batch(self.run, [job_id], pending_only=True)
            client.return_value.status.assert_not_called()
        self.assertTrue(result['jobs'][0]['skipped'])
        self.assertEqual(result['jobs'][0]['credits_consumed'], 0)

    def test_fast_status_checks_the_fast_review_and_current_candidate(self):
        plan = {'id': 'p', 'mode': 'fast'}
        write_json(self.run / 'plan.json', plan)
        movie = self.run / 'outputs/final.mp4'
        movie.parent.mkdir(parents=True)
        movie.write_bytes(b'actual localized candidate')
        sha = file_hash(movie)
        write_json(self.run / 'outputs/candidate.json', {'plan_id': 'p', 'sha256': sha, 'mode': 'fast'})
        review = self.run / 'review/fast-review.json'
        write_json(review, {'video_sha256': sha})
        write_json(self.run / 'outputs/quality.json', {'decision': 'pass', 'plan_id': 'p',
                   'video_sha256': sha, 'review_sha256': file_hash(review), 'scope': 'fast-basic'})
        with patch('video_localizer.workflow.current_plan', return_value=plan):
            self.assertEqual(cli.status(self.run)['state'], 'ready_to_deliver')
            with patch('video_localizer.quality_holds.active', return_value=[{'id': 'user-objection'}]):
                self.assertEqual(cli.status(self.run)['state'], 'quality_feedback_requires_revision')
            write_json(review, {'changed': True})
            self.assertEqual(cli.status(self.run)['state'], 'needs_review')

    def test_old_completion_does_not_hide_a_new_candidate(self):
        movie = self.run / 'outputs/final.mp4'
        movie.parent.mkdir(parents=True)
        movie.write_bytes(b'bounded final')
        write_json(self.run / 'outputs/completion.json', {'video_sha256': file_hash(movie),
                   'candidate_sha256_at_completion': 'a' * 64})
        candidate = self.run / 'outputs/candidate.json'
        write_json(candidate, {'sha256': 'a' * 64})
        self.assertEqual(cli.status(self.run)['state'], 'delivered_with_issues')
        write_json(candidate, {'sha256': 'c' * 64})
        self.assertEqual(cli.status(self.run)['state'], 'needs_review')

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
