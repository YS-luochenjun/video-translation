import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_localizer import knowledge, maintenance
from video_localizer.common import WorkflowError, file_hash, guarded, read_json, write_json


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.run = self.root / 'runs/example'
        write_json(self.run / 'run.json', {})
        write_json(self.root / 'config/maintenance.json', {'enabled': True,
                   'automatic_empty_directories': True,
                   'automatic_registered_cache_after_delivery': True,
                   'close_run_after_preservation': True})

    def delivery(self):
        video = self.run / 'outputs/final.mp4'
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b'final')
        write_json(self.run / 'outputs/delivery.json', {'video': 'outputs/final.mp4', 'sha256': file_hash(video)})

    def scratch(self):
        path = self.root / 'work/runs/example/cache.bin'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'rebuildable')
        maintenance.register(self.run, path.relative_to(self.root), 'Recreate from source')
        return path

    def test_recover_exact_accepted_delivery_only(self):
        from video_localizer import bundles
        source = 'a' * 64
        code = 'MOG-20261125-001'
        material = '12345678-1234-1234-1234-123456789abc'
        write_json(self.root / 'config/storage-authorization.local.json', {
            'workspace': str(self.root.resolve()), 'automatic_cleanup': True})
        write_json(self.run / 'run.json', {'source_sha256': source})
        write_json(self.run / 'inputs/request.json', {'target_language': 'en'})
        self.delivery()
        digest = file_hash(self.run / 'outputs/final.mp4')
        folder = 'outputs/.packages/fixture'
        bundles.create(self.root / folder, 'delivery', digest,
                       {'final.mp4': self.run / 'outputs/final.mp4'},
                       {'source_sha256': source, 'target_language': 'en'})
        write_json(self.root / 'state/delivery-index.json', {'entries': [{
            'package': folder, 'origin_run_id': self.run.name, 'video_sha256': digest,
            'source_sha256': source, 'target_language': 'en'}]})
        request = {'code': code, 'requirement_id': material, 'content_version': 'v1',
                   'videos': [{'index': 1, 'members': [self.run.name], 'targets': ['en', 'es'],
                               'source': {'sha256': source}}]}
        request_path = self.root / 'state/fireplay' / code / 'request.json'
        write_json(request_path, request)
        outbox = {'state': 'returned', 'requirement_id': material, 'content_version': 'v1',
                  'video_index': 1, 'pending_locales': ['es'],
                  'packages': [{'package': folder, 'locale': 'en', 'sha256': digest}],
                  'operations': {'bind': {'state': 'verified', 'result': {'material_ids': [material]}},
                                 'import-1': {'state': 'verified', 'result': {'material_id': material}},
                                 'verify-1': {'state': 'verified'}}}
        outbox_path = request_path.with_name('return-1.json')
        write_json(outbox_path, outbox)
        with patch.object(maintenance, 'maintain', return_value={'state': 'closed_pending_lifecycle'}) as close:
            self.assertEqual(maintenance.recover_accepted_closures(self.root)['eligible'], ['example'])
            close.assert_not_called()
            self.assertEqual(maintenance.recover_accepted_closures(self.root, execute=True)['closed'], ['example'])
            close.assert_called_once()
            outbox['content_version'] = 'old'
            write_json(outbox_path, outbox)
            self.assertEqual(maintenance.recover_accepted_closures(self.root)['eligible'], [])
            outbox['content_version'] = 'v1'
            outbox['operations']['bind']['result']['material_ids'] = []
            write_json(outbox_path, outbox)
            self.assertEqual(maintenance.recover_accepted_closures(self.root)['eligible'], [])
            outbox['operations']['bind']['result']['material_ids'] = [material]
            write_json(outbox_path, outbox)
            write_json(self.run / 'outputs/candidate.json', {'sha256': 'c'*64})
            self.assertEqual(maintenance.recover_accepted_closures(self.root)['eligible'], [])

    def test_deferred_delivery_only_reflects_final_version_and_resumes_pending_work(self):
        self.delivery()
        video_sha = file_hash(self.run / 'outputs/final.mp4')
        queue_path = self.root / 'state/deferred-delivery/example.json'
        write_json(queue_path, {'run': 'example', 'video_sha256': video_sha,
                                'status': 'pending', 'tasks': ['reflect', 'source-save']})
        write_json(self.run / 'outputs/candidate.json', {'sha256': 'a' * 64})
        with patch('video_localizer.knowledge.reflect', return_value={'status': 'no_new_knowledge'}) as reflect:
            with patch('video_localizer.source_state.save', return_value={'id': 'saved'}) as save:
                first = maintenance.complete_deferred(self.run, self.root)
                self.assertEqual(first['results']['reflect']['state'], 'pending_evidence')
                reflect.assert_not_called()
                write_json(self.run / 'outputs/candidate.json', {'sha256': video_sha})
                complete = maintenance.complete_deferred(self.run, self.root)
                self.assertEqual(complete['status'], 'complete')
                self.assertEqual(maintenance.complete_deferred(self.run, self.root), complete)
                reflect.assert_called_once_with(self.run, self.root)
                save.assert_called_once_with(self.run, self.root)

    def test_fast_reflection_uses_receipts_for_empty_and_no_new_lessons(self):
        self.delivery()
        video_sha = file_hash(self.run / 'outputs/final.mp4')
        plan = {'id': 'plan', 'mode': 'fast', 'source_sha256': 'b' * 64}
        write_json(self.run / 'plan.json', plan)
        write_json(self.run / 'inputs/request.json', {'target_language': 'en'})
        write_json(self.run / 'outputs/candidate.json',
                   {'path': 'outputs/final.mp4', 'sha256': video_sha})
        review_path = self.run / 'review/fast-review.json'
        review = {'plan_id': 'plan', 'video_sha256': video_sha, 'reviewer': 'synthetic test', 'method': 'fixture'}
        quality_path = self.run / 'outputs/quality.json'
        quality = {'plan_id': 'plan', 'video_sha256': video_sha, 'decision': 'pass'}
        with patch('video_localizer.workflow.current_plan', return_value=plan):
            write_json(review_path, {**review, 'knowledge_no_new_reason': 'The existing timing method covered the observed behavior.'})
            write_json(quality_path, {**quality, 'review_sha256': file_hash(review_path)})
            receipt = knowledge.reflect(self.run, self.root)
            self.assertEqual(receipt['status'], 'no_new_knowledge')
            self.assertEqual(knowledge.reflect(self.run, self.root), receipt)
            self.assertTrue((self.root / receipt['receipt']).is_file())
            self.assertFalse((self.root / 'knowledge').exists())
            write_json(review_path, review)
            with self.assertRaisesRegex(WorkflowError, 'quality binding'):
                knowledge.reflect(self.run, self.root)
            write_json(quality_path, {**quality, 'review_sha256': file_hash(review_path)})
            ordinary = knowledge.reflect(self.run, self.root)
            self.assertEqual(ordinary['status'], 'recorded_without_lesson')
            self.assertEqual(knowledge.reflect(self.run, self.root), ordinary)
            self.assertIsNone(ordinary['candidate'])
            self.assertIsNone(ordinary['inbox'])
            self.assertFalse((self.root / 'knowledge').exists())
            write_json(review_path, {**review, 'lesson': 'Inspect transparent glyphs over footage during the first two frames.'})
            write_json(quality_path, {**quality, 'review_sha256': file_hash(review_path)})
            with patch('video_localizer.learning.capture_case', return_value=self.root / 'knowledge/local/fixture'):
                with patch('video_localizer.knowledge_usage.followup', return_value={}):
                    candidate = knowledge.reflect(self.run, self.root)
            self.assertEqual(candidate['reflection_state'], 'observed_candidate')
            self.assertTrue((self.root / candidate['candidate']).is_file())
            self.assertTrue((self.root / candidate['inbox']).is_file())

    def test_cache_waits_for_delivery_and_is_idempotent(self):
        cache = self.scratch()
        maintenance.maintain(self.run)
        self.assertTrue(cache.exists())
        self.delivery()
        package = self.root / 'outputs/package/final.mp4'
        package.parent.mkdir(parents=True)
        package.write_bytes(b'final')
        result = maintenance.maintain(self.run)
        self.assertEqual(len(result['deleted_cache']), 1)
        self.assertFalse(cache.exists())
        self.assertTrue(package.exists())
        self.assertEqual(maintenance.maintain(self.run)['deleted_cache'], [])

    def test_corrupt_records_report_all_errors_without_deletion(self):
        cache = self.scratch()
        self.delivery()
        bad = self.root / 'state/broken.json'
        bad.write_bytes(b'{"secret": invalid}')
        other = self.root / 'knowledge/empty.json'
        other.parent.mkdir(parents=True)
        other.write_bytes(b'')
        with patch('video_localizer.retention.preserve') as preserve:
            result = maintenance.maintain(self.run, close=True)
        self.assertEqual(result['state'], 'deferred')
        self.assertEqual(len(result['reference_scan_errors']), 2)
        self.assertEqual(result['deleted_cache'], [])
        self.assertTrue(cache.exists())
        self.assertEqual(bad.read_bytes(), b'{"secret": invalid}')
        self.assertNotIn('secret', str(result))
        preserve.assert_not_called()
        self.assertEqual(read_json(self.root / 'state/maintenance/example/latest.json'), result)

    def test_invalid_utf8_record_keeps_scratch(self):
        cache = self.scratch()
        self.delivery()
        (self.root / 'state/bad.txt').write_bytes(b'\xff')
        result = maintenance.maintain(self.run)
        self.assertEqual(result['reference_scan_errors'][0]['error_type'], 'UnicodeDecodeError')
        self.assertTrue(cache.exists())

    def test_reference_and_changed_bytes_are_kept(self):
        cache = self.scratch()
        self.delivery()
        write_json(self.root / 'outputs/package/manifest.json', {'path': cache.relative_to(self.root).as_posix()})
        self.assertEqual(maintenance.maintain(self.run)['state'], 'deferred')
        self.assertTrue(cache.exists())
        (self.root / 'outputs/package/manifest.json').unlink()
        cache.write_bytes(b'new')
        self.assertEqual(maintenance.maintain(self.run)['state'], 'deferred')
        self.assertTrue(cache.exists())

    def test_run_relative_reference_is_kept(self):
        cache = self.scratch()
        self.delivery()
        write_json(self.run / 'analysis/inventory.json', {'asset': '../../work/runs/example/cache.bin'})
        self.assertEqual(maintenance.maintain(self.run)['state'], 'deferred')
        self.assertTrue(cache.exists())

    def test_reference_scan_stops_when_every_candidate_must_be_kept(self):
        cache = self.scratch()
        reference = self.run / 'analysis/inventory.json'
        write_json(reference, {'path': cache.relative_to(self.root).as_posix()})
        with patch.object(Path, 'rglob', return_value=iter([reference])) as scan:
            result = maintenance._references(self.root, {
                cache.relative_to(self.root).as_posix(): {'sha256': file_hash(cache)}
            }, errors=[])
        self.assertEqual(result, {cache.relative_to(self.root).as_posix()})
        self.assertEqual(scan.call_count, 1)

    def test_reference_scan_checks_owning_run_before_unrelated_runs(self):
        cache = self.scratch()
        write_json(self.run / 'analysis/inventory.json', {
            'path': cache.relative_to(self.root).as_posix()
        })
        unrelated = self.root / 'runs/earlier/large.json'
        write_json(unrelated, {'unrelated': True})
        original_read = Path.read_text

        def read_without_unrelated(path, *args, **kwargs):
            self.assertNotEqual(path, unrelated)
            return original_read(path, *args, **kwargs)

        with patch.object(Path, 'read_text', read_without_unrelated):
            result = maintenance._references(self.root, {
                cache.relative_to(self.root).as_posix(): {'sha256': file_hash(cache)}
            }, errors=[])
        self.assertEqual(result, {cache.relative_to(self.root).as_posix()})

    def test_reference_scan_timeout_retains_every_candidate(self):
        cache = self.scratch()
        self.delivery()
        with patch('video_localizer.maintenance.time.monotonic', side_effect=[0, 31]):
            result = maintenance.maintain(self.run)
        self.assertEqual(result['state'], 'deferred')
        self.assertEqual(result['deleted_cache'], [])
        self.assertEqual(result['reference_scan_errors'][0]['error_type'], 'ReferenceScanTimeout')
        self.assertTrue(cache.exists())

    def test_unsettled_job_and_active_work_prevent_cleanup(self):
        cache = self.scratch()
        self.delivery()
        write_json(self.run / 'jobs/job.json', {'state': 'failed', 'estimated_credits': 10})
        self.assertEqual(maintenance.maintain(self.run, close=True)['state'], 'deferred')
        self.assertTrue(cache.exists())
        (self.run / 'jobs/job.json').unlink()
        path = self.root / 'state/resources/render.lock'
        path.parent.mkdir(parents=True)
        path.write_text('active')
        self.assertEqual(maintenance.maintain(self.run)['state'], 'deferred')
        self.assertTrue(cache.exists())

    def test_targets_outside_owned_scratch_rejected(self):
        for relative in ('outputs/final.mp4', '../outside', 'work/runs/other/file'):
            with self.assertRaises(WorkflowError):
                maintenance.register(self.run, relative, 'not ours')

    def test_closure_uses_current_preservation_fingerprint(self):
        self.delivery()
        with patch('video_localizer.retention.preserve') as preserve, patch('video_localizer.retention.delete') as delete:
            delete.side_effect = [{'decision': 'ready', 'fingerprint': 'current'}, {'status': 'deleted'}]
            result = maintenance.maintain(self.run, close=True)
        preserve.assert_called_once()
        self.assertEqual(delete.call_args.kwargs, {'execute': True, 'expected': 'current'})
        self.assertEqual(result['state'], 'retired')

    def test_guarded_stage_runs_hook_once_and_keeps_result(self):
        @guarded
        def inner(run):
            return 42
        @guarded
        def outer(run):
            return inner(run)
        with patch.object(maintenance, 'after_stage') as hook:
            self.assertEqual(outer(self.run), 42)
            self.assertEqual(hook.call_count, 1)

    def test_cleanup_error_is_reported_without_affecting_delivery(self):
        with patch.object(maintenance, 'maintain', side_effect=WorkflowError('changed')):
            maintenance.after_stage(self.run, 'finalization.finish')
        self.assertTrue(read_json(self.root / 'state/maintenance/example/latest.json')['delivery_unaffected'])

    def test_intermediate_stage_does_not_delete_cache_after_old_delivery(self):
        cache = self.scratch()
        self.delivery()
        maintenance.maintain(self.run, stage='workflow.render')
        self.assertTrue(cache.exists())

    def test_changed_delivery_is_not_a_cache_release_signal(self):
        cache = self.scratch()
        self.delivery()
        (self.run / 'outputs/final.mp4').write_bytes(b'changed')
        self.assertEqual(maintenance.maintain(self.run)['state'], 'deferred')
        self.assertTrue(cache.exists())

    def test_real_preservation_keeps_independent_package_after_run_retirement(self):
        from video_localizer import finalization, library
        self.delivery()
        source = self.run / 'inputs/source.mp4'
        source.parent.mkdir(parents=True)
        source.write_bytes(b'source fixture')
        write_json(self.run / 'run.json', {'id': 'example', 'source': 'inputs/source.mp4', 'source_sha256': file_hash(source)})
        write_json(self.root / 'config/workspace.json', {'output_policy': 'best_available_required'})
        write_json(self.root / 'knowledge/index.json', {'entries': []})
        write_json(self.run / 'inputs/request.json', {'target_language': 'ar'})
        write_json(self.run / 'analysis/inventory.json', {'text_instances': [], 'speech_segments': [], 'shots': []})
        evidence = self.run / 'review/observations.txt'
        evidence.parent.mkdir(parents=True)
        evidence.write_text('fixture observations')
        spec = {'source_sha256': file_hash(source), 'inventory_sha256': file_hash(self.run / 'analysis/inventory.json'),
                'request_sha256': file_hash(self.run / 'inputs/request.json'),
                'video': {'path': 'outputs/final.mp4', 'sha256': file_hash(self.run / 'outputs/final.mp4')},
                'reviewer': 'fixture', 'reason': 'bounded completion', 'text_ids': [], 'speech_ids': [],
                'speech_mode': 'no_speech', 'evidence': [{'path': 'review/observations.txt', 'sha256': file_hash(evidence)}],
                'assets': [], 'limitations': ['synthetic technical fixture']}
        write_json(self.run / 'review/finalization.json', spec)
        (self.run / 'outputs/delivery.json').unlink()
        with patch.object(finalization.media, 'probe', return_value={'duration': 4, 'width': 320, 'height': 480, 'fps': 30, 'has_audio': False}), patch.object(finalization.media, 'command'):
            finalization.finish(self.run)
        result = maintenance.maintain(self.run, close=True)
        self.assertEqual(result['state'], 'retired')
        self.assertFalse(self.run.exists())
        self.assertTrue(list((self.root / 'outputs').rglob('final.mp4')))
        self.assertTrue((self.root / 'state/maintenance/example/run-preview.json').is_file())
