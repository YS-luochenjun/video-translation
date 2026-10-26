import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from video_localizer import curation, curation_engine
from video_localizer.common import WorkflowError, file_hash, read_json, write_json

PROJECT = Path(__file__).resolve().parents[1]
TEMP = PROJECT / "work/test-tmp"
TEMP.mkdir(parents=True, exist_ok=True)


class CurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP)
        self.root = Path(self.temp.name)
        write_json(self.root / "config/hooks.json", read_json(PROJECT / "config/hooks.json"))
        write_json(self.root / "knowledge/index.json", {"entries": []})
        prompt = self.root / "config/hooks/knowledge-curation/prompt.md"
        prompt.parent.mkdir(parents=True)
        prompt.write_text("Reason only, return data", encoding="utf-8")
        self.scope = {"workflow": "video-localization", "source_sha256": "a" * 64, "target_language": "zh-CN"}
        curation.baseline(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def event(self, name, scope=None, private=False):
        path = self.root / ("knowledge/local/candidates" if private else "knowledge/candidates") / (name + ".json")
        write_json(path, {"id": name, "hypothesis": "Preserve original icon above translated line", "scope": scope or self.scope,
                          "limitations": ["One actual source only"], "evidence": {"video_sha256": "b" * 64}})
        return path

    def answer(self, value, merge_into=""):
        return {"groups": [{"event_ids": [e["event_id"] for e in value["events"]], "same_meaning": True,
                            "merge_into": merge_into, "title": "Preserve icon", "trigger": "Text overlaps an icon",
                            "action": "Reconstruct glyphs beneath icon", "failure_signature": "Arrow contains old glyph",
                            "limitations": ["Source-specific observation"], "next_counterexample_test": "New moving source",
                            "conflict_with_rules": False}], "pending": []}

    def run_hook(self):
        return curation.execute(self.root, engine=lambda value, *args: self.answer(value))

    def test_adoption_proposal_is_retained_but_never_activates(self):
        self.event("one")
        def engine(value, *args):
            response = self.answer(value)
            response["groups"][0]["adoption"] = {"action": "new_method", "target_ids": [],
                "reason": "No existing method covers this observation", "missing_evidence": ["Another source"]}
            return response
        report = curation.execute(self.root, engine=engine)
        record = read_json(self.root / report["artifacts"][0]["path"])
        self.assertEqual(record["adoption_proposal"]["action"], "new_method")
        self.assertEqual(read_json(self.root / "knowledge/index.json")["entries"], [])
        saved = [read_json(p) for p in (self.root / curation.STATE / "reports").glob("*.json")]
        self.assertTrue(any(r.get("adoption_queue_open") == report["adoption_queue_open"] for r in saved))

    def test_unknown_adoption_target_rejected(self):
        self.event("one")
        def engine(value, *args):
            response = self.answer(value)
            response["groups"][0]["adoption"] = {"action": "merge_existing", "target_ids": ["invented"],
                "reason": "Unverified suggestion", "missing_evidence": []}
            return response
        with self.assertRaisesRegex(WorkflowError, "Unknown adoption"):
            curation.execute(self.root, engine=engine)

    def test_baseline_is_explicit_and_changes_are_incremental(self):
        with self.assertRaisesRegex(WorkflowError, "already exists"):
            curation.baseline(self.root)
        path = self.event("one")
        self.assertEqual(curation.status(self.root)["new_records"], 1)
        self.run_hook()
        self.assertEqual(curation.status(self.root)["new_records"], 0)
        data = read_json(path)
        data["hypothesis"] += "; preserve entry animation"
        write_json(path, data)
        self.assertEqual(curation.status(self.root)["new_records"], 1)

    def test_duplicates_preserve_all_sources_and_do_not_activate(self):
        self.event("one")
        self.event("two")
        before = curation.protected(self.root)
        report = self.run_hook()
        record = next(iter(curation.catalogs(self.root).values()))
        self.assertEqual(len(record["sources"]), 2)
        self.assertEqual(record["scope"], self.scope)
        self.assertEqual(record["status"], "candidate")
        self.assertEqual(curation.protected(self.root), before)
        self.assertEqual(report["merged"], 1)
        self.assertEqual(report["paid_media_model_credits"], 0)
        # Embedded source text remains readable without production inputs.
        self.assertEqual(record["sources"][0]["record"]["limitations"], ["One actual source only"])

    def test_scope_widening_rejected_without_checkpoint_progress(self):
        self.event("one")
        self.event("two", {**self.scope, "target_language": "ja-JP"})
        previous = file_hash(self.root / curation.STATE / "checkpoint.json")
        with self.assertRaisesRegex(WorkflowError, "different or missing scopes"):
            self.run_hook()
        self.assertEqual(file_hash(self.root / curation.STATE / "checkpoint.json"), previous)
        self.assertFalse((self.root / "knowledge/distillations").exists())

    def test_private_observations_cannot_be_merged_into_public_candidate(self):
        self.event("one")
        self.event("two", private=True)
        with self.assertRaisesRegex(WorkflowError, "visibility"):
            self.run_hook()

    def test_private_candidate_is_stored_privately(self):
        self.event("one", private=True)
        self.run_hook()
        self.assertFalse((self.root / "knowledge/distillations").exists())
        self.assertTrue((self.root / curation.STATE / "private-candidates/index.json").exists())

    def test_rule_changes_by_engine_rejected_before_candidate_write(self):
        self.event("one")
        def engine(value, *args):
            write_json(self.root / "knowledge/index.json", {"entries": [], "unexpected_rule": True})
            return self.answer(value)
        with self.assertRaisesRegex(WorkflowError, "Protected"):
            curation.execute(self.root, engine=engine)
        self.assertEqual(len(curation.checkpoint(self.root)["seen_record_versions"]), 0)

    def test_agent_contract_changes_reject_candidate_without_checkpoint_progress(self):
        self.event("one")
        policy = self.root / "agent/contracts/quality.md"
        policy.parent.mkdir(parents=True)
        policy.write_text("Require actual review", encoding="utf-8")
        def engine(value, *args):
            policy.write_text("Skip actual review", encoding="utf-8")
            return self.answer(value)
        with self.assertRaisesRegex(WorkflowError, "Protected"):
            curation.execute(self.root, engine=engine)
        self.assertEqual(len(curation.checkpoint(self.root)["seen_record_versions"]), 0)
        self.assertFalse((self.root / "knowledge/distillations").exists())

    def test_engine_failure_does_not_consume_event_and_releases_lock(self):
        self.event("one")
        with self.assertRaisesRegex(WorkflowError, "offline"):
            curation.execute(self.root, engine=lambda *args: (_ for _ in ()).throw(WorkflowError("offline")))
        self.assertEqual(curation.status(self.root)["new_records"], 1)
        self.assertFalse((self.root / curation.STATE / "lock.json").exists())

    def test_source_edit_during_reasoning_rejects_result(self):
        path = self.event("one")
        def engine(value, *args):
            write_json(path, {"scope": self.scope, "hypothesis": "changed meanwhile"})
            return self.answer(value)
        with self.assertRaisesRegex(WorkflowError, "Source changed"):
            curation.execute(self.root, engine=engine)
        self.assertEqual(len(curation.checkpoint(self.root)["seen_record_versions"]), 0)

    def test_unknown_or_duplicate_sources_rejected(self):
        self.event("one")
        value = curation.packet(self.root, curation.checkpoint(self.root), curation.settings(self.root))
        answer = self.answer(value)
        answer["groups"][0]["event_ids"].append(answer["groups"][0]["event_ids"][0])
        with self.assertRaisesRegex(WorkflowError, "exactly once"):
            curation.validate(answer, value)
        answer["groups"][0]["event_ids"] = ["made-up-source"]
        with self.assertRaisesRegex(WorkflowError, "Unknown curation source"):
            curation.validate(answer, value)

    def test_activation_fields_are_not_accepted_from_reasoning_engine(self):
        self.event("one")
        value = curation.packet(self.root, curation.checkpoint(self.root), curation.settings(self.root))
        answer = self.answer(value)
        answer["groups"][0]["status"] = "active"
        with self.assertRaisesRegex(WorkflowError, "fields"):
            curation.validate(answer, value)

    def test_pending_is_retained_without_repeated_inference_and_without_starvation(self):
        self.event("one")
        def pending(value, *args):
            return {"groups": [], "pending": [{"event_id": e["event_id"], "reason": "Need actual evidence"} for e in value["events"]]}
        report = curation.execute(self.root, engine=pending)
        self.assertEqual(report["pending"], 1)
        self.assertEqual(len(curation.checkpoint(self.root)["seen_record_versions"]), 0)
        self.event("two")
        report = self.run_hook()
        self.assertEqual(report["new_records"], 1)
        self.assertEqual(report["pending"], 1)
        with patch.object(curation_engine, "codex_cli", side_effect=AssertionError("Must not invoke inference for unchanged pending")):
            self.assertEqual(curation.execute(self.root)["new_records"], 0)

    def test_revision_merge_keeps_prior_evidence_and_version(self):
        self.event("one")
        first = self.run_hook()
        original = next(iter(curation.catalogs(self.root).values()))
        self.event("two")
        curation.execute(self.root, engine=lambda value, *args: self.answer(value, original["lesson_id"]))
        current = next(iter(curation.catalogs(self.root).values()))
        self.assertEqual(len(current["sources"]), 2)
        self.assertTrue((self.root / first["artifacts"][0]["path"]).exists())
        self.assertEqual(len(curation.catalogs(self.root)), 1)

    def test_checkpoint_write_failure_can_retry_cached_reasoning_idempotently(self):
        self.event("one")
        def fail_commit(path, value):
            if Path(path) == self.root / curation.STATE / "checkpoint.json":
                raise OSError("synthetic commit failure")
            return write_json(path, value)
        with patch.object(curation, "write_json", side_effect=fail_commit), self.assertRaises(OSError):
            self.run_hook()
        with patch.object(curation_engine, "codex_cli", side_effect=AssertionError("Reasoning must be cached")):
            self.assertEqual(curation.execute(self.root)["state"], "curated")
        self.assertEqual(len(list((self.root / "knowledge/distillations").glob("lesson-*/*.json"))), 1)
        self.assertEqual(len(curation.checkpoint(self.root)["seen_record_versions"]), 1)

    def test_time_zone_and_once_per_day_gate(self):
        config, state = curation.settings(self.root), curation.checkpoint(self.root)
        self.assertFalse(curation.due(config, state, datetime(2026, 10, 21, 0, 59, tzinfo=timezone.utc)))
        self.assertTrue(curation.due(config, state, datetime(2026, 10, 21, 1, 0, tzinfo=timezone.utc)))
        state["last_successful_run_at"] = "2026-10-21T01:00:01+00:00"
        self.assertFalse(curation.due(config, state, datetime(2026, 10, 21, 5, 0, tzinfo=timezone.utc)))
        self.assertTrue(curation.due(config, state, datetime(2026, 10, 22, 1, 0, tzinfo=timezone.utc)))

    def test_existing_lock_blocks_concurrent_sweep(self):
        write_json(self.root / curation.STATE / "lock.json", {"owner": "other job"})
        with self.assertRaisesRegex(WorkflowError, "locked"):
            self.run_hook()

    def test_missing_checkpoint_is_not_silently_rebaselined(self):
        (self.root / curation.STATE / "checkpoint.json").unlink()
        with self.assertRaisesRegex(WorkflowError, "checkpoint missing"):
            self.run_hook()

    def test_prepare_and_apply_support_a_different_reasoning_provider(self):
        self.event("one")
        prepared = curation.execute(self.root, prepare_only=True)
        value = read_json(self.root / prepared["packet"])
        response = self.root / "work/alternative-engine.json"
        write_json(response, self.answer(value))
        self.assertEqual(curation.execute(self.root, response_file=response.relative_to(self.root).as_posix())["state"], "curated")

    def test_cli_reasoning_has_no_media_keys_or_shell_tools(self):
        self.event("one")
        job = self.root / curation.STATE / "probe"
        job.mkdir(parents=True)
        value = curation.packet(self.root, curation.checkpoint(self.root), curation.settings(self.root))
        def invoke(argv, **kwargs):
            self.assertIn("--ignore-user-config", argv)
            self.assertIn("features.shell_tool=false", argv)
            self.assertIn("features.image_generation=false", argv)
            self.assertNotIn("KIE_API_KEY", kwargs["env"])
            write_json(Path(argv[argv.index("--output-last-message") + 1]), self.answer(value))
            return SimpleNamespace(returncode=0, stdout='{"type":"turn.completed","usage":{"input_tokens":100,"output_tokens":80}}')
        with patch.object(curation_engine, "executable", return_value="codex"), patch.object(curation_engine.subprocess, "run", side_effect=invoke), patch.dict(os.environ, {"KIE_API_KEY": "synthetic-secret"}):
            response = curation_engine.codex_cli(value, "Return JSON", job, self.root, 30)
        curation.validate(response, value)
        self.assertEqual(read_json(job / "engine-receipt.json")["paid_media_model_credits"], 0)


if __name__ == "__main__":
    unittest.main()
