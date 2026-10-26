import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from video_localizer import evidence, knowledge, learning, workspace
from video_localizer.common import WorkflowError, file_hash, read_json, write_json

TEMP = PROJECT / "work/test-tmp"
TEMP.mkdir(parents=True, exist_ok=True)


class KnowledgeEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP)
        self.root = Path(self.temp.name)
        (self.root / "knowledge/rules").mkdir(parents=True)
        (self.root / "work").mkdir()
        self.method = self.root / "knowledge/rules/method.md"
        self.method.write_text("Inspect the actual pause. Evidence: evidence:pause", encoding="utf-8")
        write_json(self.root / "work/observation.json", {"observed_pause": 1.2, "scope": "synthetic contract fixture"})
        self.spec = {"id": "method", "path": "knowledge/rules/method.md", "scope": {"workflow": "video-localization"},
            "tags": ["speech"], "origin": "developer contract test", "reviewed_by": "test developer",
            "approval_type": "developer_review", "evidence_review": "sanitized_project_evidence",
            "company_preference": False, "evidence_files": ["work/observation.json"],
            "evidence_references": {"pause": "evidence/observation.json"}, "requires_features": ["speech"]}

    def tearDown(self):
        self.temp.cleanup()

    def promote(self):
        write_json(self.root / "work/spec.json", self.spec)
        return learning.promote("work/spec.json", self.root)

    def test_new_method_cannot_claim_an_unpackaged_reference(self):
        self.spec["evidence_references"] = {}
        with self.assertRaisesRegex(WorkflowError, "unresolved"):
            self.promote()
        self.assertFalse((self.root / "knowledge/index.json").exists())

    def test_named_evidence_is_verified_and_method_is_feature_scoped(self):
        self.promote()
        with patch.object(knowledge, "ROOT", self.root):
            self.assertEqual(knowledge.retrieve({"workflow": "video-localization"}), [])
            actual = knowledge.retrieve({"workflow": "video-localization", "features": ["speech"]})
            self.assertEqual([e["id"] for e in actual], ["method"])

    def test_multi_source_claim_cannot_use_only_one_source(self):
        self.spec["validation_level"] = "multi_source_observations"
        with self.assertRaisesRegex(WorkflowError, "two distinct"):
            self.promote()

    def test_required_supplement_is_not_a_silent_optional_file(self):
        self.promote()
        index = read_json(self.root / "knowledge/index.json")
        index["entries"][0]["required_evidence"] = ["caption-sync.json"]
        write_json(self.root / "knowledge/index.json", index)
        with self.assertRaisesRegex(WorkflowError, "unresolved"):
            learning.audit(self.root)

    def test_supplement_survives_original_run_and_missing_file_is_detected(self):
        self.promote()
        run = self.root / "runs/old"
        (run / "inputs").mkdir(parents=True)
        (run / "outputs").mkdir()
        (run / "inputs/source.mp4").write_bytes(b"fixture-source")
        (run / "outputs/final.mp4").write_bytes(b"fixture-result")
        source_sha, video_sha = file_hash(run / "inputs/source.mp4"), file_hash(run / "outputs/final.mp4")
        write_json(run / "run.json", {"source": "inputs/source.mp4", "source_sha256": source_sha})
        write_json(run / "review/caption-sync.json", {"video_sha256": video_sha, "decision": "fixture only"})
        spec = {"entry_id": "method", "source_run": "old", "video_sha256": video_sha,
            "reviewed_by": "fixture developer", "evidence_review": "sanitized_project_evidence",
            "files": {"caption-sync.json": "review/caption-sync.json"}}
        write_json(self.root / "work/evidence.json", spec)
        result = evidence.supplement("work/evidence.json", self.root)
        self.assertTrue(run.resolve().is_relative_to(self.root.resolve()))
        shutil.rmtree(run)
        self.assertEqual(learning.audit(self.root)["decision"], "pass")
        proof = self.root / result["supplement"]["path"] / "evidence/review/caption-sync.json"
        proof.unlink()
        with self.assertRaises(WorkflowError):
            learning.audit(self.root)

    def test_invalid_content_features_do_not_silently_become_characters(self):
        with self.assertRaisesRegex(WorkflowError, "content_features"):
            knowledge.context_for({"target_language": "zh-CN"}, {"content_features": "speech"})

    def test_inventory_features_are_used_without_copying_source_identity(self):
        context = knowledge.context_for({"target_language": "ko-KR"}, {
            "source_sha256": "new-source", "content_features": ["foreground_occlusion"],
            "audio": {"has_speech": True}, "text_instances": [{"trajectory": [{"time": 1}], "text_role": "speech_caption"}]})
        self.assertEqual(set(context["features"]), {"foreground_occlusion", "speech", "animated_text", "speech_captions", "onscreen_text"})
        self.assertEqual(context["source_sha256"], "new-source")

    def test_source_reference_does_not_enter_general_method_retrieval(self):
        self.promote()
        self.spec.update(id="source-case", scope={"workflow": "video-localization", "source_sha256": "a" * 64})
        self.promote()
        context = {"workflow": "video-localization", "source_sha256": "a" * 64, "features": ["speech"]}
        with patch.object(knowledge, "ROOT", self.root):
            self.assertEqual([e["id"] for e in knowledge.retrieve(context)], ["method"])
            self.assertEqual([e["id"] for e in knowledge.source_references(context)], ["source-case"])
        self.assertEqual(read_json(self.root / "knowledge/cases/index.json")["entries"][0]["path"],
                         "knowledge/cases/source-case.md")

    def test_actual_method_catalog_has_no_video_scope(self):
        entries = read_json(PROJECT / "knowledge/index.json")["entries"]
        self.assertTrue(all(not e.get("scope", {}).get("source_sha256") for e in entries))

    def test_external_workspace_can_audit_without_runtime_data_or_secrets(self):
        destination = self.root / "portable"
        result = workspace.initialize(destination, PROJECT)
        self.assertEqual(result["workspace"], str(destination.resolve()))
        self.assertFalse((destination / ".env").exists())
        self.assertFalse((destination / "knowledge/local").exists())
        env = {**os.environ, "VIDEO_LOCALIZER_WORKSPACE": str(destination)}
        completed = subprocess.run([sys.executable, "-B", str(PROJECT / "bin/va.py"), "knowledge-audit"],
            env=env, cwd=self.root, text=True, capture_output=True, encoding="utf-8")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["decision"], "pass")
