import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from video_localizer import storage, storage_policy
from video_localizer.common import WorkflowError, read_json, write_json

TEMP = PROJECT / "work/test-tmp"
TEMP.mkdir(parents=True, exist_ok=True)


class StoragePolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP)
        self.root = Path(self.temp.name)
        write_json(self.root / storage_policy.CONFIG, read_json(PROJECT / storage_policy.CONFIG))

    def tearDown(self):
        self.temp.cleanup()

    def task(self, name, quality="pass", state="success"):
        run = self.root / "runs" / name
        write_json(run / "run.json", {"source_sha256": "a" * 64})
        if quality:
            write_json(run / "outputs/quality.json", {"decision": quality})
        write_json(run / "jobs/task.json", {"state": state})
        return run

    def test_user_override_preserves_defaults_and_is_never_delete_mode(self):
        original = (self.root / storage_policy.CONFIG).read_bytes()
        storage_policy.configure(self.root, area="runs", max_count=4, max_gib=2)
        storage_policy.configure(self.root, area="outputs", max_count=50, minimum_free_gib=3)
        actual = storage_policy.settings(self.root)
        self.assertEqual(actual["runs"], {"max_count": 4, "max_gib": 2})
        self.assertEqual(actual["outputs"]["max_count"], 50)
        self.assertEqual(actual["minimum_free_gib"], 3)
        self.assertEqual(actual["mode"], "preview_only")
        self.assertEqual((self.root / storage_policy.CONFIG).read_bytes(), original)

    def test_invalid_or_nonfinite_limits_do_not_write(self):
        for args in ({"max_count": 2}, {"area": "runs", "max_count": -1},
                     {"area": "runs", "max_gib": float("nan")},
                     {"minimum_free_gib": float("inf")}):
            with self.assertRaises(WorkflowError):
                storage_policy.configure(self.root, **args)
        self.assertFalse((self.root / storage_policy.OVERRIDE).exists())

    def test_preview_flags_limits_and_retains_locked_unknown_and_unfinished_tasks(self):
        self.task("locked")
        write_json(self.root / "runs/.locks/locked.lock", {})
        self.task("unknown", state="ambiguous")
        self.task("unfinished", quality=None)
        self.task("closed")
        storage_policy.configure(self.root, area="runs", max_count=1, max_gib=0)
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        result = storage_policy.plan(self.root)
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(result["deleted_files"], 0)
        self.assertTrue(result["budgets"]["runs"]["over_count"])
        self.assertFalse(result["budgets"]["runs"]["over_bytes"])
        tasks = {e["run"]: e for e in result["runs"]}
        for name in ("locked", "unknown", "unfinished"):
            self.assertEqual(tasks[name]["next_step"], "retain")
        self.assertIn("confirm_idle", tasks["closed"]["next_step"])

    def test_loose_zip_counts_towards_capacity_not_delivery_count(self):
        package = self.root / "outputs/source/es/version"
        write_json(package / "manifest.json", {"metadata": {}})
        write_json(self.root / "outputs/index.json", {"entries": [
            {"package": "outputs/source/es/version"}, {"package": "outputs/source/es/version"}]})
        (self.root / "outputs/download.zip").write_bytes(b"duplicate")
        (self.root / "outputs/index.html").write_text("links only", encoding="utf-8")
        write_json(self.root / "outputs/reports/batch/notes.json", {"note": "retained"})
        storage_policy.configure(self.root, area="outputs", max_gib=0.000000001)
        result = storage_policy.plan(self.root)
        self.assertEqual(result["budgets"]["outputs"]["count"], 1)
        self.assertTrue(result["budgets"]["outputs"]["over_bytes"])
        self.assertEqual(result["unmanaged_output_entries"], ["download.zip"])

    def test_pinned_source_is_protected_even_after_quality_pass(self):
        self.task("keep")
        write_json(self.root / storage_policy.OVERRIDE, {"pinned_sources": ["a" * 64]})
        result = storage_policy.plan(self.root)
        self.assertIn("pinned", result["runs"][0]["blockers"])

    def test_catalog_cannot_escape_outputs(self):
        write_json(self.root / "outputs/index.json", {"entries": [{"package": "knowledge/example"}]})
        with self.assertRaisesRegex(WorkflowError, "escapes outputs"):
            storage_policy.plan(self.root)

    def test_report_tolerates_file_disappearing_during_scan(self):
        folder = self.root / "work"
        folder.mkdir()
        (folder / "stable.txt").write_bytes(b"kept")
        # Reproduce a directory listing made just before a worker removes a file.
        with patch.object(storage.os, "walk", return_value=iter([
                (str(folder), [], ["stable.txt", "already-removed.tmp"])])):
            result = storage.report(self.root)
        self.assertEqual(result["areas"]["work"]["logical_bytes"], 4)
        self.assertIn("work/already-removed.tmp", result["skipped_unavailable"])

    def test_report_separates_installed_models_from_scratch_without_deleting(self):
        for relative, data in [('.runtime/models/asr/base.bin', b'model'),
                               ('.runtime/deps/asr/runtime.py', b'lib'),
                               ('work/probe/result.png', b'probe')]:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        result = storage.report(self.root)
        groups = result['areas']['work']['retention_groups']
        self.assertEqual(groups['runtime_dependencies']['logical_bytes'], 0)
        self.assertEqual(result['areas']['.runtime']['logical_bytes'], 8)
        self.assertEqual(groups['scratch_and_unclassified']['logical_bytes'], 5)
        self.assertTrue((self.root / 'work/probe/result.png').exists())
        self.assertEqual(result['areas']['work']['largest_children'][0]['logical_bytes'], 5)
