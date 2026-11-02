import sys
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from video_localizer import bundles, delivery_index, delivery_layout, fireplay_publication, library
from video_localizer.common import WorkflowError, file_hash, read_json, write_json


class DeliveryIndexTests(unittest.TestCase):
    def setUp(self):
        temp = PROJECT / "work/test-tmp"
        temp.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = self.root / "fixture.mp4"
        source.write_bytes(b"actual video fixture")
        self.sha = file_hash(source)
        self.package = self.root / "outputs/source/es/version"
        self.entry = {"source_sha256": "a" * 64, "target_language": "es",
                      "video_sha256": self.sha, "status": "historical_reference",
                      "origin_run_id": '<img src=x onerror="bad()">',
                      "package": "outputs/source/es/version"}
        bundles.create(self.package, "delivery", self.sha, {"final.mp4": source},
                       {**self.entry, "technical_decision": "revise"})
        self.entry["manifest_sha256"] = file_hash(self.package / "manifest.json")
        write_json(self.root / "outputs/index.json", {"entries": [self.entry]})

    def test_page_escapes_names_keeps_reference_status_and_does_not_copy_video(self):
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        result = delivery_index.refresh(self.root)
        page = (self.root / result["page"]).read_text(encoding="utf-8")
        self.assertIn("&lt;img", page)
        self.assertNotIn('<img src=x', page)
        self.assertIn('href="source/es/version/final.mp4"', page)
        self.assertEqual(result["counts"], {"delivered": 0, "with_issues": 0, "reference": 1, "unavailable": 0, "expired": 0})
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(set(after) - set(before), {Path("outputs/index.html")})
        for path, data in before.items():
            self.assertEqual(after[path], data)

    def test_changed_video_missing_file_and_escaping_path_are_not_linked(self):
        for change in ("changed", "missing", "escape"):
            with self.subTest(change=change):
                video = self.package / "final.mp4"
                if change == "changed":
                    video.write_bytes(b"changed")
                elif change == "missing":
                    video.unlink()
                else:
                    self.entry["package"] = "../outside"
                    write_json(self.root / "outputs/index.json", {"entries": [self.entry]})
                result = delivery_index.refresh(self.root)
                self.assertEqual(result["counts"]["unavailable"], 1)
                self.assertNotIn("打开视频", (self.root / result["page"]).read_text(encoding="utf-8"))

    def test_catalog_cannot_relabel_reference_as_delivered(self):
        self.entry["status"] = "delivered"
        write_json(self.root / "outputs/index.json", {"entries": [self.entry]})
        result = delivery_index.refresh(self.root)
        self.assertEqual(result["counts"]["delivered"], 0)
        self.assertEqual(result["counts"]["unavailable"], 1)
        self.assertEqual(result['diagnostics'][0]['reason'], 'Catalog differs from manifest: status')

    def test_invalid_manifest_is_diagnosed_and_html_escaped_without_link(self):
        manifest = self.package / 'manifest.json'
        manifest.write_text('', encoding='utf-8')
        self.entry['manifest_sha256'] = file_hash(manifest)
        write_json(self.root / 'outputs/index.json', {'entries': [self.entry]})
        result = delivery_index.refresh(self.root)
        self.assertIn('manifest.json', result['diagnostics'][0]['reason'])
        self.assertEqual(result['counts']['unavailable'], 1)
        self.assertNotIn('打开视频', (self.root / result['page']).read_text())


    def test_valid_delivery_and_empty_new_workspace(self):
        manifest = read_json(self.package / "manifest.json")
        manifest["metadata"].update(status="delivered", technical_decision="pass")
        write_json(self.package / "manifest.json", manifest)
        self.entry.update(status="delivered", manifest_sha256=file_hash(self.package / "manifest.json"))
        write_json(self.root / "outputs/index.json", {"entries": [self.entry]})
        self.assertEqual(delivery_index.refresh(self.root)["counts"]["delivered"], 1)
        fresh = self.root / "fresh"
        fresh.mkdir()
        self.assertEqual(delivery_index.refresh(fresh)["counts"],
                         {"delivered": 0, "with_issues": 0, "reference": 0, "unavailable": 0, "expired": 0})


class DeliveryPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / 'runs/synthetic-delivery'
        self.put('inputs/source.mp4', b'original-source')
        self.put('outputs/final.mp4', b'old-final')
        self.source_sha = file_hash(self.run / 'inputs/source.mp4')
        self.sha = file_hash(self.run / 'outputs/final.mp4')
        write_json(self.run / 'run.json', {'source': 'inputs/source.mp4', 'source_sha256': self.source_sha})
        self.request = {'target_language': 'es', 'requirement_name': 'fixture', 'task_name': 'clip'}
        write_json(self.run / 'inputs/request.json', self.request)
        self.policy = {'enabled': True, 'layout': 'requirement-language-task', 'retention_days': 14,
                       'package_root': 'outputs/.packages', 'catalog': 'state/delivery-index.json'}
        write_json(self.root / 'config/delivery-policy.json', self.policy)
        self.bind(self.sha)

    def put(self, relative, value):
        path = self.run / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
        return path

    def bind(self, digest):
        write_json(self.run / 'outputs/delivery.json', {'sha256': digest})
        write_json(self.run / 'outputs/quality.json', {'video_sha256': digest, 'decision': 'pass'})

    def export(self, **kwargs):
        # Capacity checks stay isolated from the host's actual disk policy.
        with patch('video_localizer.resources.preflight'):
            return library.export(self.run, self.root, **kwargs)

    def test_default_lean_skips_broken_dependencies_and_retains_only_final_and_json(self):
        self.put('outputs/neutral.mp4', b'neutral')
        self.put('outputs/voice.wav', b'voice')
        self.put('review/' + self.sha[:12] + '/evidence.mp4', b'large-review-video')
        write_json(self.run / 'analysis/inventory.json', {'shots': [{'prepared_video':
                   {'path': 'outputs/missing.mp4', 'sha256': 'a' * 64}}]})
        write_json(self.run / 'outputs/candidate.json', {'path': 'outputs/final.mp4', 'sha256': self.sha,
                   'typography_assets': [{'path': 'outputs/missing-font.png', 'sha256': 'b' * 64}]})
        write_json(self.run / 'plan.json', {'knowledge_snapshot_version': 1, 'id': 'missing-plan',
                   'audio_assets': [{'path': 'outputs/voice.wav', 'sha256': 'c' * 64}]})
        with patch.object(library, '_asset_closure', side_effect=AssertionError('closure must not run')), \
                patch('video_localizer.typography.verify_receipt', side_effect=AssertionError('prep must not run')), \
                patch('video_localizer.fast_delivery.validate_plan', side_effect=AssertionError('plan must not run')):
            result = self.export(reuse_manifests=[self.run / 'missing-reuse.json'])
        package = self.root / result['package']
        manifest = bundles.verify(package)
        paths = {asset['path'] for asset in manifest['files']}
        self.assertIn('payload/outputs/quality.json', paths)
        self.assertIn('payload/analysis/inventory.json', paths)
        self.assertTrue(all(p == 'final.mp4' or p.endswith('.json') for p in paths))
        self.assertNotIn('payload/inputs/source.mp4', paths)
        self.assertNotIn('payload/outputs/final.mp4', paths)
        self.assertNotIn('payload/outputs/neutral.mp4', paths)
        self.assertNotIn('payload/outputs/voice.wav', paths)
        self.assertEqual(manifest['metadata']['package_mode'], 'lean')
        self.assertEqual(manifest['metadata']['reusable'], [])
        self.assertFalse(manifest['metadata']['restoration_eligible'])
        self.assertFalse(manifest['metadata']['source_reuse_eligible'])
        self.assertIn('cannot restore', manifest['metadata']['restoration'])
        entry = library.find(self.source_sha, root=self.root)[0]
        self.assertTrue(entry['delivery_eligible'])
        self.assertFalse(entry['production_eligible'])
        self.assertFalse(entry['restoration_eligible'])
        self.assertFalse(entry['source_reuse_eligible'])
        destination = self.root / 'restored'
        with self.assertRaisesRegex(WorkflowError, 'production restoration is unavailable'):
            bundles.extract(package, destination)
        self.assertFalse(destination.exists())

    def test_request_and_policy_opt_in_keep_full_restorable_package(self):
        for mode in ('request', 'policy', 'legacy'):
            with self.subTest(mode=mode):
                if mode == 'request':
                    self.request['keep_reusable_assets'] = True
                elif mode == 'policy':
                    self.request.pop('keep_reusable_assets', None)
                    self.policy['package_mode'] = 'reusable'
                    write_json(self.root / 'config/delivery-policy.json', self.policy)
                else:
                    (self.root / 'config/delivery-policy.json').unlink()
                self.request['task_name'] = mode
                write_json(self.run / 'inputs/request.json', self.request)
                result = self.export()
                package = self.root / result['package']
                manifest = bundles.verify(package)
                self.assertEqual(manifest['metadata']['package_mode'], 'reusable')
                self.assertIn('payload/inputs/source.mp4', {a['path'] for a in manifest['files']})
                destination = self.root / ('restored-' + mode)
                bundles.extract(package, destination)
                self.assertEqual(file_hash(destination / 'inputs/source.mp4'), self.source_sha)
                self.assertTrue(library.find(self.source_sha, root=self.root)[-1]['production_eligible'])

    def test_old_new_old_replay_preserves_newest_view_catalog_order_and_first_timestamp(self):
        with patch.object(bundles, 'utc_now', return_value='2026-01-01T00:00:00Z'):
            old = self.export()
        self.put('outputs/final.mp4', b'new-final')
        new_sha = file_hash(self.run / 'outputs/final.mp4')
        self.bind(new_sha)
        with patch.object(bundles, 'utc_now', return_value='2026-01-02T00:00:00Z'):
            new = self.export()
        old_package = self.root / old['package']
        before_package = {p.relative_to(old_package): p.read_bytes() for p in old_package.rglob('*') if p.is_file()}
        before_catalog = read_json(self.root / 'state/delivery-index.json')
        self.put('outputs/old.mp4', b'old-final')
        replay = self.export(video_sha256=self.sha)
        self.assertTrue(replay['reused'])
        self.assertFalse(replay['presentation_current'])
        self.assertNotIn('final_file', replay)
        self.assertEqual(file_hash(self.root / new['final_file']), new_sha)
        self.assertEqual(read_json(self.root / 'state/delivery-index.json'), before_catalog)
        self.assertEqual({p.relative_to(old_package): p.read_bytes() for p in old_package.rglob('*') if p.is_file()}, before_package)

    def test_replay_full_package_remains_immutable_when_default_becomes_lean(self):
        self.request['keep_reusable_assets'] = True
        write_json(self.run / 'inputs/request.json', self.request)
        result = self.export()
        package = self.root / result['package']
        original = {p.relative_to(package): p.read_bytes() for p in package.rglob('*') if p.is_file()}
        self.request.pop('keep_reusable_assets')
        write_json(self.run / 'inputs/request.json', self.request)
        write_json(self.run / 'analysis/inventory.json', {'shots': [{'prepared_video':
                   {'path': 'missing.mp4', 'sha256': 'a' * 64}}]})
        with patch.object(library, '_collect_reusable', side_effect=AssertionError('immutable replay')):
            self.assertTrue(self.export()['reused'])
        self.assertEqual({p.relative_to(package): p.read_bytes() for p in package.rglob('*') if p.is_file()}, original)

    def test_existing_lean_cannot_silently_claim_reusable_upgrade(self):
        self.export()
        self.request['keep_reusable_assets'] = True
        write_json(self.run / 'inputs/request.json', self.request)
        with self.assertRaisesRegex(WorkflowError, 'cannot be upgraded'):
            self.export()

    def test_lean_best_available_keeps_publication_completion_evidence(self):
        write_json(self.run / 'analysis/inventory.json', {'audio': {'has_speech': True}})
        self.request['require_target_audio'] = True
        write_json(self.run / 'inputs/request.json', self.request)
        completion = {'video_sha256': self.sha, 'source_sha256': self.source_sha,
                      'quality_passed': False, 'decode_passed': True,
                      'speech_mode': 'dubbed', 'completed_at': '2026-01-01T00:00:00Z'}
        write_json(self.run / 'outputs/completion.json', completion)
        write_json(self.run / 'outputs/quality.json', {'video_sha256': self.sha, 'decision': 'revise'})
        write_json(self.run / 'outputs/delivery.json', {'sha256': self.sha, 'scope': 'best_available',
                   'completion_sha256': file_hash(self.run / 'outputs/completion.json')})
        result = self.export()
        package = self.root / result['package']
        manifest = bundles.verify(package)
        self.assertEqual(fireplay_publication._complete(package, manifest), completion)
        self.assertFalse(library.find(self.source_sha, root=self.root)[0]['production_eligible'])

    def test_expired_catalog_entries_hide_residual_media_without_broken_diagnostic(self):
        result = self.export()
        catalog_path = self.root / 'state/delivery-index.json'
        catalog = read_json(catalog_path)
        catalog['entries'][0]['expired_at'] = '2026-01-03T00:00:00Z'
        write_json(catalog_path, catalog)
        # Both still-valid residual bytes and missing bytes count as expired history.
        for residual in (True, False):
            if not residual:
                (self.root / result['package'] / 'manifest.json').unlink()
            refreshed = delivery_index.refresh(self.root)
            page = (self.root / refreshed['page']).read_text(encoding='utf-8')
            self.assertEqual(refreshed['counts']['expired'], 1)
            self.assertEqual(refreshed['counts']['unavailable'], 0)
            self.assertEqual(refreshed['diagnostics'], [])
            self.assertNotIn('打开视频', page)
            self.assertNotIn('查看原因', page)
            self.assertNotIn('final.mp4', page)
            self.assertEqual(library.find(self.source_sha, root=self.root)[0]['availability'], 'expired')

    def test_latest_uses_catalog_order_on_equal_timestamps_and_skips_expired_missing(self):
        self.export()
        path = self.root / 'state/delivery-index.json'
        entry = read_json(path)['entries'][0]
        second = {**entry, 'video_sha256': 'b' * 64}
        expired = {**second, 'expired_at': 'later'}
        missing = {**second, 'package': 'outputs/.packages/missing', 'archived_at': '9999'}
        self.assertIs(delivery_layout.latest([entry, second], self.root)[0], second)
        self.assertIs(delivery_layout.latest([entry, expired, missing], self.root)[0], entry)


class ArchiveContractTests(unittest.TestCase):
    setUp = DeliveryPolicyTests.setUp
    put = DeliveryPolicyTests.put
    bind = DeliveryPolicyTests.bind
    export = DeliveryPolicyTests.export

    def save_request(self):
        write_json(self.run / 'inputs/request.json', self.request)

    def snapshot(self):
        return {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def test_explicit_reusable_keeps_source_and_restores(self):
        self.request['delivery_package_mode'] = 'reusable'
        self.save_request()
        result = self.export()
        package = self.root / result['package']
        manifest = bundles.verify(package)
        self.assertEqual(manifest['metadata']['package_mode'], 'reusable')
        self.assertTrue(manifest['metadata']['restoration_eligible'])
        destination = self.root / 'restored'
        bundles.extract(package, destination)
        self.assertEqual(file_hash(destination / 'inputs/source.mp4'), self.source_sha)
        self.assertTrue(library.find(self.source_sha, root=self.root)[0]['source_reuse_eligible'])

    def test_explicit_lean_overrides_old_flag_and_policy(self):
        self.request.update(delivery_package_mode='lean', keep_reusable_assets=True)
        self.save_request()
        self.policy['package_mode'] = 'reusable'
        write_json(self.root / 'config/delivery-policy.json', self.policy)
        result = self.export()
        manifest = bundles.verify(self.root / result['package'])
        self.assertEqual(manifest['metadata']['package_mode'], 'lean')
        self.assertNotIn('payload/inputs/source.mp4', {a['path'] for a in manifest['files']})

    def test_invalid_modes_are_rejected_without_writes(self):
        for value in ('', 'true', 'REUSABLE', 'other', True, False, None, 1, [], {}):
            with self.subTest(value=value):
                self.request['delivery_package_mode'] = value
                self.save_request()
                before = self.snapshot()
                with self.assertRaisesRegex(WorkflowError, 'delivery_package_mode'):
                    self.export()
                self.assertEqual(self.snapshot(), before)

    def test_legacy_strings_do_not_enable_reusable(self):
        for value in ('true', 'false', 1):
            with self.subTest(value=value):
                self.request.update(keep_reusable_assets=value, task_name=str(value))
                self.save_request()
                manifest = bundles.verify(self.root / self.export()['package'])
                self.assertEqual(manifest['metadata']['package_mode'], 'lean')

    def test_explicit_upgrade_of_existing_lean_still_rejected(self):
        self.export()
        self.request['delivery_package_mode'] = 'reusable'
        self.save_request()
        before = self.snapshot()
        with self.assertRaisesRegex(WorkflowError, 'cannot be upgraded'):
            self.export()
        self.assertEqual(self.snapshot(), before)

    def test_expired_replay_cannot_recreate_or_present(self):
        result = self.export()
        path = self.root / 'state/delivery-index.json'
        catalog = read_json(path)
        catalog['entries'][0]['expired_at'] = '2026-01-03T00:00:00Z'
        write_json(path, catalog)
        for residual in (True, False):
            with self.subTest(residual=residual):
                if not residual:
                    shutil.rmtree(self.root / result['package'])
                    (self.root / result['final_file']).unlink()
                before = self.snapshot()
                with patch.object(bundles, 'create', side_effect=AssertionError('must not recreate')):
                    with self.assertRaisesRegex(WorkflowError, '(?i)expired'):
                        self.export()
                self.assertEqual(self.snapshot(), before)

    def test_expired_legacy_fallback_cannot_recreate(self):
        result = self.export()
        current = self.root / 'state/delivery-index.json'
        catalog = read_json(current)
        catalog['entries'][0]['expired_at'] = '2026-01-03T00:00:00Z'
        write_json(self.root / 'outputs/index.json', catalog)
        current.unlink()
        shutil.rmtree(self.root / result['package'])
        before = self.snapshot()
        with self.assertRaisesRegex(WorkflowError, '(?i)expired'):
            self.export()
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(current.exists())

    def test_expired_identity_does_not_block_another_task(self):
        self.export()
        path = self.root / 'state/delivery-index.json'
        catalog = read_json(path)
        catalog['entries'][0]['expired_at'] = '2026-01-03T00:00:00Z'
        write_json(path, catalog)
        self.request['task_name'] = 'different-task'
        self.save_request()
        self.assertTrue(self.export()['presentation_current'])
        self.assertEqual(len(read_json(path)['entries']), 2)
        self.assertTrue(read_json(path)['entries'][0]['expired_at'])

    def test_archive_holds_run_lock_through_package_and_catalog(self):
        from video_localizer import project_storage
        write_json(self.root / 'config/storage-authorization.local.json', {
            'workspace': str(self.root.resolve()), 'automatic_cleanup': True})
        stages = []
        def check_exclusion(stage):
            stages.append(stage)
            self.assertTrue((self.run.parent / '.locks' / (self.run.name + '.lock')).exists())
            with self.assertRaisesRegex(WorkflowError, 'Active run'):
                project_storage.preview(self.root)
        create, register = bundles.create, library._register
        def create_locked(*args, **kwargs):
            check_exclusion('package')
            return create(*args, **kwargs)
        def register_locked(*args, **kwargs):
            check_exclusion('catalog')
            return register(*args, **kwargs)
        with patch.object(bundles, 'create', side_effect=create_locked), patch.object(library, '_register', side_effect=register_locked):
            self.export()
        self.assertEqual(stages, ['package', 'catalog'])
        self.assertFalse((self.run.parent / '.locks' / (self.run.name + '.lock')).exists())

    def test_sweep_lock_blocks_archive_before_source_reads(self):
        from video_localizer.common import lock
        with lock(self.root / 'state/project-storage.lock'):
            with patch.object(library, '_export', side_effect=AssertionError('must not read source')):
                with self.assertRaisesRegex(WorkflowError, 'storage maintenance is active'):
                    self.export()
        self.assertFalse((self.root / 'outputs').exists())

    def test_archive_preserves_closed_marker(self):
        marker = self.root / 'state/storage-closed' / (self.run.name + '.json')
        write_json(marker, {'closed_at': '2026-01-01T00:00:00Z', 'video_sha256': self.sha})
        before = marker.read_bytes()
        self.export()
        self.assertEqual(marker.read_bytes(), before)
        self.assertFalse((self.root / 'state/storage-activity' / (self.run.name + '.json')).exists())

    def test_archive_shares_existing_producer_lock(self):
        from video_localizer.common import run_operation
        with run_operation(self.run):
            result = self.export()
            self.assertTrue((self.root / result['package'] / 'manifest.json').exists())
            self.assertTrue((self.run.parent / '.locks' / (self.run.name + '.lock')).exists())


if __name__ == "__main__":
    unittest.main()
