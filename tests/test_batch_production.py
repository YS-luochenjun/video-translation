import copy
import contextlib
import io
import shutil
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from video_localizer import batches, budgets, common, model_tasks, production, timing, workflow
from video_localizer.common import WorkflowError, file_hash, read_json, write_json

PROJECT = Path(__file__).resolve().parents[1]


class BatchBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=PROJECT / 'work/test-tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.mp4'
        self.source.write_bytes(b'synthetic original')
        self.sha = file_hash(self.source)
        self.budget = budgets.open_request({'authority': 'user', 'authorization_ref': 'fixture-human-1',
            'user_request': 'Synthetic translation request', 'source': str(self.source), 'mode': 'first'}, self.root)
        self.runs = [self.root / 'runs' / name for name in ('batch-01', 'batch-02')]
        for run in self.runs:
            run.mkdir(parents=True)
            shutil.copyfile(self.source, run / 'source.mp4')
            write_json(run / 'run.json', {'source': 'source.mp4', 'source_sha256': self.sha})
            write_json(run / 'inputs/batch.json', {'id': 'batch'})
        self.record = {'id': 'batch', 'source_sha256': self.sha, 'members': [r.name for r in self.runs],
                       'pilot': self.runs[0].name, 'credit_limit': 60, 'state': 'pilot_pending', 'reservations': {}}
        self.path = self.root / 'state/batches/batch.json'
        write_json(self.path, self.record)

    def reserve(self, run, digest, credits):
        with patch.object(batches, 'gate'):
            return batches.reserve(run, digest, credits)

    def test_aggregate_reservation_prevents_per_locale_budget_multiplication(self):
        self.reserve(self.runs[0], 'a'*64, 40)
        with self.assertRaisesRegex(WorkflowError, 'Whole-request'):
            self.reserve(self.runs[1], 'b'*64, 21)
        self.reserve(self.runs[1], 'b'*64, 20)
        self.assertEqual(batches.status('batch', self.root)['remaining_estimated_credits'], 0)

    def test_orphan_reservation_and_removed_pointer_do_not_allow_duplicate_charge(self):
        self.reserve(self.runs[0], 'a'*64, 40)
        (self.runs[0] / 'inputs/batch.json').unlink()
        with self.assertRaisesRegex(WorkflowError, 'already reserved'):
            self.reserve(self.runs[0], 'a'*64, 40)
        with self.assertRaisesRegex(WorkflowError, 'Whole-request'):
            self.reserve(self.runs[1], 'b'*64, 21)

    def test_unknown_cost_stays_reserved_and_terminal_zero_releases_credit(self):
        run = self.runs[0]
        self.reserve(run, 'a'*64, 40)
        journal = run / 'jobs' / ('a'*64 + '.json')
        write_json(journal, {'id': 'a'*64, 'state': 'ambiguous', 'estimated_credits': 40, 'credits_consumed': 0})
        self.assertEqual(batches.status('batch', self.root)['reserved_or_billed_credits'], 40)
        write_json(journal, {'id': 'a'*64, 'state': 'fail', 'task_id': 'known', 'credits_consumed': 0})
        self.assertEqual(batches.status('batch', self.root)['reserved_or_billed_credits'], 0)

    def test_deleted_run_does_not_erase_settled_spend(self):
        run = self.runs[0]
        self.reserve(run, 'a'*64, 40)
        write_json(run / 'jobs' / ('a'*64 + '.json'), {'id': 'a'*64, 'state': 'success', 'credits_consumed': 32})
        batches.sync(run)
        # Explicitly scoped synthetic fixture deletion, not a project media cleanup.
        shutil.rmtree(run)
        self.assertEqual(batches.status('batch', self.root)['reserved_or_billed_credits'], 32)

    def test_actual_over_estimate_blocks_next_job(self):
        run = self.runs[0]
        self.reserve(run, 'a'*64, 20)
        write_json(run / 'jobs' / ('a'*64 + '.json'), {'id': 'a'*64, 'state': 'success', 'credits_consumed': 64})
        with self.assertRaisesRegex(WorkflowError, 'Whole-request'):
            self.reserve(self.runs[1], 'b'*64, 1)

    def test_unregistered_journal_and_concurrent_lock_fail_closed(self):
        with common.lock(self.root / 'state/budgets/.lock'):
            with self.assertRaisesRegex(WorkflowError, 'locked'):
                self.reserve(self.runs[0], 'a'*64, 1)
        write_json(self.runs[0] / 'jobs' / ('f'*64 + '.json'), {'id': 'f'*64})
        with self.assertRaisesRegex(WorkflowError, 'Whole-request'):
            self.reserve(self.runs[0], 'a'*64, 1)

    def test_pilot_and_master_change_revoke_batch_release(self):
        with self.assertRaisesRegex(WorkflowError, 'representative language'):
            batches.gate(self.runs[1])
        snapshot = {'plan_id': 'v1', 'video_sha256': 'v1', 'review_sha256': 'r1',
                    'masters': [{'start': 0, 'end': 1, 'sha256': 'master'}]}
        self.record['pilot_release'] = copy.deepcopy(snapshot)
        write_json(self.path, self.record)
        with patch.object(batches, '_pilot_snapshot', return_value=snapshot):
            batches.gate(self.runs[1], {'segments': [{'start': 0, 'end': 1, 'prepared_video': {'sha256': 'master'}}]})
            with self.assertRaisesRegex(WorkflowError, 'master differs'):
                batches.gate(self.runs[1], {'segments': []})
            snapshot['video_sha256'] = 'new-output'
            with self.assertRaisesRegex(WorkflowError, 'Pilot changed'):
                batches.gate(self.runs[1])

    def test_direct_render_checks_batch_before_media_work(self):
        with patch.object(workflow, 'current_plan', return_value={'segments': []}):
            with self.assertRaisesRegex(WorkflowError, 'representative language'):
                workflow.render(self.runs[1])

    def test_fast_pilot_uses_current_basic_review_without_claiming_strict_audit(self):
        pilot = self.runs[0]
        write_json(pilot / 'outputs/candidate.json', {'sha256': 'e' * 64, 'plan_id': 'p1'})
        write_json(pilot / 'review/review.json', {'reviewer': 'fixture'})
        quality = {'decision': 'pass', 'scope': 'fast-basic', 'review_sha256': 'review-v1'}
        with patch.object(workflow, 'current_plan', return_value={
                'id': 'p1', 'mode': 'fast', 'source_sha256': self.sha, 'segments': []}), \
                patch.object(workflow, 'quality', return_value=quality):
            snapshot = batches._pilot_snapshot(self.record, self.root)
            self.assertEqual(snapshot['text_visual_audit'], {
                'scope': 'fast-basic', 'decision': 'pass', 'review_sha256': 'review-v1'})
            quality['decision'] = 'revise'
            with self.assertRaisesRegex(WorkflowError, 'has not passed'):
                batches._pilot_snapshot(self.record, self.root)
            quality.update(decision='pass', review_sha256=None)
            with self.assertRaisesRegex(WorkflowError, 'current basic review'):
                batches._pilot_snapshot(self.record, self.root)

    def test_model_task_budget_blocks_before_any_provider_call(self):
        run = self.runs[0]
        self.reserve(run, 'a'*64, 60)
        data = {'payload': {'model': 'google/gemini-2-5-pro-tts'}, 'estimated_credits': 1}
        client = Mock()
        with patch.object(model_tasks, 'packet', return_value=data), patch.object(workflow, 'execution_limits', return_value={
                'max_paid_jobs_per_run': 2, 'max_estimated_credits_per_run': 60}):
            with self.assertRaisesRegex(WorkflowError, 'Whole-request'):
                model_tasks.submit(run, 'input.json', client=client)
        self.assertEqual(client.mock_calls, [])

    def test_paid_invalid_json_counts_received_charge(self):
        self.assertEqual(workflow.reserved_credits({'state': 'response_invalid', 'credits_consumed': 3,
                                                   'estimated_credits': 20}, 60), 3)

    def test_video_and_audio_analysis_share_the_same_batch_guard(self):
        run = self.runs[0]
        self.reserve(run, 'a'*64, 60)
        limits = {'max_paid_jobs_per_run': 2, 'max_estimated_credits_per_run': 60}
        client = Mock()
        packet = {'payload': {'model': 'wan/2-7-videoedit'}, 'estimated_credits': 1}
        with patch.object(workflow, 'prepare_packet', return_value=packet), patch.object(workflow, 'current_plan',
                return_value={'segments': [{'id': 's001'}]}), patch.object(workflow, 'execution_limits', return_value=limits):
            with self.assertRaisesRegex(WorkflowError, 'Whole-request'):
                workflow.submit(run, 's001', client)
        write_json(run / 'analysis/audio.wav', {'synthetic': True})
        with patch.object(workflow, 'source_path', return_value=run / 'analysis/audio.wav'), \
                patch.object(workflow.media, 'probe', return_value={'has_audio': True}), \
                patch.object(workflow, 'execution_limits', return_value=limits):
            with self.assertRaisesRegex(WorkflowError, 'Whole-request'):
                workflow.analyze_audio(run, client)
        self.assertEqual(client.mock_calls, [])

    def test_restored_run_pointer_is_provenance_not_old_batch_authority(self):
        restored = self.root / 'runs/restored'
        write_json(restored / 'run.json', {'source_sha256': 'source'})
        write_json(restored / 'inputs/batch.json', {'id': 'batch', 'run': 'batch-01', 'origin_workspace': str(self.root)})
        self.assertIsNone(batches.binding(restored))
        self.assertIsNotNone(batches.binding(self.runs[0]))

    def test_authorization_is_not_transferred_to_another_workspace(self):
        write_json(self.root / 'config/kie-authorization.local.json', {
            'provider': 'KIE', 'automatic_use': True, 'source_quote': 'owner permission', 'workspace': str(self.root)})
        self.assertTrue(batches.authorization(self.root)['automatic_use'])
        value = read_json(self.root / 'config/kie-authorization.local.json')
        value['workspace'] = str(self.root / 'other')
        write_json(self.root / 'config/kie-authorization.local.json', value)
        self.assertFalse(batches.authorization(self.root)['automatic_use'])

    def test_create_batch_aliases_and_lower_reuse_limit(self):
        from video_localizer import languages
        write_json(self.root / 'config/workspace.json', {'max_paid_jobs_per_run': 2,
                   'max_estimated_credits_per_run': 60, 'max_estimated_credits_per_reused_run': 40})
        shutil.copyfile(PROJECT / 'config/language-aliases.json', self.root / 'config/language-aliases.json')
        source = self.root / 'fixture.mp4'; source.write_bytes(b'synthetic')
        initial = budgets.open_request({'authority': 'user', 'authorization_ref': 'fixture-initial',
            'user_request': 'First fixture', 'source': str(source), 'mode': 'first'}, self.root)
        budgets.open_request({'authority': 'user', 'authorization_ref': 'fixture-reuse', 'reuse_of': initial['id'],
            'reuse_confirmation': 'new_user_request', 'user_request': 'New fixture locale', 'source': str(source), 'mode': 'reuse'}, self.root)
        def create(video, language, brief, name):
            write_json(self.root / 'runs' / name / 'run.json', {'source_sha256': file_hash(video)})
        with patch.object(workflow, 'create_run', side_effect=create):
            result = batches.create('fresh', source, ['ja', 'ptbr'], 'fixture', True, self.root)
        self.assertEqual(result['credit_limit'], 40)
        self.assertEqual(len(result['members']), 2)


class TimingTests(unittest.TestCase):
    def test_nested_and_failed_stages_are_not_added_as_wall_time(self):
        with tempfile.TemporaryDirectory(dir=PROJECT / 'work/test-tmp') as tmp:
            run = Path(tmp) / 'runs/fixture'
            with timing.measure(run, 'outer'):
                with timing.measure(run, 'inner'):
                    pass
            with self.assertRaises(ValueError):
                with timing.measure(run, 'failure'):
                    raise ValueError('not stored: credential-like business text')
            result = timing.report([run])
            self.assertEqual(result['events'], 3)
            self.assertEqual(result['stages']['failure']['failures'], 1)
            self.assertGreaterEqual(result['stages']['outer']['inclusive_seconds'], result['stages']['inner']['inclusive_seconds'])
            self.assertLessEqual(result['observed_active_wall_seconds'], result['observed_span_seconds']+.0001)
            self.assertNotIn('credential-like', ''.join(p.read_text() for p in timing.directory(run).glob('*.json')))


class ProductionTests(unittest.TestCase):
    def batch_fixture(self, release=True):
        temp = tempfile.TemporaryDirectory(dir=PROJECT / 'work/test-tmp')
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        write_json(root / 'state/batches/fixture.json', {
            'id': 'fixture', 'pilot': 'es', 'members': ['es', 'pt', 'vi'],
            'pilot_release': {'scope': 'best_available'} if release else None})
        return root

    def test_best_available_locale_does_not_stop_remaining_deliveries(self):
        root = self.batch_fixture()
        rows = [{'run': 'es', 'state': 'delivered_with_issues'},
                {'run': 'pt', 'state': 'delivered'}, {'run': 'vi', 'state': 'delivered'}]
        with patch.object(batches, 'gate') as gate, patch.object(production, 'advance', side_effect=rows) as advance:
            result = production.advance_batch('fixture', deliver=True, root=root)
        self.assertEqual(advance.call_count, 3)
        self.assertEqual(gate.call_count, 3)
        self.assertEqual(result['state'], 'completed_with_issues')
        self.assertEqual(result['pending_runs'], [])
        self.assertFalse(result['quality_pass_claimed'])
        self.assertFalse(result['external_submission_claimed'])

    def test_one_language_error_or_pending_review_does_not_starve_other_languages(self):
        for failure in (WorkflowError('locale-specific evidence missing'), {'run': 'pt', 'state': 'needs_review'}):
            with self.subTest(failure=str(failure)):
                root = self.batch_fixture()
                with patch.object(batches, 'gate'), patch.object(production, 'advance', side_effect=[
                        {'run': 'es', 'state': 'delivered'}, failure, {'run': 'vi', 'state': 'delivered'}]) as advance:
                    result = production.advance_batch('fixture', deliver=True, root=root)
                self.assertEqual(advance.call_count, 3)
                self.assertEqual(result['state'], 'needs_attention')
                self.assertEqual(result['pending_runs'], ['pt'])

    def test_unreleased_pilot_remains_an_explicit_checkpoint(self):
        root = self.batch_fixture(release=False)
        with patch.object(batches, 'gate'), patch.object(production, 'advance', return_value={
                'run': 'es', 'state': 'delivered_with_issues'}) as advance:
            result = production.advance_batch('fixture', deliver=True, root=root)
        self.assertEqual(advance.call_count, 1)
        self.assertEqual(result['pending_runs'], ['pt', 'vi'])

    def test_changed_pilot_blocks_fast_expansion_before_advancing(self):
        root = self.batch_fixture()
        with patch.object(batches, 'gate', side_effect=[None, WorkflowError('Pilot changed'), WorkflowError('Pilot changed')]), \
                patch.object(production, 'advance', return_value={'run': 'es', 'state': 'delivered'}) as advance:
            result = production.advance_batch('fixture', deliver=True, root=root)
        self.assertEqual(advance.call_count, 1)
        self.assertEqual(result['pending_runs'], ['pt', 'vi'])

    def test_cli_waiting_states_are_not_reported_as_success(self):
        from video_localizer import cli
        with patch.object(cli, 'get_run', return_value=Path('fixture')), \
                patch.object(production, 'advance', return_value={'state': 'needs_review'}), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['production', 'fixture']), 2)
        with patch.object(production, 'advance_batch', return_value={'state': 'needs_attention'}), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['batch-run', 'fixture']), 2)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_synthetic_pipeline_keeps_rendered_bytes_and_resumes_without_encoding(self):
        from video_localizer import cli, demo, knowledge
        from workspace_fixture import copy_project_knowledge
        with tempfile.TemporaryDirectory(dir=PROJECT / 'work/test-tmp') as tmp, ExitStack() as stack:
            root = Path(tmp)
            for relative in ('config/workspace.json', 'config/quality.json', 'config/profiles/company-default/profile.json'):
                target = root / relative; target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(PROJECT / relative, target)
            copy_project_knowledge(PROJECT, root)
            for module in (common, cli, demo, knowledge, workflow, production):
                stack.enter_context(patch.object(module, 'ROOT', root))
            demo.create_demo('fixture', 'local_overlay', 1)
            run = root / 'runs/fixture'
            before = read_json(run / 'outputs/candidate.json')['sha256']
            first = production.advance(run)
            self.assertEqual(first['state'], 'needs_review')
            self.assertEqual(read_json(run / 'outputs/candidate.json')['sha256'], before)
            # Visual evidence creates this directory before capture. It must not
            # suppress overview/audio capture, and resume must reuse both.
            captured = run / 'review' / before[:12]
            base_files = [captured / name for name in ('frame-00001.jpg', 'contact-sheet.jpg', 'audio.wav')]
            self.assertTrue(all(p.is_file() for p in base_files))
            stamps = {p: (p.stat().st_mtime_ns, file_hash(p)) for p in base_files}
            write_json(run / 'inputs/visual-audit/unsubmitted-note.json', {'notes':'Draft observations, not production inputs'})
            with patch.object(workflow, 'render', side_effect=AssertionError('Repeated encoding')):
                second = production.advance(run)
                self.assertTrue(second['render_reused'])
                self.assertEqual(second['state'], 'needs_review')
            self.assertEqual(stamps, {p: (p.stat().st_mtime_ns, file_hash(p)) for p in base_files})
            # Removing one generated asset requires just that missing asset,
            # without rebuilding overview frames or modifying the candidate.
            (captured / 'audio.wav').unlink()
            cli.capture(run)
            self.assertTrue((captured / 'audio.wav').is_file())
            self.assertEqual(stamps[base_files[0]], (base_files[0].stat().st_mtime_ns, file_hash(base_files[0])))
            self.assertEqual(read_json(run / 'outputs/candidate.json')['sha256'], before)
            self.assertFalse((run / 'outputs/delivery.json').exists())

    def test_stale_explicit_plan_stops_without_silently_selecting_new_route(self):
        with tempfile.TemporaryDirectory(dir=PROJECT / 'work/test-tmp') as tmp:
            run = Path(tmp) / 'runs/fixture'
            write_json(run / 'analysis/inventory.json', {})
            write_json(run / 'plan.json', {'experiment': 'model_edit'})
            with patch.object(workflow, 'current_plan', side_effect=WorkflowError('Inventory changed')), \
                    patch.object(workflow, 'build_plan') as build, patch.object(workflow, 'render') as render:
                with self.assertRaisesRegex(WorkflowError, 'Inventory changed'):
                    production.advance(run)
                build.assert_not_called(); render.assert_not_called()

    def test_resume_skips_only_render_and_never_skips_quality(self):
        from video_localizer import cli
        with tempfile.TemporaryDirectory(dir=PROJECT / 'work/test-tmp') as tmp:
            run = Path(tmp) / 'runs/fixture'
            write_json(run / 'analysis/inventory.json', {})
            (run / 'outputs').mkdir()
            (run / 'outputs/final.mp4').write_bytes(b'fixture')
            candidate = {'plan_id': 'p', 'path': 'outputs/final.mp4', 'sha256': file_hash(run / 'outputs/final.mp4')}
            write_json(run / 'outputs/candidate.json', candidate)
            write_json(run / 'outputs/production-checkpoint.json', {'fingerprint': 'f', 'video_sha256': candidate['sha256']})
            with patch.object(workflow, 'build_plan'), patch.object(workflow, 'current_plan', return_value={
                    'id': 'p', 'source_sha256': 'a'*64, 'segments': []}), patch.object(production, '_fingerprint', return_value='f'), \
                    patch.object(workflow, 'render') as render, patch.object(cli, 'capture') as capture, \
                    patch.object(workflow, 'quality', return_value={'decision': 'revise'}) as quality, \
                    patch('video_localizer.visual_audit.generate', return_value={'automatic_pass': False}), \
                    patch.object(workflow, 'deliver') as deliver:
                result = production.advance(run, deliver=True)
                self.assertTrue(result['render_reused'])
                self.assertEqual(result['state'], 'needs_review')
                render.assert_not_called(); capture.assert_called_once(); quality.assert_called_once(); deliver.assert_not_called()
                (run / 'outputs/final.mp4').write_bytes(b'tampered')
                production.advance(run)
                render.assert_called_once()


if __name__ == '__main__':
    unittest.main()
