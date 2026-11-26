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
        self.close('recent', 1)
        self.close('old', 25)
        (self.root / 'work/runs/old').mkdir(parents=True)
        self.assertNotIn('runs/recent', self.paths())
        self.assertIn('runs/old', self.paths())
        self.assertIn('work/runs/old', self.paths())

    def test_retired_experiment_requires_unchanged_summary_and_no_live_reference(self):
        experiment = self.file('work/replay/output.mp4', b'temporary test video')
        self.age(experiment.parent, 3)
        summary = self.file('work/state/replay-result.json', b'{"result":"complete"}')
        write_json(self.root / 'state/maintenance/retired-work.json', {'entries': [{
            'path': 'work/replay', 'summary': 'work/state/replay-result.json',
            'summary_sha256': common.file_hash(summary),
            'completed_at': (self.now - timedelta(days=2)).isoformat()}]})
        self.file('work/unregistered/output.mp4', b'keep')
        self.assertEqual(self.paths(), {'work/replay'})
        self.file('runs/unrelated/analysis/incomplete.json', b'{"broken":')
        self.assertIn('work/replay', self.paths())
        consumer = self.run_folder('consumer')
        write_json(consumer / 'input.json', {'asset': 'work/replay/output.mp4'})
        self.assertNotIn('work/replay', self.paths())
        (consumer / 'input.json').unlink()
        summary.write_bytes(b'changed')
        self.assertNotIn('work/replay', self.paths())

    def test_repeating_same_close_does_not_extend_retention_clock(self):
        run = self.run_folder('repeat')
        video = self.file('runs/repeat/outputs/final.mp4', b'final')
        write_json(run / 'outputs/delivery.json', {'sha256': common.file_hash(video), 'video': 'outputs/final.mp4'})
        project_storage.note_closed(run)
        marker = self.root / 'state/storage-closed/repeat.json'
        original = read_json(marker)
        stamp = marker.stat().st_mtime_ns
        project_storage.note_closed(run)
        self.assertEqual(read_json(marker), original)
        self.assertEqual(marker.stat().st_mtime_ns, stamp)

    def test_registered_local_trial_runs_retire_with_work_after_dependencies_clear(self):
        run = self.run_folder('trial')
        self.file('runs/trial/outputs/candidate.mp4', b'trial')
        orphan = self.file('runs/trial-orphan/outputs/final.mp4', b'trial orphan')
        experiment = self.file('work/replay/output.mp4', b'trial work')
        source_map = {'trial': 'a' * 64, 'trial-orphan': 'a' * 64}
        summary = self.root / 'work/state/replay-result.json'
        write_json(summary, {'run_sources': source_map})
        for folder in (run, orphan.parent.parent, experiment.parent):
            self.age(folder, 3)
        write_json(self.root / 'state/maintenance/retired-work.json', {'entries': [{
            'path': 'work/replay', 'summary': 'work/state/replay-result.json',
            'summary_sha256': common.file_hash(summary), 'run_sources': source_map,
            'completed_at': (self.now - timedelta(days=2)).isoformat()}]})
        consumer = self.run_folder('consumer', source='c' * 64)
        reference = consumer / 'inputs/reference.json'
        write_json(reference, {'asset': 'runs/trial/outputs/candidate.mp4'})
        self.assertEqual(self.paths(), {'runs/trial-orphan'})
        reference.unlink()
        with common.run_operation(consumer):
            plan = project_storage.scoped_preview(self.root, self.now)
            self.assertEqual({row['path'] for row in plan['selected']},
                             {'runs/trial', 'runs/trial-orphan', 'work/replay'})
            result = project_storage.scoped_execute(self.root, plan['fingerprint'], self.now)
        self.assertEqual(len(result['deleted']), 3)
        self.assertTrue(summary.is_file())
        self.assertTrue(consumer.is_dir())

    def test_registered_trials_do_not_override_production_or_unsettled_jobs(self):
        run = self.run_folder('trial')
        work = self.file('work/replay/output.mp4', b'trial')
        summary = self.root / 'work/state/replay-result.json'
        sources = {'trial': 'a' * 64}
        write_json(summary, {'run_sources': sources})
        registry = {'entries': [{
            'path': 'work/replay', 'summary': 'work/state/replay-result.json',
            'summary_sha256': common.file_hash(summary), 'run_sources': sources,
            'completed_at': (self.now - timedelta(days=2)).isoformat()}]}
        write_json(self.root / 'state/maintenance/retired-work.json', registry)
        self.age(work.parent, 3)
        self.age(run, 3)
        work.write_bytes(b'new trial activity')
        self.assertEqual(self.paths(), set())
        self.age(work.parent, 3)
        for path, receipt in [('inputs/fireplay.json', {'requirement_id': 'fixture'}),
                              ('jobs/queued.json', {'state': 'queued'}),
                              ('outputs/delivery.json', {'sha256': 'b' * 64})]:
            marker = run / path
            write_json(marker, receipt)
            self.age(run, 3)
            self.assertEqual(self.paths(), set())
            marker.unlink()
        self.age(run, 3)
        with common.run_operation(run):
            self.assertEqual(project_storage.scoped_preview(self.root, self.now)['selected'], [])

    def test_scoped_retired_experiment_reclaimed_during_unrelated_production(self):
        experiment = self.file('work/replay/output.mp4', b'temporary test video')
        self.age(experiment.parent, 3)
        summary = self.file('work/state/replay-result.json', b'{"result":"complete"}')
        write_json(self.root / 'state/maintenance/retired-work.json', {'entries': [{
            'path': 'work/replay', 'summary': 'work/state/replay-result.json',
            'summary_sha256': common.file_hash(summary),
            'completed_at': (self.now - timedelta(days=2)).isoformat()}]})
        active = self.run_folder('active')
        with common.run_operation(active):
            plan = project_storage.scoped_preview(self.root, self.now)
            self.assertEqual({row['path'] for row in plan['selected']}, {'work/replay'})
            reference = active / 'inputs/reference.json'
            write_json(reference, {'asset': 'work/replay/output.mp4'})
            with self.assertRaisesRegex(WorkflowError, 'Storage preview changed'):
                project_storage.scoped_execute(self.root, plan['fingerprint'], self.now)
            reference.unlink()
            plan = project_storage.scoped_preview(self.root, self.now)
            result = project_storage.scoped_execute(self.root, plan['fingerprint'], self.now)
            self.assertEqual([row['path'] for row in result['deleted']], ['work/replay'])
            self.assertTrue((self.root / 'runs/.locks/active.lock').exists())
        self.assertFalse(experiment.exists())
        self.assertTrue(summary.is_file())

    def test_scoped_sweep_reclaims_only_independent_closed_run_during_production(self):
        self.close('ready')
        self.close('referenced')
        self.close('same-source')
        write_json(self.root / 'runs/same-source/run.json', {'id': 'same-source', 'source_sha256': 'c' * 64})
        marker = self.root / 'state/storage-closed/same-source.json'
        os.utime(marker, None)
        active = self.run_folder('active', source='c' * 64)
        write_json(active / 'inputs/reference.json', {'path': 'runs/referenced/inputs/asset.mp4'})
        self.file('work/runs/ready/cache.bin', b'rebuildable scratch')
        with common.run_operation(active):
            plan = project_storage.scoped_preview(self.root, self.now)
            self.assertEqual({row['path'] for row in plan['selected']}, {'runs/ready', 'work/runs/ready'})
            result = project_storage.scoped_execute(self.root, plan['fingerprint'], self.now)
            self.assertEqual(len(result['deleted']), 2)
            self.assertTrue((self.root / 'runs/.locks/active.lock').exists())
        for name in ('active', 'referenced', 'same-source'):
            self.assertTrue((self.root / 'runs' / name).exists())
        self.assertFalse((self.root / 'runs/ready').exists())
        self.assertTrue((self.root / result['preserved_records'] / 'manifest.json').is_file())

    def test_scoped_sweep_rechecks_new_dependency_before_deletion(self):
        self.close('ready')
        active = self.run_folder('active', source='c' * 64)
        with common.run_operation(active):
            plan = project_storage.scoped_preview(self.root, self.now)
            write_json(active / 'inputs/reference.json', {'path': 'runs/ready/inputs/asset.mp4'})
            with self.assertRaisesRegex(WorkflowError, 'Storage preview changed'):
                project_storage.scoped_execute(self.root, plan['fingerprint'], self.now)
        self.assertTrue((self.root / 'runs/ready').exists())

    def test_post_deletion_knowledge_audit_does_not_block_production(self):
        from video_localizer import learning
        for scoped in (False, True):
            with self.subTest(scoped=scoped):
                run = self.close('ready')
                lock_path = self.root / 'state/project-storage.lock'
                preview = project_storage.scoped_preview if scoped else project_storage.preview
                execute = project_storage.scoped_execute if scoped else project_storage.execute
                plan = preview(self.root, now=self.now)
                observed = []

                def audit(root):
                    observed.append((lock_path.exists(), run.exists()))

                with patch.object(learning, 'audit', side_effect=audit):
                    result = execute(self.root, plan['fingerprint'], now=self.now)
                self.assertEqual(observed, [(True, True), (False, False)])
                self.assertGreaterEqual(result['global_lock_seconds'], 0)
                self.assertFalse(lock_path.exists())

    def test_closed_neutral_cache_keeps_reviewed_replacement_and_referenced_versions(self):
        run = self.close('recent', 1)
        original = self.file('runs/recent/outputs/local-repair/first/visual-master.mkv', b'old cache')
        replacement = self.file('runs/recent/outputs/reviewed.mkv', b'new reviewed')
        os.utime(original, (1, 1))
        asset = {'path': original.relative_to(run).as_posix(), 'sha256': common.file_hash(original)}
        write_json(original.with_name('preparation.json'), {
            'output': asset, 'source_sha256': 'a' * 64, 'approved_for_reuse': False,
            'contains_target_typography': False, 'probe_only': False})
        write_json(run / 'analysis/media.json', {'duration': 3})
        shot = {'start': 0, 'end': 3, 'prepared_video': {
            'path': replacement.relative_to(run).as_posix(), 'sha256': common.file_hash(replacement)}}
        inventory = {'source_sha256': 'a' * 64, 'shots': [shot]}
        write_json(run / 'analysis/inventory.json', inventory)
        marker = self.root / 'state/storage-closed/recent.json'
        future = (self.now + timedelta(seconds=10)).timestamp()
        os.utime(marker, (future, future))
        with (patch('video_localizer.prepared.verify_for_production') as verify,
              patch('video_localizer.media.probe', return_value={'duration': 3}) as probe):
            self.assertEqual(self.paths(), {original.relative_to(self.root).as_posix()})
            verify.assert_called_once()
            probe.return_value = {'duration': 1}
            self.assertEqual(self.paths(), set())
            probe.return_value = {'duration': 3}
            write_json(run / 'analysis/inventory.json', {**inventory, 'shots': [{**shot, 'end': 1}]})
            self.assertEqual(self.paths(), set())
            write_json(run / 'analysis/inventory.json', inventory)
            consumer = self.run_folder('consumer') / 'input.json'
            write_json(consumer, {'neutral_hash': asset['sha256']})
            self.assertEqual(self.paths(), set())
            consumer.unlink()
            write_json(run / 'review/retained.json', {'old_master': asset})
            self.assertEqual(self.paths(), set())

    def test_delivered_run_without_close_receipt_is_reported_separately(self):
        self.run_folder('working')
        delivered = self.run_folder('delivered')
        write_json(delivered / 'outputs/delivery.json', {'sha256': 'b' * 64})
        self.age(delivered, 10)
        plan = self.plan()
        self.assertEqual(plan['selected'], [])
        self.assertIn({'path': 'runs/delivered', 'reason': 'awaiting_close_receipt'}, plan['retained'])
        self.assertIn({'path': 'runs/working', 'reason': 'unfinished_or_recent'}, plan['retained'])

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

    def test_invalid_control_receipts_do_not_block_unrelated_cleanup(self):
        self.close('ready')
        invalid_run = self.close('invalid')
        invalid_marker = self.close('bad-date')
        write_json(invalid_run / 'outputs/delivery.json', ['runs/needed/outputs/base.mp4'])
        write_json(self.root / 'state/storage-closed/bad-date.json', {
            'video_sha256': 'b' * 64, 'closed_at': '2026-11-24T00:00:00'})
        self.close('needed')
        plan = self.plan()
        self.assertEqual([row['path'] for row in plan['selected']], ['runs/ready'])
        for run, receipt in (
                (invalid_run, 'runs/invalid/outputs/delivery.json'),
                (invalid_marker, 'state/storage-closed/bad-date.json')):
            self.assertIn({'path': 'runs/' + run.name, 'reason': 'unreadable_json_receipt',
                           'receipts': [receipt]}, plan['retained'])
        project_storage.execute(self.root, plan['fingerprint'], now=self.now)
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

    def test_legacy_orphan_cache_requires_matching_completed_retirement(self):
        cases = (
            ('eligible', 'eligible', 'deleted', 2),
            ('recent', 'recent', 'deleted', 0),
            ('different_owner', 'other', 'deleted', 2),
            ('awaiting_deletion', 'awaiting_deletion', 'preserved', 2),
        )
        for name, owner, status, days in cases:
            scratch = self.root / 'work/runs' / name
            scratch.mkdir(parents=True)
            self.age(scratch, 3)
            write_json(self.root / 'state/run-retention' / (name + '.json'), {
                'schema_version': 1, 'run': owner, 'status': status,
                'deleted_at': (self.now - timedelta(days=days)).isoformat()})
        self.assertEqual(self.paths(), {'work/runs/eligible'})
        consumer = self.run_folder('consumer')
        write_json(consumer / 'input.json', {'asset': 'work/runs/eligible/source.mp4'})
        self.assertEqual(self.paths(), set())

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
                with common.run_operation(run, storage_wait_seconds=0):
                    self.fail('Producer entered during a sweep')
        self.assertFalse((self.root / 'runs/.locks/live.lock').exists())

    def test_stage_waits_for_maintenance_then_runs_once_without_full_sweep(self):
        from video_localizer import maintenance
        run = self.run_folder('live')
        storage_lock = self.file('state/project-storage.lock', b'synthetic')
        run_lock = self.root / 'runs/.locks/live.lock'
        calls = []

        def finish_maintenance(_seconds):
            self.assertFalse(run_lock.exists())
            self.assertEqual(calls, [])
            storage_lock.unlink()

        @common.guarded
        def stage(active_run):
            self.assertTrue(run_lock.exists())
            calls.append(active_run)
            return 'stage-receipt'

        with patch.object(common.time, 'sleep', side_effect=finish_maintenance) as wait, \
                patch.object(maintenance, 'after_stage') as after_stage, \
                patch.object(project_storage, 'preview', side_effect=AssertionError('No foreground sweep')):
            self.assertEqual(stage(run), 'stage-receipt')
        self.assertEqual(calls, [run])
        wait.assert_called_once()
        after_stage.assert_called_once()

    def test_sweep_collision_releases_run_lock_before_waiting(self):
        run = self.run_folder('live')
        run_lock = self.root / 'runs/.locks/live.lock'
        storage_lock = self.root / 'state/project-storage.lock'
        original = common.lock

        @contextmanager
        def delayed(path):
            with original(path):
                if not attempts:
                    self.file('state/project-storage.lock', b'synthetic')
                attempts.append(path)
                yield

        def finish_maintenance(_seconds):
            self.assertFalse(run_lock.exists())
            storage_lock.unlink()

        attempts = []
        with patch.object(common, 'lock', delayed), patch.object(common.time, 'sleep', side_effect=finish_maintenance):
            with common.run_operation(run):
                self.assertTrue(run_lock.exists())
        self.assertEqual(attempts, [run_lock, run_lock])

    def test_new_run_rechecks_sweep_lock_after_admission(self):
        from video_localizer import workflow
        original = common.lock

        @contextmanager
        def delayed(path):
            write_json(self.root / 'state/project-storage.lock', {'synthetic': True})
            with original(path):
                yield

        with patch.object(workflow, 'ROOT', self.root), patch.object(common, 'lock', delayed), \
                patch.object(common, 'STORAGE_WAIT_SECONDS', 0), patch.object(workflow, '_create_run') as create:
            with self.assertRaisesRegex(WorkflowError, 'storage maintenance'):
                workflow.create_run('unused.mp4', 'ja', '', 'new')
        create.assert_not_called()
