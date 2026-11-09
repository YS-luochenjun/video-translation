import json
import os
import shutil
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from video_localizer import common, project_storage
from video_localizer.common import CODE_ROOT, WorkflowError, read_json, write_json


class StorageLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('delivery-policy.json', 'storage-policy.json', 'maintenance.json'):
            target = self.root / 'config' / name
            target.parent.mkdir(exist_ok=True)
            shutil.copyfile(CODE_ROOT / 'config' / name, target)
        write_json(self.root / 'config/storage-authorization.local.json', {
            'workspace': str(self.root.resolve()), 'automatic_cleanup': True,
            'reset_existing_data': False, 'source_quote': 'Synthetic fixture only'})
        write_json(self.root / 'knowledge/index.json', {'entries': []})
        write_json(self.root / 'knowledge/cases/index.json', {'entries': []})
        self.now = datetime.now(timezone.utc)

    def run_folder(self, name, state='created', source='a' * 64):
        run = self.root / 'runs' / name
        write_json(run / 'run.json', {'id': name, 'state': state, 'source_sha256': source})
        return run

    def close(self, name, hours=25):
        run = self.run_folder(name)
        write_json(run / 'outputs/delivery.json', {'sha256': 'b' * 64})
        write_json(self.root / 'state/storage-closed' / (name + '.json'), {
            'video_sha256': 'b' * 64, 'closed_at': (self.now - timedelta(hours=hours)).isoformat()})
        return run

    def age(self, path, days):
        stamp = (self.now - timedelta(days=days)).timestamp()
        for item in sorted(path.rglob('*'), reverse=True):
            os.utime(item, (stamp, stamp))
        os.utime(path, (stamp, stamp))

    def file(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
        return path

    def plan(self):
        return project_storage.preview(self.root, now=self.now)

    def paths(self):
        return {row['path'] for row in self.plan()['selected']}

    def test_disappearing_scratch_during_capacity_scan_is_not_a_failed_sweep(self):
        gone = self.root / 'work/tmp/finished-test'
        gone.mkdir(parents=True)
        live = self.file('work/tmp/current.txt', b'keep current scratch')
        original = Path.lstat
        def disappearing(path, *args, **kwargs):
            if path == gone:
                if path.exists():
                    path.rmdir()
                raise FileNotFoundError(2, 'Synthetic vanished directory', str(path))
            return original(path, *args, **kwargs)
        with patch.object(Path, 'lstat', autospec=True, side_effect=disappearing):
            plan = self.plan()
        self.assertFalse(gone.exists())
        self.assertEqual(plan['selected'], [])
        self.assertFalse(plan['pressure'])
        self.assertTrue(live.exists())
        def denied(path, *args, **kwargs):
            if path == live:
                raise PermissionError('Keep real I/O failures visible')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'lstat', autospec=True, side_effect=denied):
            with self.assertRaises(PermissionError):
                self.plan()

    def test_closed_grace_period_and_matching_scratch(self):
        self.close('recent', 12)
        self.close('old', 25)
        (self.root / 'work/runs/old').mkdir(parents=True)
        self.assertNotIn('runs/recent', self.paths())
        self.assertIn('runs/old', self.paths())
        self.assertIn('work/runs/old', self.paths())

    def test_empty_receipt_retains_owner_and_dependencies_only(self):
        self.close('ready')
        self.close('needed')
        self.close('missing')
        write_json(self.root / 'runs/missing/input.json', {'asset': 'runs/needed/base.mp4'})
        gap = 'runs/missing/analysis/receipt.json'
        self.file(gap, b' \n')
        plan = self.plan()
        self.assertEqual([row['path'] for row in plan['selected']], ['runs/ready'])
        self.assertIn({'path': 'runs/missing', 'reason': 'unreadable_json_receipt',
                       'receipts': [gap]}, plan['retained'])
        result = project_storage.execute(self.root, plan['fingerprint'], now=self.now)
        self.assertEqual([row['path'] for row in result['deleted']], ['runs/ready'])
        self.assertTrue((self.root / gap).exists())
        self.assertTrue((self.root / 'runs/needed').is_dir())

    def test_live_cross_run_reference_keeps_producer(self):
        self.close('old')
        live = self.run_folder('live')
        write_json(live / 'custom/dependency.json', {'asset': 'runs/old/outputs/base.mp4'})
        self.assertNotIn('runs/old', self.paths())

    def test_transitive_dependency_keeps_entire_producer_chain(self):
        self.close('first')
        second = self.close('second')
        live = self.run_folder('live')
        write_json(second / 'dependency.json', {'asset': 'runs/first/outputs/base.mp4'})
        write_json(live / 'dependency.json', {'asset': 'runs/second/outputs/base.mp4'})
        self.assertFalse({'runs/first', 'runs/second'} & self.paths())

    def test_idle_media_evicted_only_without_live_source(self):
        source = self.root / 'media' / ('a' * 64)
        source.mkdir(parents=True)
        (source / 'data.wav').write_bytes(b'cached')
        self.age(source, 8)
        self.assertIn(source.relative_to(self.root).as_posix(), self.paths())
        self.run_folder('live')
        self.assertNotIn(source.relative_to(self.root).as_posix(), self.paths())

    def test_actual_media_reuse_extends_idle_clock(self):
        source = self.root / 'media' / ('a' * 64)
        source.mkdir(parents=True)
        self.age(source, 8)
        write_json(self.root / 'state/media-usage' / ('a' * 64 + '.json'),
                   {'last_used_at': self.now.isoformat()})
        self.assertNotIn(source.relative_to(self.root).as_posix(), self.paths())

    def test_terminal_idle_task_expires_but_quiet_unfinished_does_not(self):
        failed = self.run_folder('failed', 'failed')
        live = self.run_folder('quiet')
        self.age(failed, 8)
        self.age(live, 30)
        self.assertIn('runs/failed', self.paths())
        self.assertNotIn('runs/quiet', self.paths())

    def test_orphan_cache_requires_task_ownership(self):
        for name in ('registered', 'unknown'):
            path = self.root / 'work/runs' / name
            path.mkdir(parents=True)
            self.age(path, 2)
        write_json(self.root / 'state/maintenance/registered/scratch.json', {'files': {}})
        self.assertIn('work/runs/registered', self.paths())
        self.assertNotIn('work/runs/unknown', self.paths())

    def test_late_consumer_or_policy_change_invalidates_preview(self):
        self.close('old')
        live = self.run_folder('live')
        first = self.plan()
        write_json(live / 'dependency.json', {'asset': 'runs/old/base.mp4'})
        with self.assertRaisesRegex(WorkflowError, 'preview changed'):
            project_storage.execute(self.root, first['fingerprint'], now=self.now)
        self.assertTrue((self.root / 'runs/old').exists())
        second = self.plan()
        policy = read_json(self.root / 'config/maintenance.json')
        policy['media_idle_retention_days'] = 2
        write_json(self.root / 'config/maintenance.json', policy)
        with self.assertRaisesRegex(WorkflowError, 'preview changed'):
            project_storage.execute(self.root, second['fingerprint'], now=self.now)

    def test_missing_legacy_packages_reconciled_once_outside_outputs(self):
        entry = {'package': 'outputs/gone', 'source_sha256': 'a' * 64,
                 'target_language': 'ja', 'video_sha256': 'b' * 64,
                 'archived_at': self.now.isoformat()}
        write_json(self.root / 'outputs/index.json', {'entries': [entry]})
        plan = self.plan()
        project_storage.execute(self.root, plan['fingerprint'], now=self.now)
        saved = read_json(self.root / 'state/delivery-index.json')['entries'][0]
        self.assertEqual(saved['expiry_reason'], 'missing_before_sweep')
        self.assertFalse((self.root / 'outputs/index.json').exists())
        self.assertEqual(self.plan()['unavailable_entries'], [])

    def test_resuming_closed_task_revokes_old_close_qualification(self):
        run = self.close('resumed')
        with common.run_operation(run):
            write_json(run / 'analysis/new-plan.json', {'stage': 'translation'})
        self.assertFalse((self.root / 'state/storage-closed/resumed.json').exists())
        self.assertNotIn('runs/resumed', self.paths())
        saved = read_json(self.root / 'state/storage-activity/resumed.json')
        self.assertIn('previous_close', saved)

    def test_processing_remote_job_keeps_old_closed_task(self):
        run = self.close('remote')
        write_json(run / 'jobs/new.json', {'state': 'processing'})
        self.assertNotIn('runs/remote', self.paths())

    def test_out_of_band_production_change_invalidates_old_close(self):
        run = self.close('external')
        marker = self.root / 'state/storage-closed/external.json'
        stamp = (self.now - timedelta(hours=25)).timestamp()
        os.utime(marker, (stamp, stamp))
        write_json(run / 'analysis/new-plan.json', {'stage': 'translation'})
        self.assertNotIn('runs/external', self.paths())

    def test_resumed_failed_state_does_not_expire_as_old_terminal_work(self):
        run = self.run_folder('resumed-failure', 'failed')
        self.age(run, 8)
        with common.run_operation(run):
            pass
        future = self.now + timedelta(days=9)
        plan = project_storage.preview(self.root, now=future)
        self.assertNotIn('runs/resumed-failure', {r['path'] for r in plan['selected']})

    def test_unresolved_provider_jobs_keep_terminal_task(self):
        for index, state in enumerate(('waiting', 'queuing', 'generating', 'submitting', 'ambiguous', 'unknown', 'future_state')):
            with self.subTest(state=state):
                name = 'provider-' + str(index)
                run = self.run_folder(name, 'failed')
                write_json(run / 'jobs/paid.json', {'state': state, 'task_id': 'synthetic-task'})
                self.age(run, 8)
                self.assertNotIn('runs/' + name, self.paths())

    def test_known_terminal_job_does_not_keep_idle_failed_task(self):
        run = self.run_folder('settled', 'failed')
        write_json(run / 'jobs/paid.json', {'state': 'success', 'actual_credits': None})
        self.age(run, 8)
        self.assertIn('runs/settled', self.paths())

    def test_live_presentation_reference_keeps_expired_package(self):
        relative = 'outputs/.packages/REQ/ja/source-1/old'
        video = self.file(relative + '/final.mp4', b'formal-result')
        write_json(self.root / relative / 'manifest.json', {'fixture': True})
        presentation = 'outputs/REQ/ja/source-1/final.mp4'
        self.file(presentation, video.read_bytes())
        write_json(self.root / 'state/delivery-index.json', {'entries': [{
            'package': relative, 'presentation': presentation,
            'video_sha256': common.file_hash(video), 'source_sha256': 'b' * 64, 'target_language': 'ja',
            'requirement_name': 'REQ', 'task_name': 'source-1',
            'archived_at': (self.now - timedelta(days=20)).isoformat()}]})
        consumer = self.run_folder('consumer')
        for reference in (presentation, str(self.root / presentation), presentation.replace('/', chr(92))):
            with self.subTest(reference=reference):
                write_json(consumer / 'inputs/reference.json', {'video': reference})
                plan = project_storage.preview(self.root, now=self.now)
                self.assertNotIn(relative, {row['path'] for row in plan['selected']})
                self.assertIn({'path': relative, 'reason': 'referenced_by_live_task'}, plan['retained'])
        project_storage.execute(self.root, plan['fingerprint'], now=self.now)
        self.assertEqual((self.root / presentation).read_bytes(), b'formal-result')
        self.assertTrue((self.root / relative / 'manifest.json').exists())

    def test_run_rechecks_sweep_lock_after_acquiring_own_lock(self):
        run = self.run_folder('live')
        original = common.lock

        @contextmanager
        def delayed(path):
            write_json(self.root / 'state/project-storage.lock', {'synthetic': True})
            with original(path):
                yield

        with patch.object(common, 'lock', delayed):
            with self.assertRaisesRegex(WorkflowError, 'storage maintenance'):
                with common.run_operation(run):
                    self.fail('Producer entered during a sweep')
        self.assertFalse((self.root / 'runs/.locks/live.lock').exists())

    def test_new_run_rechecks_sweep_lock_after_admission(self):
        from video_localizer import workflow
        original = common.lock

        @contextmanager
        def delayed(path):
            write_json(self.root / 'state/project-storage.lock', {'synthetic': True})
            with original(path):
                yield

        with patch.object(workflow, 'ROOT', self.root), patch.object(workflow, 'lock', delayed), patch.object(workflow, '_create_run') as create:
            with self.assertRaisesRegex(WorkflowError, 'storage maintenance'):
                workflow.create_run('unused.mp4', 'ja', '', 'new')
        create.assert_not_called()
