import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from video_localizer import bundles, candidate_index, knowledge_maintenance as maintenance
from video_localizer.common import WorkflowError, file_hash, read_json, write_json


class KnowledgeMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = self.root / "frame.jpg"
        source.write_bytes(b"same historical evidence")
        for name, language in (("a", "de"), ("b", "ja")):
            bundles.create(self.root / "knowledge/examples" / name, "knowledge-case", name,
                           {"evidence/frame.jpg": source}, {"scope": {"target_language": language}})

    def compact(self):
        return maintenance.compact(self.root, maintenance.preview(self.root)["fingerprint"])

    def test_compaction_preserves_manifests_and_is_portable_and_idempotent(self):
        before = {p.relative_to(self.root): p.read_bytes()
                  for p in self.root.glob("knowledge/examples/*/manifest.json")}
        result = self.compact()
        self.assertEqual(result["removed_files"], 2)
        self.assertEqual(result["shared_objects"], 1)
        self.assertEqual(result["logical_bytes_removed"], len(b"same historical evidence"))
        for path, value in before.items():
            self.assertEqual((self.root / path).read_bytes(), value)
        self.assertEqual(self.compact()["removed_files"], 0)
        portable = self.root / "portable"
        shutil.copytree(self.root / "knowledge", portable / "knowledge")
        shutil.rmtree(self.root / "knowledge")
        self.assertEqual(maintenance.audit(portable)["bundles"], 2)
        resolved = maintenance.resolve_path(portable, "knowledge/examples/a/evidence/frame.jpg")
        self.assertTrue(Path(resolved["path"]).is_file())
        self.assertEqual(bundles.verify(portable / "knowledge/examples/b")["metadata"]["scope"],
                         {"target_language": "ja"})

    def test_tampering_and_missing_object_fail_closed(self):
        self.compact()
        path = next((self.root / "knowledge/examples/_objects").glob("*"))
        path.write_bytes(b"wrong")
        with self.assertRaises(WorkflowError):
            maintenance.audit(self.root)
        path.unlink()
        with self.assertRaises(WorkflowError):
            maintenance.audit(self.root)

    def test_storage_escape_and_wrong_alias_hash_are_rejected(self):
        self.compact()
        path = self.root / "knowledge/examples/storage-index.json"
        record = read_json(path)
        alias = next(iter(record["aliases"].values()))
        alias["object"] = "../outside.jpg"
        write_json(path, record)
        with self.assertRaises(WorkflowError):
            maintenance.audit(self.root)
        alias["object"] = "_objects/" + "0" * 64 + ".jpg"
        write_json(path, record)
        with self.assertRaises(WorkflowError):
            maintenance.audit(self.root)

    def test_stale_preview_does_not_delete(self):
        plan = maintenance.preview(self.root)
        path = self.root / "knowledge/examples/a/manifest.json"
        record = read_json(path)
        record["metadata"]["new_judgment"] = "hold"
        write_json(path, record)
        with self.assertRaises(WorkflowError):
            maintenance.compact(self.root, plan["fingerprint"])
        self.assertTrue((path.parent / "evidence/frame.jpg").exists())

    def test_dangling_alias_fails(self):
        self.compact()
        path = self.root / "knowledge/examples/storage-index.json"
        record = read_json(path)
        record["aliases"]["nonexistent/evidence.jpg"] = next(iter(record["aliases"].values()))
        write_json(path, record)
        with self.assertRaises(WorkflowError):
            maintenance.audit(self.root)

    def test_candidate_index_preserves_status_scope_outcome_and_partial_adoption(self):
        originals = {}
        for name, language in (("a", "de"), ("b", "ja")):
            path = self.root / f"knowledge/candidates/{name}.json"
            write_json(path, {"id": name, "status": "candidate", "hypothesis": "shared wording",
                              "outcome": "fail", "scope": {"target_language": language}})
            originals[path] = path.read_bytes()
        write_json(self.root / "knowledge/curation/candidate-adoption-test.json", {
            "groups": {"g": {"adopted_in": ["historical-method"], "retained": "failed route"}},
            "records": [{"path": "knowledge/candidates/a.json", "sha256": file_hash(next(iter(originals))), "group": "g"}]})
        index = candidate_index.refresh(self.root)
        self.assertEqual(index["counts"], {"partial_adoption_recorded": 1, "no_adoption_record": 1})
        self.assertEqual(len(index["exact_hypothesis_groups"]), 1)
        for entry in index["entries"]:
            self.assertEqual(entry["status"], "candidate")
            self.assertEqual(entry["historical_outcome"], "fail")
        for path, raw in originals.items():
            self.assertEqual(path.read_bytes(), raw)
        candidate_index.verify(self.root)
        write_json(self.root / "knowledge/candidates/new.json", {"id": "new"})
        with self.assertRaises(WorkflowError):
            candidate_index.verify(self.root)
        candidate_index.refresh(self.root)
        next(iter(originals)).write_text('{}')
        with self.assertRaises(WorkflowError):
            candidate_index.refresh(self.root)

    def test_reviewed_synthetic_and_archive_records_are_not_adoptions(self):
        records = []
        for name in ("synthetic", "archive"):
            path = self.root / f"knowledge/candidates/{name}.json"
            write_json(path, {"id": name, "status": "candidate"})
            records.append({"path": path.relative_to(self.root).as_posix(),
                            "sha256": file_hash(path), "group": name})
        write_json(self.root / "knowledge/curation/candidate-adoption-test.json", {
            "groups": {"synthetic": {"disposition": "synthetic_only", "adopted_in": []},
                       "archive": {"disposition": "archive_only", "adopted_in": []}},
            "records": records})
        self.assertEqual(candidate_index.refresh(self.root)["counts"],
                         {"historical_retained": 1, "synthetic_only": 1})


if __name__ == "__main__":
    unittest.main()
