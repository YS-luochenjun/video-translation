import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from video_localizer import storage, workspace
from video_localizer.common import WorkflowError, read_json, write_json

TEMP = Path(__file__).resolve().parents[1] / "work/test-tmp"
TEMP.mkdir(parents=True, exist_ok=True)


class FreshWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP)
        self.root = Path(self.temp.name)
        self.source = self.root / "development"
        for name in ("AGENTS.md", ".env.example", "README.md", "pyproject.toml",
                     ".gitignore", ".gitattributes", "src/example.py", "bin/va.py",
                     "docs/guide.md", "tests/test_example.py", "knowledge/rules/method.md",
                     "workbench/server.py", "workbench/start.ps1", "workbench/static/app.js"):
            self.put(name, b"public\r\nbytes\n")
        write_json(self.source / "knowledge/index.json", {"entries": []})
        write_json(self.source / "config/workspace.json", {})
        self.target = self.root / "fresh"

    def put(self, relative, value):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
        return path

    def tearDown(self):
        self.temp.cleanup()

    def test_fresh_export_preserves_public_bytes_and_excludes_development_data(self):
        adoption = b'{"review": "public adoption map", "records": []}\n'
        self.put("knowledge/curation/adoption.json", adoption)
        self.put("knowledge/README.md", b"Knowledge navigation\n")
        self.put("knowledge/history/rules/old.md", b"Superseded, provenance only\n")
        private = (".env", "config/hooks.local.json", "knowledge/local/customer.txt",
                   "runs/old/input.mp4", "outputs/old.mp4", "media/old.wav", "state/job.json",
                   ".archive/old.mp4", "work/model.bin", "assets/fonts/local.ttf",
                   ".git/config", "src/__pycache__/example.pyc", "docs/.env.local",
                   ".codex/config.toml", "docs/verification/local-report.json",
                   "workbench/.env", "workbench/private.local.json",
                   "workbench/__pycache__/server.pyc")
        for name in private:
            self.put(name, b"private marker")
        result = workspace.export(self.target, self.source)
        self.assertEqual(result["decision"], "pass")
        for name in private:
            self.assertFalse((self.target / name).exists(), name)
        self.assertEqual((self.target / "knowledge/rules/method.md").read_bytes(), b"public\r\nbytes\n")
        self.assertEqual((self.target / "knowledge/curation/adoption.json").read_bytes(), adoption)
        self.assertEqual((self.target / "knowledge/history/rules/old.md").read_bytes(),
                         b"Superseded, provenance only\n")
        self.assertTrue((self.target / "knowledge/README.md").is_file())
        self.assertTrue((self.target / "bin/va.py").is_file())
        for name in ("workbench/server.py", "workbench/start.ps1", "workbench/static/app.js"):
            self.assertEqual((self.target / name).read_bytes(), b"public\r\nbytes\n")
        for name in ("runs", "outputs", "media", "state", "knowledge/local"):
            self.assertEqual(list((self.target / name).iterdir()), [])

    def test_export_cannot_overwrite_or_nest_into_preserved_data(self):
        workspace.export(self.target, self.source)
        with self.assertRaisesRegex(WorkflowError, "already exists"):
            workspace.export(self.target, self.source)
        for name in ("knowledge", "runs", "media", "agent", "docs", "src", "workbench"):
            with self.assertRaisesRegex(WorkflowError, "overlaps"):
                workspace.export(self.source / name / "fresh", self.source)

    def test_nested_configuration_and_context_survive_init_and_export(self):
        profile = "config/profiles/company-default/profile.json"
        method = "config/profiles/company-default/method.md"
        prompt = "config/hooks/knowledge-curation/prompt.md"
        write_json(self.source / profile, {"method": method})
        write_json(self.source / "config/hooks.json", {"knowledge_daily": {"prompt": prompt}})
        files = (method, prompt, "config/workflows/video-localization/workflow.json",
                 "agent/contracts/workflow.md", "agent/workflows/video-localization.md",
                 "agent/integrations/kie.md", "agent/templates/inventory-example.json",
                 ".agents/skills/video-localization/SKILL.md")
        for name in files:
            self.put(name, b"public context")
        private = ("config/profiles/company-default/authorization.local.json",
                   "config/hooks/.env", "agent/templates/private.local.json")
        for name in private:
            self.put(name, b"private")
        targets = (self.root / "initialized", self.target)
        workspace.initialize(targets[0], self.source)
        workspace.export(targets[1], self.source)
        for target in targets:
            for name in files:
                self.assertEqual((target / name).read_bytes(), b"public context")
            self.assertTrue((target / read_json(target / profile)["method"]).is_file())
            self.assertTrue((target / read_json(target / "config/hooks.json")["knowledge_daily"]["prompt"]).is_file())
            for name in private:
                self.assertFalse((target / name).exists(), name)

    def test_initialization_cannot_reenter_public_or_production_trees(self):
        for name in ("agent", "docs", "config/profiles", ".agents/skills", "knowledge", "runs", "outputs", "state", "workbench"):
            target = self.source / name / "nested"
            with self.assertRaisesRegex(WorkflowError, "overlaps"):
                workspace.initialize(target, self.source)
            self.assertFalse(target.exists())

    def test_verify_detects_tampered_code_and_allows_new_task_data(self):
        workspace.export(self.target, self.source)
        (self.target / "runs/new").mkdir()
        self.assertEqual(workspace.verify_export(self.target)["decision"], "pass")
        (self.target / "src/example.py").write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(WorkflowError, "missing or changed"):
            workspace.verify_export(self.target)

    def test_source_link_cannot_export_private_data(self):
        external = self.root / "secret.txt"
        external.write_bytes(b"not public")
        link = self.source / "docs/linked.txt"
        try:
            link.symlink_to(external)
        except OSError:
            self.skipTest("Creating symbolic links is not available on this host")
        with self.assertRaisesRegex(WorkflowError, "link"):
            workspace.export(self.target, self.source)
        self.assertFalse(self.target.exists())

    def test_storage_report_measures_overlap_without_deleting_independent_copies(self):
        for name in ("runs/new/source.mp4", "media/source/original.mp4",
                     "knowledge/examples/case/source.mp4"):
            self.put(name, b"identical source")
        self.put("outputs/final.mp4", b"different result")
        result = storage.report(self.source, duplicates=True)
        self.assertEqual(result["duplicate_groups"], 1)
        self.assertEqual(result["extra_logical_bytes"], 2 * len(b"identical source"))
        self.assertEqual(len(result["largest_duplicates"][0]["paths"]), 3)
        self.assertTrue((self.source / "runs/new/source.mp4").exists())


if __name__ == "__main__":
    unittest.main()
