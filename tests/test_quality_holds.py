import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from video_localizer import bundles, delivery_index, library, prepared, quality_holds, workflow
from video_localizer.common import WorkflowError, file_hash, read_json, write_json


class QualityHoldIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = PROJECT / "work/test-tmp"
        temporary.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temporary)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "source.mp4").write_bytes(b"source")
        self.source_sha = file_hash(self.root / "source.mp4")
        video = self.root / "video.mp4"
        video.write_bytes(b"old rejected video")
        self.sha = file_hash(video)
        package = self.root / "outputs/source/es/version"
        self.entry = {"source_sha256": self.source_sha, "video_sha256": self.sha,
                      "target_language": "es", "origin_run_id": "old-es",
                      "status": "delivered", "package": "outputs/source/es/version"}
        bundles.create(package, "delivery", self.sha, {"final.mp4": video},
                       {**self.entry, "technical_decision": "pass"})
        self.entry["manifest_sha256"] = file_hash(package / "manifest.json")
        write_json(self.root / "outputs/index.json", {"entries": [self.entry]})
        self.package = package
        feedback = self.root / "feedback.json"
        write_json(feedback, {"user_feedback": "The child's hair is frozen."})
        branch = self.root / "knowledge/local/quality-holds" / self.source_sha / self.sha
        event = branch / "user-correction"
        bundles.create(event, "quality-hold", "test-hold", {"feedback.json": feedback}, {
            "id": "user-correction", "source_sha256": self.source_sha,
            "asset_sha256": self.sha, "asset_kind": "video",
            "reason": "Frozen hair", "reported_by": "user feedback and reviewed reproduction",
        })
        write_json(branch / "index.json", {"schema_version": 1, "entries": [
            {"id": "user-correction", "manifest_sha256": file_hash(event / "manifest.json")}]})
        self.branch = branch

    def test_rejected_delivery_is_not_shown_as_accepted(self):
        before = (self.package / "manifest.json").read_bytes()
        result = delivery_index.refresh(self.root)
        self.assertEqual(result["counts"]["delivered"], 0)
        self.assertIn("质量异议", (self.root / "outputs/index.html").read_text(encoding="utf-8"))
        self.assertEqual((self.package / "manifest.json").read_bytes(), before)

    def test_rejected_package_remains_recoverable_but_not_production_eligible(self):
        result = library.find(self.source_sha, root=self.root)[0]
        self.assertEqual(result["availability"], "available")
        self.assertFalse(result.get("production_eligible", True))
        self.assertEqual(result["effective_status"], "revise")

    def test_hold_survives_package_removal_and_does_not_block_different_video(self):
        (self.package / "final.mp4").unlink()
        self.assertEqual(len(quality_holds.active(self.source_sha, self.sha, self.root)), 1)
        self.assertEqual(quality_holds.active(self.source_sha, "b" * 64, self.root), [])
        quality_holds.require_clear(self.source_sha, "b" * 64, self.root)

    def test_missing_or_tampered_notice_blocks_instead_of_restoring_old_pass(self):
        evidence = self.branch / "user-correction/feedback.json"
        evidence.write_bytes(b"changed")
        with self.assertRaises(WorkflowError):
            library.find(self.source_sha, root=self.root)
        result = delivery_index.refresh(self.root)
        self.assertEqual(result["counts"]["unavailable"], 1)

    def test_old_approval_cannot_bypass_production_or_delivery(self):
        run = self.root / "runs/old-es"
        write_json(run / "run.json", {"source_sha256": self.source_sha})
        write_json(run / "outputs/candidate.json", {"sha256": self.sha})
        with self.assertRaisesRegex(WorkflowError, "Quality hold"):
            prepared.verify_for_production(run, {"sha256": self.sha}, self.source_sha, self.root)
        with patch.object(workflow, "ROOT", self.root), patch.object(workflow, "quality") as quality:
            with self.assertRaisesRegex(WorkflowError, "Quality hold"):
                workflow.deliver(run)
            quality.assert_not_called()
        self.assertFalse((run / "outputs/delivery.json").exists())

    def test_record_is_idempotent_independent_and_rejects_changed_event(self):
        spec = {"id": "reviewed-correction", "source": {"path": "source.mp4", "sha256": self.source_sha},
                "asset": {"path": "video.mp4", "sha256": self.sha}, "asset_kind": "video",
                "reason": "Frozen hair verified in the actual encoded video",
                "reported_by": "user feedback with developer verification",
                "evidence": [{"path": "feedback.json", "sha256": file_hash(self.root / "feedback.json")}]}
        write_json(self.root / "hold.json", spec)
        for _ in range(2):
            result = quality_holds.record("hold.json", self.root)
            self.assertEqual(len(result["notices"]), 2)
        self.assertEqual(len(read_json(self.branch / "index.json")["entries"]), 2)
        (self.root / "feedback.json").unlink()
        self.assertEqual(len(quality_holds.active(self.source_sha, self.sha, self.root)), 2)
        write_json(self.root / "feedback.json", {"new": "evidence"})
        spec["evidence"][0]["sha256"] = file_hash(self.root / "feedback.json")
        spec["reason"] = "changed"
        write_json(self.root / "hold.json", spec)
        with self.assertRaisesRegex(WorkflowError, "new event id"):
            quality_holds.record("hold.json", self.root)

    def test_new_candidate_cannot_bypass_a_held_master_in_an_old_plan(self):
        run = self.root / "runs/repaired-es"
        write_json(run / "run.json", {"source_sha256": self.source_sha})
        write_json(run / "outputs/candidate.json", {"sha256": "b" * 64})
        plan = {"source_sha256": self.source_sha, "segments": [
            {"prepared_video": {"sha256": self.sha}}]}
        with patch.object(workflow, "ROOT", self.root), \
                patch.object(workflow, "current_plan", return_value=plan), \
                patch.object(workflow, "quality") as quality:
            with self.assertRaisesRegex(WorkflowError, "Quality hold"):
                workflow.deliver(run)
            quality.assert_not_called()

    def test_reuse_eligibility_checks_neutral_assets_separately_from_final_video(self):
        fresh = self.root / "new.mp4"
        fresh.write_bytes(b"different final")
        entry = {**self.entry, "package": "outputs/source/es/new", "video_sha256": file_hash(fresh)}
        package = self.root / entry["package"]
        bundles.create(package, "delivery", entry["video_sha256"], {"final.mp4": fresh},
                       {**entry, "technical_decision": "pass", "reusable": [
                           {"kind": "prepared_video", "asset": {"sha256": self.sha}}]})
        entry["manifest_sha256"] = file_hash(package / "manifest.json")
        write_json(self.root / "outputs/index.json", {"entries": [entry]})
        result = library.find(self.source_sha, root=self.root)[0]
        self.assertEqual(result["quality_holds"], [])
        self.assertEqual(len(result["visual_reuse_holds"]), 1)
        self.assertFalse(result["production_eligible"])


if __name__ == "__main__":
    unittest.main()
