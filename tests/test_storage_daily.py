import importlib.util
import io
import json
from pathlib import Path
import tempfile
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from video_localizer.common import CODE_ROOT, WorkflowError, read_json, write_json

spec = importlib.util.spec_from_file_location("storage_daily", CODE_ROOT / "bin/storage_daily.py")
daily = importlib.util.module_from_spec(spec)
spec.loader.exec_module(daily)


class StorageDailyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        write_json(self.root / "config/storage-authorization.local.json", {
            "workspace": str(self.root), "automatic_cleanup": True})
        self.preview = patch.object(daily.project_storage, "preview", return_value={
            "selected": [{"path": "runs/closed", "logical_bytes": 128}],
            "unavailable_entries": [], "pressure": False, "fingerprint": "frozen"}).start()
        self.execute = patch.object(daily.project_storage, "execute", return_value={
            "deleted": [{"path": "runs/closed"}], "logical_bytes_removed": 128,
            "net_free_bytes_change": 64, "preserved_records": "state/expired-production/frozen/records",
            "accounting_sync_errors": []}).start()
        self.addCleanup(patch.stopall)

    def test_default_only_plans_without_receipt_or_execution(self):
        result = daily.run(self.root)
        self.assertEqual(result["state"], "planned")
        self.assertTrue(result["would_execute"])
        self.assertFalse((self.root / daily.RECEIPT).exists())
        self.execute.assert_not_called()
        self.preview.assert_called_once_with(self.root)

    def test_explicit_execution_uses_current_fingerprint_and_short_actual_receipt(self):
        result = daily.run(self.root, execute=True)
        self.execute.assert_called_once_with(self.root, "frozen")
        self.assertEqual(result["state"], "executed")
        self.assertEqual(result["net_free_bytes_change"], 64)
        self.assertEqual(result["deleted_count"], 1)
        self.assertEqual(read_json(self.root / daily.RECEIPT), result)
        self.assertNotIn("selected", result)
        self.assertNotIn("deleted", result)

    def test_unavailable_old_index_alone_triggers_reconciliation(self):
        self.preview.return_value["selected"] = []
        self.preview.return_value["unavailable_entries"] = ["outputs/.packages/old"]
        self.execute.return_value["deleted"] = []
        result = daily.run(self.root, execute=True)
        self.assertEqual(result["state"], "executed")
        self.assertEqual(result["unavailable_count"], 1)
        self.execute.assert_called_once_with(self.root, "frozen")

    def test_empty_plan_does_not_execute(self):
        self.preview.return_value["selected"] = []
        result = daily.run(self.root, execute=True)
        self.assertEqual(result["state"], "no_eligible_data")
        self.execute.assert_not_called()

    def test_missing_or_wrong_workspace_authorization_defers(self):
        for auth in (None, {"workspace": "another workspace", "automatic_cleanup": True},
                     {"workspace": str(self.root), "automatic_cleanup": False}):
            with self.subTest(auth=auth):
                path = self.root / "config/storage-authorization.local.json"
                if auth is None:
                    path.unlink(missing_ok=True)
                else:
                    write_json(path, auth)
                result = daily.run(self.root, execute=True)
                self.assertEqual(result["state"], "deferred")
                self.assertEqual(result["reason"], "workspace_authorization_missing")
                self.assertEqual(read_json(self.root / daily.RECEIPT), result)
        self.preview.assert_not_called()
        self.execute.assert_not_called()

    def test_each_lock_defers_without_touching_lock_or_media(self):
        media = self.root / "runs/closed/video.mp4"
        media.parent.mkdir(parents=True)
        media.write_bytes(b"synthetic fixture")
        for relative in ("runs/.locks/active.lock", "state/resources/heavy.lock", "state/project-storage.lock"):
            with self.subTest(lock=relative):
                path = self.root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture", encoding="utf-8")
                result = daily.run(self.root, execute=True)
                self.assertEqual(result["state"], "deferred")
                self.assertIn(relative, result["locks"])
                self.assertEqual(media.read_bytes(), b"synthetic fixture")
                self.assertTrue(path.exists())
                path.unlink()
        self.preview.assert_not_called()
        self.execute.assert_not_called()

    def test_new_lock_after_preview_is_deferred_without_retry(self):
        def racing_execute(*args):
            path = self.root / "state/project-storage.lock"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("other sweep", encoding="utf-8")
            raise WorkflowError("Operation locked")
        self.execute.side_effect = racing_execute
        result = daily.run(self.root, execute=True)
        self.assertEqual(result["state"], "deferred")
        self.execute.assert_called_once()
        self.assertTrue((self.root / "state/project-storage.lock").exists())

    def test_invalid_authorization_and_executor_failure_save_failed_receipt(self):
        self.execute.side_effect = WorkflowError("Storage preview changed")
        result = daily.run(self.root, execute=True)
        self.assertEqual(result["state"], "failed")
        self.assertIn("preview changed", result["error"])
        self.execute.assert_called_once()
        path = self.root / "config/storage-authorization.local.json"
        path.write_text("{broken", encoding="utf-8")
        result = daily.run(self.root, execute=True)
        self.assertEqual(result["state"], "failed")
        self.assertEqual(read_json(self.root / daily.RECEIPT), result)

    def test_cli_requires_explicit_execute_and_reports_failure_exit(self):
        with patch.object(daily, "run", return_value={"state": "planned"}) as run:
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(daily.main([]), 0)
            run.assert_called_once_with(execute=False)
            self.assertEqual(json.loads(output.getvalue())["state"], "planned")
        with patch.object(daily, "run", return_value={"state": "failed"}) as run:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(daily.main(["--execute"]), 1)
            run.assert_called_once_with(execute=True)

    def test_scheduler_contract_is_explicit_and_separate_from_knowledge(self):
        text = (CODE_ROOT / "bin/project-storage.ps1").read_text(encoding="utf-8")
        for required in ("[switch]$Execute", "if (-not $Execute)", "-StartWhenAvailable",
                         "-MultipleInstances IgnoreNew", "AddHours(18).AddMinutes(30)",
                         "VideoLocalizer-Storage-$taskSuffix", "--execute", ".venv\\Scripts\\python.exe",
                         "-WorkingDirectory $projectRoot", "ToLowerInvariant()"):
            self.assertIn(required, text)
        self.assertNotIn("storage-reset", text)
        self.assertNotIn("-Force", text)
        self.assertNotIn("knowledge", text.lower())


if __name__ == "__main__":
    unittest.main()
