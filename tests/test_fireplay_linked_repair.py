import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from video_localizer.common import WorkflowError, file_hash, read_json, write_json
from video_localizer.fireplay_revision import linked_repair_request


class LinkedRepairTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        video = {"source_url": "https://example.com/source.mp4",
                 "source": {"sha256": "source"}, "targets": ["fr"]}
        self.previous = {"code": "APC-repair", "requirement_id": "repair-id",
                         "targets": ["fr"], "videos": [video.copy()]}
        original = {"requirement_id": "original-id", "budget": "original-budget",
                    "targets": ["fr"], "videos": [{
                        **video, "members": ["original-01"],
                        "chat": {"threadId": "owner"}, "batch": "original"}]}
        write_json(self.root / "state/fireplay/APC-original/request.json", original)
        self.outbox = self.root / "state/fireplay/APC-repair/return-1.json"
        write_json(self.outbox, {
            "state": "returned", "operations": {"bind": {"state": "verified"}},
            "packages": [{"package": "outputs/original-fr", "locale": "fr", "sha256": "old-video"}]})
        self.evidence = self.root / "continuity.json"
        write_json(self.evidence, {
            "delivery_requirement": {"code": "APC-repair", "id": "repair-id"},
            "original_requirement": {"code": "APC-original", "id": "original-id"},
            "original_budget_id": "original-budget", "targets": ["fr"],
            "original_runs": ["original-01"], "source_sha256": "source",
            "owner_thread_id": "owner",
            "authority": {"authorization_ref": "human-message", "source_quote": "Continue repair"}})
        self.decision = {
            "continue_user_requested_repair": True, "repair_authority": "user",
            "repair_authorization_ref": "human-message", "repair_source_quote": "Complete and upload",
            "repair_continuity": {"path": "continuity.json", "sha256": file_hash(self.evidence)}}
        self.manifest = {"metadata": {
            "origin_run_id": "original-01", "source_sha256": "source",
            "target_language": "fr", "video_sha256": "old-video"}}

    def resolve(self):
        with patch("video_localizer.bundles.verify", return_value=self.manifest):
            return linked_repair_request(self.previous, self.decision, self.root)

    def test_attaches_verified_original_production_without_new_budget(self):
        result = self.resolve()
        self.assertEqual(result["budget"], "original-budget")
        self.assertEqual(result["videos"][0]["members"], ["original-01"])
        self.assertNotIn("budget", self.previous)
        self.assertEqual(read_json(self.outbox)["state"], "returned")

    def test_rejects_changed_continuity_evidence(self):
        self.evidence.write_text("{}")
        with self.assertRaisesRegex(WorkflowError, "evidence changed"):
            self.resolve()

    def test_rejects_original_package_from_another_source(self):
        self.manifest["metadata"]["source_sha256"] = "different-source"
        with self.assertRaisesRegex(WorkflowError, "linked production"):
            self.resolve()

    def test_rejects_unknown_external_operation(self):
        value = read_json(self.outbox)
        value["operations"]["upload-1"] = {"state": "unknown"}
        write_json(self.outbox, value)
        with self.assertRaisesRegex(WorkflowError, "Settle prior"):
            self.resolve()

    def test_rejects_changed_original_budget(self):
        self.previous["budget"] = "another-budget"
        with self.assertRaisesRegex(WorkflowError, "original funded request"):
            self.resolve()


if __name__ == "__main__":
    unittest.main()
