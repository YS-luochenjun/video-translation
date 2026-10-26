import copy
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from video_localizer import bundles, knowledge, learning, retention, source_state, workflow
from video_localizer.common import WorkflowError, file_hash, object_hash, read_json, run_operation, write_json

TEMP = Path(__file__).resolve().parents[1] / "work/test-tmp"
TEMP.mkdir(parents=True, exist_ok=True)


class SourceRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP)
        self.root = Path(self.temp.name)
        write_json(self.root / "config/workspace.json", {"sampling_seconds": 1, "max_segment_seconds": 8})
        write_json(self.root / "knowledge/index.json", {"entries": []})
        self.run = self.make_run("original", "zh-CN")
        self.sha = read_json(self.run / "run.json")["source_sha256"]
        write_json(self.run / "analysis/media.json", {"duration": 8, "has_audio": False})
        write_json(self.run / "analysis/inventory.json", {"source_sha256": self.sha,
            "coverage": {"visual": {"status": "reviewed"}},
            "shots": [{"id": "s001", "start": 0, "end": 8, "keyframe": "analysis/shot-001.jpg", "description": "source scene"}],
            "text_instances": [{"id": "t001", "source_text": "Hello", "target_text": "CHINESE ONLY", "start": 1,
                "end": 7, "source_interval": [2, 6], "bbox": [1, 2, 30, 10], "action": "solid_overlay",
                "display": {"font_size": 30}, "target_audio": "chinese.wav"}],
            "speech_segments": [{"target_text": "CHINESE VOICE"}]})
        (self.run / "analysis/shot-001.jpg").write_bytes(b"source-frame")
        (self.run / "analysis/frames").mkdir()
        (self.run / "analysis/frames/frame-00001.jpg").write_bytes(b"source-sampled-frame")

    def tearDown(self):
        self.temp.cleanup()

    def make_run(self, name, locale, content=b"source-video"):
        run = self.root / "runs" / name
        (run / "inputs").mkdir(parents=True)
        (run / "analysis").mkdir()
        (run / "jobs").mkdir()
        (run / "outputs").mkdir()
        (run / "inputs/source.mp4").write_bytes(content)
        write_json(run / "run.json", {"id": name, "source": "inputs/source.mp4", "source_sha256": file_hash(run / "inputs/source.mp4")})
        write_json(run / "inputs/request.json", {"target_language": locale})
        return run

    def test_new_locale_reuses_extraction_after_old_run_is_removed(self):
        source_state.save(self.run, self.root)
        shutil.rmtree(self.run)
        other = self.make_run("japanese", "ja-JP")
        with patch.object(workflow, "ROOT", self.root), patch.object(workflow.media, "extract", side_effect=AssertionError("Must reuse")):
            result = workflow.analyze(other)
        self.assertTrue(result["reused"])
        inventory = read_json(other / "analysis/inventory.json")
        self.assertEqual(inventory["text_instances"][0]["source_text"], "Hello")
        self.assertEqual(inventory["text_instances"][0]["target_text"], "")
        self.assertEqual(inventory["text_instances"][0]["start"], 2)
        self.assertEqual(inventory["speech_segments"], [])
        self.assertEqual(inventory["coverage"]["visual"]["status"], "pending")
        self.assertNotIn("CHINESE", str(inventory))

    def test_changed_source_is_not_a_cache_hit(self):
        source_state.save(self.run, self.root)
        other = self.make_run("different", "ja-JP", b"changed-source")
        self.assertIsNone(source_state.restore(other, self.root))

    def test_optional_ocr_candidates_survive_source_snapshot_without_new_locale_approval(self):
        from video_localizer.ocr_supplement import context
        rapid = {'source_sha256': self.sha, 'complete': True, 'frames': []}
        extra = {'source_sha256': self.sha, 'rapid_sha256': object_hash(rapid), 'status': 'available',
                 'items': [{'text': 'Hello', 'review_status': 'pending'}], 'warnings': []}
        write_json(self.run / 'analysis/ocr-source.json', rapid)
        write_json(self.run / 'analysis/ocr-supplement.json', extra)
        source_state.save(self.run, self.root)
        shutil.rmtree(self.run)
        other = self.make_run('ocr-reuse', 'ja-JP')
        self.assertTrue(source_state.restore(other, self.root)['reused'])
        self.assertEqual(read_json(other / 'analysis/ocr-supplement.json'), extra)
        self.assertEqual(context(other, self.sha)['status'], 'retired')
        self.assertEqual(context(other, self.sha)['historical_evidence'], 'analysis/ocr-supplement.json')

    def test_corrupt_source_snapshot_does_not_fall_back_silently(self):
        result = source_state.save(self.run, self.root)
        folder = self.root / result["snapshot"]
        (folder / "payload/analysis/shot-001.jpg").write_bytes(b"tampered")
        with self.assertRaises(WorkflowError):
            source_state.restore(self.make_run("second", "ja-JP"), self.root)

    def test_adaptive_ocr_backlog_survives_source_snapshot(self):
        from video_localizer.ocr_supplement import context
        inventory = read_json(self.run / 'analysis/inventory.json')
        inventory['text_instances'][0]['source_interval'] = [1, 7]
        write_json(self.run / 'analysis/inventory.json', inventory)
        rapid = {'source_sha256': self.sha, 'complete': True, 'frames': [
            {'frame': 60, 'time': 2, 'observations': []}]}
        write_json(self.run / 'analysis/ocr-source.json', rapid)
        result = {'source_sha256': self.sha, 'status': 'disabled',
                  'pending_checks': [{'time': 2, 'deferred_reason': 'disabled'}]}
        write_json(self.run / 'analysis/ocr-supplement.json', result)
        source_state.save(self.run, self.root)
        shutil.rmtree(self.run)
        other = self.make_run('pending-ocr-reuse', 'ja-JP')
        self.assertTrue(source_state.restore(other, self.root)['reused'])
        result = context(other, self.sha)
        self.assertEqual(result['status'], 'retired')
        self.assertFalse(result['automatic_pass'])
        report = read_json(other / 'analysis/ocr-supplement.json')
        self.assertEqual(report['pending_checks'][0]['time'], 2)
        self.assertEqual(report['pending_checks'][0]['deferred_reason'], 'disabled')

    def test_existing_inventory_is_never_overwritten(self):
        source_state.save(self.run, self.root)
        with self.assertRaisesRegex(WorkflowError, "overwritten"):
            source_state.restore(self.run, self.root)

    def test_changed_extraction_parameters_require_new_extraction(self):
        source_state.save(self.run, self.root)
        write_json(self.root / "config/workspace.json", {"sampling_seconds": .5, "max_segment_seconds": 8})
        self.assertIsNone(source_state.restore(self.make_run("other", "ja-JP"), self.root))

    def test_source_ocr_and_speech_observations_survive_without_old_target(self):
        inventory = read_json(self.run / "analysis/inventory.json")
        inventory["audio"] = {"has_speech": True}
        inventory["speech_segments"] = [{"id": "a001", "source_text": "English source", "target_text": "OLD TARGET"}]
        write_json(self.run / "analysis/inventory.json", inventory)
        write_json(self.run / "analysis/ocr-source.json", {"source_sha256": self.sha, "text": "Hello"})
        source_state.save(self.run, self.root)
        other = self.make_run("ocr-reuse", "ja-JP")
        source_state.restore(other, self.root)
        restored = read_json(other / "analysis/inventory.json")
        self.assertEqual(restored["source_speech_observations"][0]["source_text"], "English source")
        self.assertTrue(restored["audio"]["has_speech"])
        self.assertNotIn("OLD TARGET", str(restored))
        self.assertEqual(read_json(other / "analysis/ocr-source.json")["text"], "Hello")

    def test_source_ocr_cannot_be_borrowed_from_another_video(self):
        write_json(self.run / "analysis/ocr-source.json", {"source_sha256": "0" * 64})
        with self.assertRaisesRegex(WorkflowError, "another video"):
            source_state.save(self.run, self.root)

    def test_recorded_extraction_settings_survive_later_config_change(self):
        write_json(self.run / "analysis/extraction-settings.json", source_state.parameters(self.root))
        write_json(self.root / "config/workspace.json", {"sampling_seconds": .5, "max_segment_seconds": 8})
        source_state.save(self.run, self.root)
        self.assertIsNone(source_state.restore(self.make_run("settings-change", "ja-JP"), self.root))

    def test_delete_defaults_to_preview_and_requires_preservation(self):
        result = retention.delete(self.run, self.root)
        self.assertEqual(result["decision"], "blocked")
        self.assertTrue(self.run.exists())
        with self.assertRaises(WorkflowError):
            retention.delete(self.run, self.root, execute=True)

    def test_delete_keeps_observations_source_and_queue(self):
        retention.preserve(self.run, self.root)
        preview = retention.delete(self.run, self.root)
        self.assertEqual(preview["decision"], "ready")
        result = retention.delete(self.run, self.root, execute=True, expected=preview["fingerprint"])
        self.assertFalse(self.run.exists())
        self.assertEqual(bundles.verify(self.root / result["knowledge_case"])["kind"], "knowledge-case")
        self.assertEqual(learning.audit(self.root)["decision"], "pass")
        self.assertEqual(len(list((self.root / "knowledge/local/inbox").glob("*.json"))), 1)
        self.assertTrue(source_state.restore(self.make_run("reuse-after-delete", "ko-KR"), self.root)["reused"])

    def test_mutation_after_preservation_blocks_deletion(self):
        retention.preserve(self.run, self.root)
        (self.run / "analysis/new-observation.txt").write_text("new insight")
        self.assertEqual(retention.delete(self.run, self.root)["decision"], "blocked")

    def test_unsettled_task_and_unknown_billing_block_preservation(self):
        for job in ({"state": "ambiguous"}, {"state": "success", "billing_status": "unknown"},
                    {"state": "success", "task_id": "unsettled-remote-task"}):
            write_json(self.run / "jobs/task.json", job)
            with self.assertRaisesRegex(WorkflowError, "Resolve"):
                retention.preserve(self.run, self.root)

    def test_active_operation_lock_prevents_deletion(self):
        lock_path = self.run.parent / ".locks" / (self.run.name + ".lock")
        lock_path.parent.mkdir(exist_ok=True)
        lock_path.write_text("another process")
        with self.assertRaisesRegex(WorkflowError, "locked"):
            retention.delete(self.run, self.root)
        self.assertTrue(self.run.exists())

    def test_external_live_reference_blocks_run_deletion(self):
        retention.preserve(self.run,self.root)
        other=self.make_run('consumer','en')
        write_json(other/'plan.json',{'asset':{'path':'../original/inputs/source.mp4','sha256':self.sha}})
        preview=retention.delete(self.run,self.root)
        self.assertEqual(preview['decision'],'blocked')
        self.assertTrue(any('Another run' in b for b in preview['blockers']))

    def test_original_task_script_is_independent_evidence_after_deletion(self):
        path=self.run/'inputs/repair.py';path.write_text('# original failed implementation\n')
        receipt=retention.preserve(self.run,self.root)
        manifest=bundles.verify(self.root/receipt['case'])
        assets=[a for a in manifest['files'] if a['path'].endswith('inputs/repair.py')]
        self.assertEqual(len(assets),1)
        preview=retention.delete(self.run,self.root)
        retention.delete(self.run,self.root,True,preview['fingerprint'])
        self.assertEqual((self.root/receipt['case']/assets[0]['path']).read_text(),'# original failed implementation\n')

    def test_unknown_cost_report_blocks_deletion(self):
        write_json(self.run / "outputs/actual-costs.json", {"unknown_jobs": ["unsettled-task"]})
        self.assertTrue(any("Unsettled" in p for p in retention.delete(self.run, self.root)["blockers"]))

    def test_missing_permanent_evidence_blocks_deletion(self):
        record = retention.preserve(self.run, self.root)
        manifest = bundles.verify(self.root / record["case"])
        (self.root / record["case"] / manifest["files"][0]["path"]).unlink()
        with self.assertRaises(WorkflowError):
            retention.delete(self.run, self.root)

    def test_stale_preview_cannot_delete_a_preserved_revision(self):
        retention.preserve(self.run, self.root)
        with self.assertRaisesRegex(WorkflowError, "fingerprint"):
            retention.delete(self.run, self.root, execute=True, expected="0" * 64)

    def test_delete_target_cannot_be_a_different_directory(self):
        with self.assertRaisesRegex(WorkflowError, "named run"):
            retention.delete(self.root / "knowledge", self.root)
