import shutil
import json
import runpy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from video_localizer import candidate_index, curation, knowledge, knowledge_advisories as advisories
from video_localizer import knowledge_review as reviews, knowledge_usage as usage, learning
from video_localizer.common import WorkflowError, file_hash, read_json, write_json
from video_localizer.knowledge_records import resolve


class KnowledgeLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = "knowledge/candidates/observation.json"
        self.context = {"workflow": "video-localization", "source_sha256": "source-sha", "target_language": "de", "features": ["animated_text"]}
        self.value = {"id": "observation", "status": "candidate", "scope": {k: self.context[k] for k in ("workflow", "source_sha256", "target_language")},
                      "hypothesis": "Inspect transitions; sampled stills missed residual text", "outcome": "revise", "limitations": ["Single source; same agent"]}
        write_json(self.root / self.path, self.value)
        self.original = (self.root / self.path).read_bytes()
        method = self.root / "knowledge/rules/transitions.md"
        method.parent.mkdir(parents=True)
        method.write_bytes(b"Inspect continuous transitions.\r\n")
        self.entry = {"id": "transitions", "path": "knowledge/rules/transitions.md", "status": "active",
                      "scope": {"workflow": "video-localization"}, "tags": [], "method_sha256": file_hash(method)}
        write_json(self.root / "knowledge/index.json", {"entries": [self.entry]})
        self.review = {"source": {"path": self.path, "sha256": file_hash(self.root / self.path)}, "resolution": "adopted",
                       "review_type": "developer_review", "reviewed_by": "synthetic test developer", "origin": "fixture review",
                       "reason": "The method covers the check; coordinates remain historical observations",
                       "targets": [{"id": "transitions", "sha256": file_hash(method)}], "adopted_parts": ["continuous review"],
                       "retained_parts": ["single-source parameters"], "all_material_accounted": True, "remaining_disposition": "historical_only"}

    def test_scoped_advisory_is_separate_and_never_activates(self):
        matches = advisories.retrieve(self.context, self.root)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["validation_status"], "unverified_observation")
        self.assertEqual(advisories.retrieve({**self.context, "target_language": "ja"}, self.root), [])
        self.assertEqual(advisories.retrieve({**self.context, "source_sha256": "other"}, self.root), [])
        self.assertEqual([x["id"] for x in knowledge.retrieve(self.context, root=self.root)], ["transitions"])
        self.assertEqual(advisories.retrieve(self.context, self.root, limit=0), [])

    def test_generic_candidate_needs_explicit_features(self):
        self.value["scope"] = {"workflow": "video-localization"}
        write_json(self.root / self.path, self.value)
        self.assertEqual(advisories.retrieve(self.context, self.root), [])
        spec = {**self.review, "source": {"path": self.path, "sha256": file_hash(self.root / self.path)},
                "resolution": "pending", "targets": [], "adopted_parts": [], "all_material_accounted": False,
                "next_action": "Test another source", "retrieval_features": ["animated_text"]}
        reviews.review(spec, self.root)
        self.assertEqual(len(advisories.retrieve(self.context, self.root)), 1)
        self.assertEqual(advisories.retrieve({**self.context, "features": []}, self.root), [])

    def test_distillation_and_original_do_not_repeat_the_same_evidence(self):
        path = "knowledge/distillations/lesson/revision.json"
        write_json(self.root / path, {"scope": self.value["scope"],
                   "sources": [{"path": self.path, "sha256": file_hash(self.root / self.path)}],
                   "method": {"action": "A shorter summary of the same observation", "limitations": []}})
        write_json(self.root / "knowledge/distillations/index.json", {"entries": [{"path": path, "sha256": file_hash(self.root / path)}]})
        selected = advisories.retrieve(self.context, self.root)
        self.assertEqual([x["path"] for x in selected], [path])

    def test_private_public_copies_are_one_observation(self):
        private = "knowledge/local/candidates/observation.json"
        write_json(self.root / private, {**self.value, "case": "private-evidence"})
        self.assertEqual(len(advisories.retrieve(self.context, self.root)), 1)
        write_json(self.root / "knowledge/local/inbox/observation.json", {"id": "observation", "case": "private-evidence"})
        reviews.review({**self.review, "source": {"path": private, "sha256": file_hash(self.root / private)}}, self.root)
        self.assertNotIn(self.root / "knowledge/local/inbox/observation.json", curation.source_files(self.root))

    def test_partial_adoption_cannot_archive(self):
        reviews.review({**self.review, "resolution": "partial", "next_action": "Check the remaining repair hypothesis"}, self.root)
        with self.assertRaisesRegex(WorkflowError, "unresolved"):
            reviews.archive_preview(self.path, self.root)
        self.assertEqual(len(reviews.queue(self.root)), 1)

    def test_promoted_candidate_source_hash_is_audited(self):
        entry = {**self.entry, "candidate_sources": [self.review["source"]]}
        learning.verify_entry(entry, self.root)
        (self.root / self.path).write_text("changed source")
        with self.assertRaisesRegex(WorkflowError, "revision changed"):
            learning.verify_entry(entry, self.root)

    def test_mcp_exposes_separate_advisory_queue_and_actual_use(self):
        server = runpy.run_path(str(Path(__file__).resolve().parents[1] / "bin/mcp_server.py"))
        handle = server["handle"]
        handle.__globals__["ROOT"] = self.root
        names = {t["name"] for t in server["TOOLS"]}
        self.assertTrue({"localizer_knowledge_advisories", "localizer_knowledge_queue", "localizer_knowledge_use"} <= names)
        result = handle({"id": 1, "method": "tools/call", "params": {"name": "localizer_knowledge_queue"}})
        self.assertFalse(result["result"]["isError"])
        self.assertEqual(json.loads(result["result"]["content"][0]["text"])["items"][0]["path"], self.path)

    def test_closed_candidate_leaves_queue_but_retains_original_and_history(self):
        decision = reviews.review(self.review, self.root)
        preview = reviews.archive_preview(self.path, self.root)
        result = reviews.archive(self.path, preview["fingerprint"], self.root)
        self.assertFalse((self.root / self.path).exists())
        self.assertEqual((self.root / result["archived"]).read_bytes(), self.original)
        self.assertEqual(resolve(self.root, self.path).read_bytes(), self.original)
        self.assertEqual(reviews.queue(self.root), [])
        self.assertEqual(advisories.retrieve(self.context, self.root), [])
        candidate_index.verify(self.root)
        self.assertEqual(curation.source_files(self.root), [])
        learning.record_project_candidate(self.value, self.root)
        self.assertFalse((self.root / self.path).exists())
        self.assertEqual(reviews.decisions(self.root)[(self.path, self.review["source"]["sha256"])]["decision_sha256"], decision["sha256"])

    def test_stale_review_and_changed_target_block_archive(self):
        reviews.review(self.review, self.root)
        with self.assertRaisesRegex(WorkflowError, "Review changed"):
            reviews.review(self.review, self.root)
        (self.root / self.entry["path"]).write_text("changed")
        with self.assertRaises(WorkflowError):
            reviews.archive_preview(self.path, self.root)

    def test_archive_tampering_is_detected_and_portable(self):
        reviews.review(self.review, self.root)
        result = reviews.archive(self.path, reviews.archive_preview(self.path, self.root)["fingerprint"], self.root)
        portable = self.root / "portable"
        shutil.copytree(self.root / "knowledge", portable / "knowledge")
        self.assertEqual(len(reviews.decisions(portable)), 1)
        (portable / result["archived"]).write_text("changed")
        with self.assertRaises(WorkflowError):
            reviews.decisions(portable)

    def make_run(self):
        run = self.root / "runs/task"
        for name, data in (("inputs/source.mp4", b"source"), ("outputs/final.mp4", b"video"), ("review/observation.md", b"Actual synthetic test observation")):
            path = run / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        write_json(run / "run.json", {"source": "inputs/source.mp4"})
        write_json(run / "inputs/request.json", {"target_language": "de"})
        write_json(run / "analysis/inventory.json", {"source_sha256": file_hash(run / "inputs/source.mp4")})
        entry = {**self.entry, "sha256": file_hash(self.root / self.entry["path"])}
        plan = {"id": "p1", "source_sha256": file_hash(run / "inputs/source.mp4"), "knowledge": [entry],
                "request_sha256": file_hash(run / "inputs/request.json"), "inventory_sha256": file_hash(run / "analysis/inventory.json")}
        write_json(run / "plan.json", plan)
        write_json(run / "plans/p1/plan.json", plan)
        write_json(run / "outputs/candidate.json", {"path": "outputs/final.mp4", "sha256": file_hash(run / "outputs/final.mp4"),
                   "plan_id": plan["id"], "inventory_sha256": plan["inventory_sha256"]})
        spec = {"plan_id": "p1", "video_sha256": file_hash(run / "outputs/final.mp4"), "reviewed_by": "fixture", "review_type": "same_agent",
                "uses": [{"path": entry["path"], "sha256": entry["sha256"], "outcome": "counterexample", "observation": "Bound observation shows a missed boundary"}],
                "evidence": [{"path": "review/observation.md", "sha256": file_hash(run / "review/observation.md")}]}
        return run, spec, plan

    def test_actual_feedback_survives_run_and_reaches_revision_queue(self):
        run, spec, plan = self.make_run()
        self.assertEqual(usage.followup(run, self.root)["state"], "needs_use_feedback")
        result = usage.record.__wrapped__(run, spec, self.root)
        self.assertEqual(result, usage.record.__wrapped__(run, spec, self.root))
        self.assertEqual(usage.followup(run, self.root)["state"], "recorded")
        context = {**self.context, "source_sha256": plan["source_sha256"]}
        selected = knowledge.retrieve(context, root=self.root)
        self.assertEqual(len(selected[0]["review_alerts"]), 1)
        shutil.rmtree(run)
        self.assertEqual(len(knowledge.retrieve(context, root=self.root)[0]["review_alerts"]), 1)
        item = next(r for r in reviews.queue(self.root) if r["path"] == result["path"])
        self.assertIn("counterexample", item["next_action"])
        self.assertIn(self.root / result["path"], curation.source_files(self.root))

    def test_stale_video_unselected_method_and_missing_evidence_reject(self):
        run, spec, _ = self.make_run()
        with self.assertRaises(WorkflowError):
            usage.record.__wrapped__(run, {**spec, "video_sha256": "wrong"}, self.root)
        with self.assertRaises(WorkflowError):
            usage.record.__wrapped__(run, {**spec, "uses": [{**spec["uses"][0], "sha256": "wrong"}]}, self.root)
        with self.assertRaises(WorkflowError):
            usage.record.__wrapped__(run, {**spec, "evidence": []}, self.root)
        (run / "review/observation.md").write_text("changed")
        with self.assertRaises(WorkflowError):
            usage.record.__wrapped__(run, spec, self.root)

    def test_repeated_use_observations_are_compact_and_legacy_retries_stay_immutable(self):
        run, spec, plan = self.make_run()
        second = {**plan['knowledge'][0], 'path':'knowledge/rules/other-fixture.md'}
        plan['knowledge'].append(second)
        write_json(run/'plan.json',plan);write_json(run/'plans/p1/plan.json',plan)
        spec['uses'].append({**spec['uses'][0], 'path':second['path']})
        result = usage.record.__wrapped__(run,spec,self.root)
        path = self.root/result['path'];receipt=read_json(path)
        self.assertEqual(len(receipt['uses']),2)
        self.assertEqual(receipt['hypothesis'],spec['uses'][0]['observation'])
        self.assertEqual(result,usage.record.__wrapped__(run,spec,self.root))
        receipt['hypothesis']=' | '.join(u['observation'] for u in spec['uses'])
        write_json(path,receipt);historical=path.read_bytes()
        usage.record.__wrapped__(run,spec,self.root)
        self.assertEqual(path.read_bytes(),historical)
        receipt['hypothesis']='Altered observation';write_json(path,receipt)
        with self.assertRaisesRegex(WorkflowError,'Immutable knowledge feedback changed'):
            usage.record.__wrapped__(run,spec,self.root)

    def test_new_plan_cannot_claim_use_against_an_old_render(self):
        run, spec, plan = self.make_run()
        changed = {**plan, "id": "p2"}
        write_json(run / "plan.json", changed)
        write_json(run / "plans/p2/plan.json", changed)
        with self.assertRaisesRegex(WorkflowError, "another plan"):
            usage.record.__wrapped__(run, {**spec, "plan_id": "p2"}, self.root)

    def test_reviewed_feedback_closes_alert_without_erasing_observation(self):
        run, spec, plan = self.make_run()
        result = usage.record.__wrapped__(run, spec, self.root)
        original = (self.root / result["path"]).read_bytes()
        context = {**self.context, "source_sha256": plan["source_sha256"]}
        self.assertTrue(usage.alerts(context, self.root))
        review = {**self.review, "source": {k: result[k] for k in ("path", "sha256")},
                  "resolution": "rejected", "targets": [], "adopted_parts": [],
                  "reason": "Synthetic review fixture: observation does not establish a defect in the method; historical observation retained"}
        reviews.review(review, self.root)
        self.assertEqual(usage.alerts(context, self.root), {})
        self.assertEqual((self.root / result["path"]).read_bytes(), original)
        self.assertEqual(len(knowledge.retrieve(context, root=self.root)), 1)

    def test_explicit_nonuse_is_not_success_and_new_video_needs_new_feedback(self):
        run, spec, _ = self.make_run()
        spec["uses"][0]["outcome"] = "not_used"
        spec["evidence"] = []
        result = usage.record.__wrapped__(run, spec, self.root)
        self.assertEqual(read_json(self.root / result["path"])["uses"][0]["outcome"], "not_used")
        self.assertEqual(result["state"], "recorded_non_use")
        self.assertNotIn(result["path"], [r["path"] for r in reviews.queue(self.root)])
        self.assertNotIn(self.root / result["path"], curation.source_files(self.root))
        self.assertEqual(usage.followup(run, self.root)["state"], "recorded")
        write_json(run / "outputs/candidate.json", {"path": "outputs/final.mp4", "sha256": "other"})
        self.assertEqual(usage.followup(run, self.root)["state"], "needs_use_feedback")


if __name__ == "__main__":
    unittest.main()
