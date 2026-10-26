import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("repository_check", ROOT / "bin/check_repository.py")
repository_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repository_check)


class RepositoryBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for name in ("AGENTS.md", ".env.example", "README.md", "pyproject.toml",
                     ".gitignore", ".gitattributes"):
            self.put(name, "fixture\n")
        self.put("knowledge/index.json", '{"entries": []}')

    def tearDown(self):
        self.temp.cleanup()

    def put(self, name, body):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    def test_existing_local_report_is_not_a_valid_portable_document_link(self):
        self.put("docs/verification/result.json", "{}")
        self.put("README.md", "[Result](docs/verification/result.json)\n")
        result = repository_check.check(self.root)
        self.assertEqual(result["decision"], "fail")
        self.assertTrue(any("Link missing from source package" in e for e in result["errors"]))
        self.put("docs/history.md", "Summary; runtime logs remain local.\n")
        self.put("README.md", "[Summary](docs/history.md)\n")
        self.assertEqual(repository_check.check(self.root)["decision"], "pass")

    def test_agent_pointer_must_resolve_inside_the_portable_package(self):
        self.put("AGENTS.md", "Read `agent/contracts/workflow.md`.\n")
        result = repository_check.check(self.root)
        self.assertEqual(result["decision"], "fail")
        self.assertTrue(any("agent/contracts/workflow.md" in e for e in result["errors"]))
        self.put("agent/contracts/workflow.md", "Run the workflow.\n")
        self.assertEqual(repository_check.check(self.root)["decision"], "pass")

    def test_retired_body_remains_portable_and_replacement_must_resolve(self):
        self.put("knowledge/history/rules/old.md", "Earlier scope\n")
        self.put("knowledge/rules/current.md", "Current scope\n")
        entries = [
            {"id": "old", "path": "knowledge/history/rules/old.md",
             "status": "superseded", "superseded_by": "current"},
            {"id": "current", "path": "knowledge/rules/current.md", "status": "active"},
        ]
        self.put("knowledge/index.json", json.dumps({"entries": entries}))
        self.assertEqual(repository_check.check(self.root)["decision"], "pass")
        entries[0]["superseded_by"] = "missing"
        self.put("knowledge/index.json", json.dumps({"entries": entries}))
        self.assertIn("Missing knowledge successor: missing", repository_check.check(self.root)["errors"])


if __name__ == "__main__":
    unittest.main()
