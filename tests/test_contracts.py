import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from video_localizer import blind, knowledge, media, workflow
from video_localizer.common import WorkflowError, file_hash, inside, read_json, write_json
from video_localizer.contracts import validate_inventory
from video_localizer.kie import ApiError, KieClient, result_urls

TEST_TEMP = Path(__file__).resolve().parents[1] / "work/test-tmp"
TEST_TEMP.mkdir(parents=True, exist_ok=True)


class FakeOpener:
    def __init__(self, value=None, error=None):
        self.value, self.error = value, error

    def open(self, request, timeout=None):
        if self.error:
            raise self.error
        return io.BytesIO(json.dumps(self.value).encode())


class ContractTests(unittest.TestCase):
    def setUp(self):
        from workspace_fixture import isolate_mock_provider
        isolate_mock_provider(self)

    def test_audio_chat_accepts_documented_openai_response_and_rejects_business_error(self):
        response = {"id": "fixture", "choices": [{"message": {"content": '{"has_speech": false}'}}]}
        client = KieClient("test-secret", FakeOpener(response))
        self.assertEqual(client.analyze_audio("https://example.org/audio.wav", "Analyze audio")["id"], "fixture")
        client = KieClient("test-secret", FakeOpener({"code": 402, "msg": "rejected test-secret"}))
        with self.assertRaises(ApiError) as caught:
            client.analyze_audio("https://example.org/audio.wav", "Analyze audio")
        self.assertNotIn("test-secret", str(caught.exception))

    def test_business_failure_is_not_http_success(self):
        client = KieClient("test-secret", FakeOpener({"code": 401, "msg": "bad test-secret"}))
        with self.assertRaises(ApiError) as caught:
            client.credits()
        self.assertNotIn("test-secret", str(caught.exception))

    def test_post_timeout_is_ambiguous_but_read_timeout_is_not(self):
        client = KieClient("fake", FakeOpener(error=URLError("timeout")))
        with self.assertRaises(ApiError) as caught:
            client.create({"model": "wan/2-7-videoedit"})
        self.assertTrue(caught.exception.ambiguous)
        with self.assertRaises(ApiError) as caught:
            client.credits()
        self.assertFalse(caught.exception.ambiguous)

    def test_missing_task_id_is_ambiguous(self):
        client = KieClient("fake", FakeOpener({"code": 200, "data": {}}))
        with self.assertRaises(ApiError) as caught:
            client.create({"model": "wan/2-7-videoedit"})
        self.assertTrue(caught.exception.ambiguous)

    def test_pending_result_is_not_a_video(self):
        self.assertEqual(result_urls({"state": "generating", "resultJson": "{}"}), [])
        self.assertEqual(result_urls({"state": "success", "resultJson": '{"resultUrls":["https://example.org/a.mp4"]}'}), ["https://example.org/a.mp4"])

    def test_run_path_traversal_is_rejected(self):
        with self.assertRaises(WorkflowError):
            inside(Path.cwd(), "../outside.mp4")

    def test_zero_clip_limit_is_rejected_instead_of_looping(self):
        with self.assertRaisesRegex(WorkflowError, "out of range"):
            media.extract("unused.mp4", Path.cwd(), max_clip=0)

    def test_unreviewed_coverage_blocks_planning(self):
        with self.assertRaisesRegex(WorkflowError, "coverage"):
            validate_inventory({"schema_version": 1, "coverage": {}}, Path.cwd(), {"duration": 8})

    def test_candidate_expired_scope_and_superseded_are_filtered(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as temporary:
            root = Path(temporary)
            (root / "knowledge").mkdir()
            (root / "config").mkdir()
            (root / "knowledge/rule.md").write_text("rule", encoding="utf-8")
            common = {"path": "knowledge/rule.md", "status": "active", "scope": {"target_language": "zh-CN"}}
            write_json(root / "knowledge/index.json", {"entries": [
                {**common, "id": "valid"}, {**common, "id": "candidate", "status": "candidate"},
                {**common, "id": "expired", "valid_until": "2020-01-01"},
                {**common, "id": "superseded", "superseded_by": "valid"},
                {**common, "id": "other-language", "scope": {"target_language": "ja-JP"}}]})
            with patch.object(knowledge, "ROOT", root):
                self.assertEqual([entry["id"] for entry in knowledge.retrieve({"target_language": "zh-CN"})], ["valid"])

    def test_blind_package_tampering_is_detected(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as temporary:
            run = Path(temporary)
            write_json(run / "blind/freeze.json", {"files": {"A.mp4": "invalid"}})
            (run / "blind/package").mkdir()
            (run / "blind/package/A.mp4").write_bytes(b"changed")
            with self.assertRaisesRegex(WorkflowError, "changed"):
                blind.verify(run)


class SubmissionTests(unittest.TestCase):
    def setUp(self):
        from workspace_fixture import isolate_mock_provider
        isolate_mock_provider(self)
        self.directory = tempfile.TemporaryDirectory(dir=TEST_TEMP)
        self.root = Path(self.directory.name)
        self.run_dir = self.root / "runs/test"
        (self.run_dir / "jobs").mkdir(parents=True)
        write_json(self.root / "config/workspace.json", {"max_paid_jobs_per_run": 2, "max_estimated_credits_per_run": 250})
        self.packet = {"plan_id": "plan", "segment": "s001", "payload": {"model": "wan/2-7-videoedit", "input": {}}, "assets": {}, "estimated_credits": 60}
        # These submission-unit tests replace prepare_packet; supply the plan
        # selector it normally validates as well, including the no-reuse case.
        plan_patch=patch.object(workflow,"current_plan",return_value={"id":"plan","segments":[{"id":"s001"}]})
        plan_patch.start()
        self.addCleanup(plan_patch.stop)
        self.client = type("FakeClient", (), {"count": 0, "credits": lambda self: 1000})()
        def create(payload):
            self.client.count += 1
            return "task-1"
        self.client.create = create

    def tearDown(self):
        self.directory.cleanup()

    def test_same_packet_does_not_charge_twice(self):
        with patch.object(workflow, "ROOT", self.root), patch.object(workflow, "prepare_packet", return_value=self.packet):
            first = workflow.submit(self.run_dir, "s001", self.client)
            second = workflow.submit(self.run_dir, "s001", self.client)
        self.assertEqual(first["task_id"], second["task_id"])
        self.assertTrue(second["reused"])
        self.assertEqual(self.client.count, 1)

    def test_ambiguous_packet_is_not_automatically_retried(self):
        def fail(payload):
            self.client.count += 1
            raise ApiError("lost reply", ambiguous=True)
        self.client.create = fail
        with patch.object(workflow, "ROOT", self.root), patch.object(workflow, "prepare_packet", return_value=self.packet):
            with self.assertRaises(ApiError):
                workflow.submit(self.run_dir, "s001", self.client)
            again = workflow.submit(self.run_dir, "s001", self.client)
        self.assertEqual(again["state"], "ambiguous")
        self.assertEqual(self.client.count, 1)

    def test_budget_blocks_new_paid_request(self):
        for i in range(2):
            write_json(self.run_dir / f"jobs/{i}.json", {"state": "failed", "estimated_credits": 60})
        with patch.object(workflow, "ROOT", self.root), patch.object(workflow, "prepare_packet", return_value=self.packet):
            with self.assertRaisesRegex(WorkflowError, "budget"):
                workflow.submit(self.run_dir, "s001", self.client)
        self.assertEqual(self.client.count, 0)

    def test_zero_cost_terminal_failure_allows_one_idempotent_explicit_retry(self):
        with patch.object(workflow, "ROOT", self.root), patch.object(workflow, "prepare_packet", side_effect=lambda *args: json.loads(json.dumps(self.packet))):
            first = workflow.submit(self.run_dir, "s001", self.client)
            path = self.run_dir / "jobs" / (first["job"] + ".json")
            failed = read_json(path)
            failed.update({"state": "fail", "credits_consumed": 0})
            write_json(path, failed)
            again = workflow.submit(self.run_dir, "s001", self.client, retry_failed=True)
            repeated = workflow.submit(self.run_dir, "s001", self.client, retry_failed=True)
            self.assertNotEqual(again["job"], first["job"])
            self.assertTrue(repeated["reused"])
            self.assertEqual(self.client.count, 2)

    def test_ambiguous_or_billed_failure_cannot_use_zero_cost_retry(self):
        with patch.object(workflow, "ROOT", self.root), patch.object(workflow, "prepare_packet", return_value=self.packet):
            first = workflow.submit(self.run_dir, "s001", self.client)
            path = self.run_dir / "jobs" / (first["job"] + ".json")
            failed = read_json(path)
            for state, cost in (("ambiguous", None), ("fail", 20)):
                write_json(path, {**failed, "state": state, "credits_consumed": cost})
                with self.assertRaisesRegex(WorkflowError, "zero billed"):
                    workflow.submit(self.run_dir, "s001", self.client, retry_failed=True)
            self.assertEqual(self.client.count, 1)

    def test_pending_zero_does_not_release_credit_reservation(self):
        self.assertEqual(workflow.reserved_credits({"state": "waiting", "credits_consumed": 0, "estimated_credits": 220}, 250), 220)
        self.assertEqual(workflow.reserved_credits({"state": "fail", "credits_consumed": 0, "estimated_credits": 220}, 250), 0)

    def test_singular_video_and_reference_image_assets_are_uploaded_and_bound(self):
        video, image = self.run_dir / "source.mp4", self.run_dir / "reference.png"
        video.write_bytes(b"video-fixture")
        image.write_bytes(b"image-fixture")
        self.packet["assets"] = {"video": {"path": video.name, "sha256": file_hash(video)},
                                 "image": {"path": image.name, "sha256": file_hash(image)}}
        self.packet["payload"]["input"] = {"video_url": "ASSET:video", "reference_image": "ASSET:image", "duration": 0}
        self.client.upload = lambda path: "https://example.com/"+path.name
        seen = []
        self.client.create = lambda payload: seen.append(payload) or "task-1"
        with patch.object(workflow, "ROOT", self.root), patch.object(workflow, "prepare_packet", return_value=self.packet):
            workflow.submit(self.run_dir, "s001", self.client)
        self.assertEqual(seen[0]["input"]["video_url"], "https://example.com/source.mp4")
        self.assertEqual(seen[0]["input"]["reference_image"], "https://example.com/reference.png")
        self.assertEqual(seen[0]["input"]["duration"], 0)

    def test_estimated_cost_budget_blocks_overspend(self):
        write_json(self.run_dir / "jobs/prior.json", {"state": "success", "estimated_credits": 220})
        with patch.object(workflow, "ROOT", self.root), patch.object(workflow, "prepare_packet", return_value=self.packet):
            with self.assertRaisesRegex(WorkflowError, "credit budget"):
                workflow.submit(self.run_dir, "s001", self.client)
        self.assertEqual(self.client.count, 0)


if __name__ == "__main__":
    unittest.main()

