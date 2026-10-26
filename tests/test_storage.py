import shutil
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from video_localizer import bundles, cli, knowledge, learning, library, prepared
from video_localizer.common import WorkflowError, file_hash, read_json, write_json

TEMP = Path(__file__).resolve().parents[1] / "work/test-tmp"
TEMP.mkdir(parents=True, exist_ok=True)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP)
        self.root = Path(self.temp.name)
        self.run = self.root / "runs/test-source"
        self.put("inputs/source.mp4", b"source-video-bytes")
        self.source_sha = file_hash(self.run / "inputs/source.mp4")
        self.put("outputs/result.mp4", b"accepted-video-bytes")
        self.video_sha = file_hash(self.run / "outputs/result.mp4")
        write_json(self.run / "run.json", {"source": "inputs/source.mp4", "source_sha256": self.source_sha})
        write_json(self.run / "inputs/request.json", {"target_language": "zh-CN"})
        self.put("outputs/neutral.mp4", b"neutral-visual-master")
        self.asset = {"path": "outputs/neutral.mp4", "sha256": file_hash(self.run / "outputs/neutral.mp4"),
                      "record": "outputs/preparation.json"}
        write_json(self.run / self.asset["record"], {"source_sha256": self.source_sha, "target_language": None,
            "contains_target_typography": False, "inputs": [{"path": "inputs/source.mp4", "sha256": self.source_sha}],
            "output": {"path": self.asset["path"], "sha256": self.asset["sha256"]}})
        self.asset["record_sha256"] = file_hash(self.run / self.asset["record"])
        write_json(self.run / "analysis/inventory.json", {"shots": [{"prepared_video": self.asset}]})
        write_json(self.run / "outputs/candidate.json", {"path": "outputs/result.mp4", "sha256": self.video_sha})
        write_json(self.run / "outputs/quality.json", {"video_sha256": self.video_sha, "decision": "pass"})
        write_json(self.run / "outputs/delivery.json", {"video": "outputs/result.mp4", "sha256": self.video_sha})
        write_json(self.run / "review/review.json", {"video_sha256": self.video_sha, "decision": "pass"})
        self.put("review/" + self.video_sha[:12] + "/observed.png", b"observed-frame-bytes")
        self.scope = {"workflow": "video-localization", "source_sha256": self.source_sha, "target_language": "zh-CN"}

    def put(self, path, content):
        path = self.run / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def tearDown(self):
        self.temp.cleanup()

    def test_delivery_restores_prepared_asset_without_original_run(self):
        result = library.export(self.run, self.root)
        package = self.root / result["package"]
        # Copy to a different location, then remove the originals in this disposable fixture.
        portable = self.root / "portable"
        shutil.copytree(package, portable)
        shutil.rmtree(self.root / "runs")
        shutil.rmtree(self.root / "outputs")
        restored = self.root / "restored"
        bundles.extract(portable, restored)
        self.assertEqual(file_hash(prepared.verify(restored, self.asset, self.source_sha)), self.asset["sha256"])
        self.assertEqual(file_hash(restored / "outputs/result.mp4"), self.video_sha)

    def test_registered_demand_name_is_used_by_export_and_lookup(self):
        write_json(self.root / 'state/delivery-folders.json',
                   {'sources': {self.source_sha: '需求视频-01'}})
        result = library.export(self.run, self.root)
        self.assertTrue(result['package'].startswith('outputs/需求视频-01/zh-CN/'))
        self.assertEqual(library.find(self.source_sha, root=self.root)[0]['availability'], 'available')
        self.assertTrue(library.export(self.run, self.root)['reused'])
        self.assertFalse((self.root / 'outputs' / self.source_sha[:16]).exists())

    def test_knowledge_survives_expiry_of_both_runs_and_outputs(self):
        method = self.root / "knowledge/local/rules/example.md"
        method.parent.mkdir(parents=True)
        method.write_text("Preserve the foreground icon above one continuous translated phrase.", encoding="utf-8")
        case = learning.capture_case("example", "independent icon", self.scope, self.root, self.run,
                                     self.video_sha, records=[self.run / "review/review.json"])
        entry = {"id": "example", "path": method.relative_to(self.root).as_posix(), "status": "active",
                 "case": case.relative_to(self.root).as_posix(), "scope": self.scope, "method_sha256": file_hash(method)}
        write_json(self.root / "config/knowledge.local.json", {"entries": [entry]})
        library.export(self.run, self.root)
        shutil.rmtree(self.root / "runs")
        shutil.rmtree(self.root / "outputs")
        self.assertEqual(learning.audit(self.root)["active_entries"], 1)
        with patch.object(knowledge, "ROOT", self.root):
            self.assertEqual([e["id"] for e in knowledge.retrieve(self.scope)], ["example"])

    def test_missing_evidence_blocks_retrieval_instead_of_silent_knowledge_loss(self):
        case = learning.capture_case("example", "lesson", self.scope, self.root, self.run, self.video_sha)
        method = self.root / "knowledge/local/method.md"
        method.write_text("Independent method", encoding="utf-8")
        entry = {"id": "example", "path": "knowledge/local/method.md", "status": "active", "scope": self.scope,
                 "case": case.relative_to(self.root).as_posix()}
        write_json(self.root / "knowledge/index.json", {"entries": [entry]})
        first = read_json(case / "manifest.json")["files"][0]
        (case / first["path"]).unlink()
        with patch.object(knowledge, "ROOT", self.root), self.assertRaisesRegex(WorkflowError, "missing or changed"):
            knowledge.retrieve(self.scope)

    def test_mutating_run_does_not_mutate_permanent_evidence(self):
        case = learning.capture_case("example", "lesson", self.scope, self.root, self.run, self.video_sha)
        self.put("review/" + self.video_sha[:12] + "/observed.png", b"later-different-pixels")
        self.assertEqual(bundles.verify(case)["identity"], "example")

    def test_cross_source_assets_rejected_and_no_partial_catalog_entry(self):
        data = read_json(self.run / "outputs/preparation.json")
        data["inputs"][0]["sha256"] = "0" * 64
        write_json(self.run / "outputs/preparation.json", data)
        with self.assertRaises(WorkflowError):
            library.export(self.run, self.root)
        self.assertFalse((self.root / "outputs/index.json").exists())

    def test_archive_idempotence_and_expired_catalog(self):
        first = library.export(self.run, self.root)
        self.assertTrue(library.export(self.run, self.root)["reused"])
        self.assertEqual(len(library.find(self.source_sha, root=self.root)), 1)
        shutil.rmtree(self.root / first["package"])
        self.assertEqual(library.find(self.source_sha, root=self.root)[0]["availability"], "expired")

    def test_historical_revise_reference_is_not_upgraded_to_delivered(self):
        write_json(self.run / "outputs/quality.json", {"video_sha256": self.video_sha, "decision": "revise"})
        result = library.export(self.run, self.root, self.video_sha)
        self.assertEqual(result["status"], "historical_reference")
        self.assertEqual(bundles.verify(self.root / result["package"])["metadata"]["technical_decision"], "revise")

    def test_bundle_rejects_path_escape_and_restore_overwrite(self):
        with self.assertRaisesRegex(WorkflowError, "stay within"):
            bundles.create(self.root / "unsafe", "case", "id", {"../escape": self.run / "run.json"})
        package = self.root / library.export(self.run, self.root)["package"]
        with self.assertRaisesRegex(WorkflowError, "already exists"):
            bundles.extract(package, self.run)

    def test_pending_learning_is_idempotent_and_never_activated(self):
        candidate = {"id": "case-one", "hypothesis": "same lesson", "scope": self.scope}
        first = learning.enqueue(candidate, self.root)
        self.assertEqual(first, learning.enqueue(candidate, self.root))
        self.assertEqual(read_json(self.root / first)["status"], "pending_distillation")
        self.assertEqual(learning.audit(self.root)["active_entries"], 0)

    def test_project_method_rejects_a_private_evidence_dependency(self):
        case = learning.capture_case("example", "lesson", self.scope, self.root, self.run, self.video_sha)
        method = self.root / "knowledge/public-method.md"
        method.write_text("A project method", encoding="utf-8")
        entry = {"id": "example", "path": "knowledge/public-method.md", "scope": self.scope,
                 "case": case.relative_to(self.root).as_posix()}
        with self.assertRaisesRegex(WorkflowError, "must not require private"):
            learning.verify_entry(entry, self.root)

    def test_published_project_method_works_without_private_or_runtime_files(self):
        method = self.root / "knowledge/rules/public-method.md"
        method.parent.mkdir(parents=True)
        method.write_text("Use actual speech pauses and inspect encoded caption boundaries.", encoding="utf-8")
        write_json(self.root / "work/reviewed-observation.json", {"video_sha256": self.video_sha,
            "observation": "A following phrase appeared during a measured pause", "reviewer": "developer"})
        spec = {"id": "public-method", "path": "knowledge/rules/public-method.md", "scope": self.scope,
            "tags": ["caption"], "origin": "developer-reviewed observation", "reviewed_by": "developer",
            "approval_type": "developer_review", "evidence_review": "sanitized_project_evidence",
            "source_run": self.run.name, "reference_video_sha256": self.video_sha, "company_preference": False,
            "evidence_files": ["work/reviewed-observation.json"]}
        write_json(self.root / "work/spec.json", spec)
        learning.promote("work/spec.json", self.root)
        shutil.rmtree(self.root / "runs")
        shutil.rmtree(self.root / "work")
        self.assertFalse((self.root / "knowledge/local").exists())
        self.assertEqual(learning.audit(self.root)["active_entries"], 1)

    def test_technical_candidate_keeps_its_business_content(self):
        candidate = {"id": "method-one", "hypothesis": "Icon and connected letters are separate objects.",
                     "scope": self.scope, "case": "knowledge/local/examples/private-observations"}
        path = learning.record_project_candidate(candidate, self.root)
        saved = read_json(self.root / path)
        self.assertEqual(saved["hypothesis"], candidate["hypothesis"])
        self.assertEqual(saved["scope"], candidate["scope"])
        self.assertNotIn("case", saved)
        self.assertEqual(saved["status"], "candidate")

    def test_modified_manifest_is_not_an_available_reuse_package(self):
        result = library.export(self.run, self.root)
        manifest = self.root / result["package"] / "manifest.json"
        data = read_json(manifest)
        data["metadata"]["technical_decision"] = "invented-new-decision"
        write_json(manifest, data)
        self.assertEqual(library.find(self.source_sha, root=self.root)[0]["availability"], "invalid")

    def test_frozen_ancestor_paths_are_not_live_preparation_dependencies(self):
        write_json(self.run / "inputs/ancestor.json", {"output": {"path": "old-output-no-longer-live.mp4", "sha256": "0" * 64}})
        prep = read_json(self.run / self.asset["record"])
        prep["inputs"].append({"path": "inputs/ancestor.json", "sha256": file_hash(self.run / "inputs/ancestor.json")})
        write_json(self.run / self.asset["record"], prep)
        self.asset["record_sha256"] = file_hash(self.run / self.asset["record"])
        write_json(self.run / "analysis/inventory.json", {"shots": [{"prepared_video": self.asset}]})
        result = library.export(self.run, self.root)
        restored = self.root / "restored"
        bundles.extract(self.root / result["package"], restored)
        self.assertTrue(prepared.verify(restored, self.asset, self.source_sha).is_file())

    def test_context_returns_asset_catalog_separately_from_knowledge(self):
        library.export(self.run, self.root)
        output = io.StringIO()
        with patch.object(cli, "ROOT", self.root), patch.object(cli, "get_run", return_value=self.run), \
                patch.object(knowledge, "ROOT", self.root), redirect_stdout(output):
            self.assertEqual(cli.main(["context", "test-source"]), 0)
        import json
        actual = json.loads(output.getvalue())
        self.assertEqual(actual["knowledge"], [])
        self.assertEqual(actual["reusable_packages"][0]["availability"], "available")
