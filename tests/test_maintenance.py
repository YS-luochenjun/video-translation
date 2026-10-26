import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_localizer import maintenance
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
