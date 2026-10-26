import copy
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from video_localizer import cli, common, demo, knowledge, media, workflow
from video_localizer.common import WorkflowError, file_hash, read_json, write_json
import mcp_server
from workspace_fixture import copy_project_knowledge

PROJECT = Path(__file__).resolve().parents[1]
TEST_TEMP = PROJECT / "work/test-tmp"
TEST_TEMP.mkdir(parents=True, exist_ok=True)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required for media integration")
class AcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(dir=TEST_TEMP)
        cls.root = Path(cls.temporary.name)
        for relative in ("config/workspace.json", "config/quality.json", "config/profiles/company-default/profile.json"):
            destination = cls.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(PROJECT / relative, destination)
        copy_project_knowledge(PROJECT, cls.root)
        cls.patches = [patch.object(module, "ROOT", cls.root) for module in (common, cli, demo, knowledge, workflow)]
        for item in cls.patches:
            item.start()
            cls.addClassCleanup(item.stop)
        demo.create_demo("test-ad", "local_overlay")
        cls.run_dir = common.get_run("test-ad")
        cli.capture(cls.run_dir)
        review = read_json(cls.run_dir / "review/template.json")
        candidate = read_json(cls.run_dir / "outputs/candidate.json")
        captured = read_json(cls.run_dir / "review/capture.json")
        frame = next(path for path in captured["files"] if path.endswith("frame-00001.jpg"))
        audio = next(path for path in captured["files"] if path.endswith("audio.wav"))
        review.update({"reviewer": "automated contract fixture", "method": "Test stub, not an actual quality judgment",
                       "video_sha256": candidate["sha256"], "decision": "pass"})
        review["scores"] = {key: 5 for key in review["scores"]}
        review["instances"] = [{**item, "decision": "pass", "evidence": [frame]} for item in review["instances"]]
        review["coverage"] = {key: {"status": "reviewed", "evidence": [audio if key == "audio" else frame]}
                              for key in ("visual", "audio", "timing")}
        cls.base_review = review
        cls.base_candidate = candidate
        from workspace_fixture import observe_visual_fixture
        observe_visual_fixture(cls.run_dir)
        cli.capture(cls.run_dir)

    @classmethod
    def tearDownClass(cls):
        for item in reversed(cls.patches):
            item.stop()
        cls.temporary.cleanup()

    def setUp(self):
        self.review = copy.deepcopy(self.base_review)
        write_json(self.run_dir / "outputs/candidate.json", self.base_candidate)
        write_json(self.run_dir / "review/review.json", self.review)

    def test_contract_complete_review_allows_delivery(self):
        self.assertEqual(workflow.quality(self.run_dir)["decision"], "pass")
        workflow.deliver(self.run_dir)
        self.assertEqual(file_hash(self.run_dir / "outputs/final.mp4"), self.base_candidate["sha256"])

    def test_new_visual_gate_blocks_delivery_without_rewriting_existing_final(self):
        from video_localizer import visual_audit
        binding, *_ = visual_audit.context(self.run_dir, 'final')
        path = visual_audit.directory(self.run_dir,binding)/visual_audit.MANIFEST
        backup = path.with_suffix('.held')
        existing = self.run_dir/'outputs/final.mp4'
        before = file_hash(existing) if existing.exists() else None
        path.rename(backup)
        try:
            self.assertIn('text_visual_audit_unverified', workflow.quality(self.run_dir)['failures'])
            with self.assertRaisesRegex(WorkflowError,'not accepted'):
                workflow.deliver(self.run_dir)
            self.assertEqual(file_hash(existing) if existing.exists() else None,before)
        finally:
            backup.rename(path)

    def test_missing_review_blocks_delivery(self):
        (self.run_dir / "review/review.json").unlink()
        with self.assertRaises(WorkflowError):
            workflow.deliver(self.run_dir)

    def test_review_of_another_video_is_rejected(self):
        self.review["video_sha256"] = "wrong-video"
        write_json(self.run_dir / "review/review.json", self.review)
        self.assertIn("review_binding_mismatch", workflow.quality(self.run_dir)["failures"])

    def test_omitted_instance_is_not_hidden_by_high_score(self):
        self.review["instances"].pop()
        write_json(self.run_dir / "review/review.json", self.review)
        self.assertIn("instance_coverage_mismatch", workflow.quality(self.run_dir)["failures"])

    def test_critical_defect_overrides_high_score(self):
        self.review["critical_defects"] = ["untranslated_required_instance"]
        write_json(self.run_dir / "review/review.json", self.review)
        self.assertEqual(workflow.quality(self.run_dir)["decision"], "revise")

    def test_failed_review_survives_later_passing_review(self):
        self.review["critical_defects"] = ["untranslated_required_instance"]
        write_json(self.run_dir / "review/review.json", self.review)
        failed = workflow.quality(self.run_dir)
        write_json(self.run_dir / "review/review.json", self.base_review)
        passed = workflow.quality(self.run_dir)
        self.assertEqual(passed["decision"], "pass")
        self.assertEqual(read_json(self.run_dir / failed["record_path"])["decision"], "revise")

    def test_foreign_speech_cannot_be_left_untranslated(self):
        from video_localizer.contracts import validate_inventory
        inventory = read_json(self.run_dir / "analysis/inventory.json")
        inventory["audio"]["has_speech"] = True
        inventory["speech_segments"] = [{"id": "a001", "start": 0, "end": 2, "source_text": "Hello", "target_text": "你好"}]
        with self.assertRaisesRegex(WorkflowError, "replacement track"):
            validate_inventory(inventory, self.run_dir, read_json(self.run_dir / "analysis/media.json"))

    def test_source_frame_cannot_substitute_for_output_evidence(self):
        self.review["instances"][0]["evidence"] = ["analysis/shot-001.jpg"]
        write_json(self.run_dir / "review/review.json", self.review)
        self.assertTrue(any("unverified" in failure for failure in workflow.quality(self.run_dir)["failures"]))

    def test_candidate_hash_tampering_blocks_delivery(self):
        changed = {**self.base_candidate, "sha256": "changed"}
        write_json(self.run_dir / "outputs/candidate.json", changed)
        with self.assertRaises(WorkflowError):
            workflow.deliver(self.run_dir)

    def test_missing_postprocessing_record_blocks_delivery(self):
        candidate = {**self.base_candidate, "postprocessing": [{"record": "outputs/missing-repair.json", "sha256": "missing"}]}
        write_json(self.run_dir / "outputs/candidate.json", candidate)
        self.assertIn("postprocessing_record_missing_or_changed", workflow.quality(self.run_dir)["failures"])

    def test_changed_inventory_invalidates_plan(self):
        path = self.run_dir / "analysis/inventory.json"
        original = path.read_bytes()
        try:
            data = read_json(path)
            data["text_instances"][0]["target_text"] = "different copy"
            write_json(path, data)
            with self.assertRaisesRegex(WorkflowError, "Inventory changed"):
                workflow.current_plan(self.run_dir)
        finally:
            path.write_bytes(original)

    def test_limited_range_video_extracts_full_range_jpeg(self):
        source = self.root / "work/limited-range.mp4"
        media.ffmpeg(["-f", "lavfi", "-i", "color=c=green:s=160x96:d=1:r=24", "-color_range", "tv",
                      "-c:v", "libx264", "-pix_fmt", "yuv420p", source])
        directory = self.root / "work/limited-analysis"
        media.extract(source, directory)
        result = media.command(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=color_range",
                                "-of", "csv=p=0", directory / "shot-001.jpg"])
        self.assertEqual(result.stdout.strip(), "pc")

    def test_text_erasure_prompt_keeps_target_copy_out_of_model_stage(self):
        path = self.run_dir / "analysis/inventory.json"
        original = path.read_bytes()
        try:
            inventory = read_json(path)
            inventory["shots"][0]["model_text_mode"] = "erase_then_overlay"
            for item in inventory["text_instances"]:
                item["action"] = "model_edit"
            write_json(path, inventory)
            result = workflow.build_plan(self.run_dir)
            plan = read_json(self.run_dir / "plan.json")
            prompt = plan["segments"][0]["prompt"]
            self.assertIn("TEXT REMOVAL pass", prompt)
            self.assertIn("ERASE, leave no lettering", prompt)
            self.assertNotIn(inventory["text_instances"][0]["target_text"], prompt)
            self.assertEqual(result["routes"], ["wan_edit"])
        finally:
            path.write_bytes(original)
            # Restore exact original plan, without introducing another revision.
            original_plan = read_json(self.run_dir / "plans" / self.base_candidate["plan_id"] / "plan.json")
            write_json(self.run_dir / "plan.json", original_plan)

    def test_typesetting_preserves_duration_and_splits_no_english_cleanup(self):
        segment = {"start": 0, "end": 1}
        instance = {"start": 0.03, "end": 1, "bbox": [10, 10, 600, 220],
                    "target_text": "你好\n世界", "display": {"font_size": 48, "reveal_seconds": 0.5}}
        source = self.run_dir / "inputs/source.mp4"
        directory = self.root / "work/foreground-test"
        output = media.render_foreground(source, segment, [instance], media.probe(source), directory)
        self.assertAlmostEqual(media.probe(output)["duration"], 1, places=2)
        script = (directory / "foreground.ass").read_text(encoding="utf-8-sig")
        self.assertIn("你好", script)
        self.assertIn("世界", script)
        self.assertNotIn("drawbox", script)

    def test_reference_composition_limits_repair_to_reviewed_region(self):
        directory = self.root / "work/reference-test"
        directory.mkdir(parents=True, exist_ok=True)
        source, plate = directory / "source.mp4", directory / "plate.png"
        media.ffmpeg(["-f", "lavfi", "-i", "color=green:s=160x240:d=1:r=30", "-c:v", "libx264",
                      "-pix_fmt", "yuv420p", source])
        media.ffmpeg(["-f", "lavfi", "-i", "color=red:s=160x240:d=1", "-frames:v", "1", plate])
        segment = {"start": 0, "end": 1, "reference_composite": {
            "day": {"path": str(plate.relative_to(self.root))},
            "night": {"path": str(plate.relative_to(self.root))},
            "blend_knots": [[0, 0], [1, 1]], "erase_regions": [[40, 70, 80, 100]]}}
        output = media.render_reference(source, segment, [], media.probe(source), directory / "render", self.root)
        def pixel(x, y):
            result = __import__('subprocess').run(["ffmpeg", "-v", "error", "-ss", "0.5", "-i", str(output),
                "-vf", f"crop=2:2:{x}:{y}", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], capture_output=True, check=True)
            return result.stdout[:3]
        inside, outside = pixel(80, 120), pixel(10, 10)
        self.assertGreater(inside[0], inside[1]+100)
        self.assertGreater(outside[1], outside[0]+80)
        self.assertAlmostEqual(media.probe(output)["duration"], 1, places=2)

    def test_wan_packet_uses_video_reference_and_silent_five_second_contract(self):
        plan = {"id": "wan-packet-test", "segments": [{"id": "s001", "route": "video_reference",
                "start": 0, "end": 5, "prompt": "把参考视频中的广告文案改为中文。"}]}
        with patch.object(workflow, "current_plan", return_value=plan):
            packet = workflow.prepare_packet(self.run_dir, "s001")
        payload = packet["payload"]
        self.assertEqual(payload["model"], "wan/2-6-flash-video-to-video")
        self.assertEqual(payload["input"]["duration"], "5")
        self.assertFalse(payload["input"]["audio"])
        self.assertFalse(payload["input"]["multi_shots"])
        self.assertEqual(payload["input"]["video_urls"], ["ASSET:video"])
        self.assertEqual(packet["estimated_credits"], 20)
        self.assertAlmostEqual(media.probe(self.run_dir / packet["assets"]["video"]["path"])["duration"], 5, places=2)

    def test_wan_edit_packet_uses_source_video_and_reference_layout(self):
        image = self.run_dir / "analysis/shot-001.jpg"
        plan = {"id": "wan-edit-test", "segments": [{"id": "s001", "route": "wan_edit", "start": 0, "end": 5,
                "prompt": "只把文案换成参考图中的中文，保留原视频。", "reference_image": {
                    "path": "analysis/shot-001.jpg", "sha256": file_hash(image)}}]}
        with patch.object(workflow, "current_plan", return_value=plan):
            packet = workflow.prepare_packet(self.run_dir, "s001")
        self.assertEqual(packet["payload"]["model"], "wan/2-7-videoedit")
        options = packet["payload"]["input"]
        self.assertEqual((options["video_url"], options["reference_image"]), ("ASSET:video", "ASSET:image"))
        self.assertEqual(options["duration"], 0)
        self.assertEqual(options["audio_setting"], "origin")
        self.assertFalse(options["prompt_extend"])
        self.assertEqual(packet["estimated_credits"], 80)

    def test_veo_lite_reference_packet_contains_images_without_source_video(self):
        image = self.run_dir / "analysis/shot-001.jpg"
        plan = {"id": "veo-lite-test", "segments": [{"id": "s001", "route": "regenerate", "start": 0, "end": 8,
                "prompt": "生成中文视频，保留参考图中的准确中文。", "veo_tier": "veo3_lite", "veo_generation_type": "REFERENCE_2_VIDEO",
                "instance_ids": ["t001"], "reference_frames": [{"path": "analysis/shot-001.jpg", "sha256": file_hash(image)}]}]}
        with patch.object(workflow, "current_plan", return_value=plan):
            packet = workflow.prepare_packet(self.run_dir, "s001")
        options = packet["payload"]["input"]
        self.assertEqual(options["model"], "veo3_lite")
        self.assertEqual(options["generation_type"], "REFERENCE_2_VIDEO")
        self.assertEqual(options["image_urls"], ["ASSET:image1"])
        self.assertNotIn("video_urls", options)
        self.assertEqual((options["duration"], packet["estimated_credits"]), (8, 30))


class McpTests(unittest.TestCase):
    def test_initialize_and_tool_discovery(self):
        response = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        self.assertEqual(response["result"]["serverInfo"]["name"], "ad-localizer")
        response = mcp_server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {tool['name'] for tool in response['result']['tools']}
        self.assertTrue({'localizer_quality','localizer_visual_evidence','localizer_visual_review',
                         'localizer_visual_release_neutral', 'localizer_visual_notes', 'localizer_visual_pages'} <= names)

    def test_visual_mcp_uses_the_same_single_instance_review(self):
        from video_localizer import visual_audit
        with patch.object(mcp_server,'get_run',return_value=Path('fixture')), \
                patch.object(visual_audit,'review',return_value={'state':'pending_or_failed'}) as review:
            response = mcp_server.handle({'id':4,'method':'tools/call','params':{'name':'localizer_visual_review',
                'arguments':{'run':'fixture','manifest':'audit.json','observation':'one.json'}}})
            self.assertFalse(response['result']['isError'])
            review.assert_called_once_with(Path('fixture'),'audit.json','one.json')

    def test_mcp_does_not_accept_arbitrary_execution(self):
        response = mcp_server.handle({"id": 3, "method": "tools/call", "params": {"name": "execute", "arguments": {"cmd": "whoami"}}})
        self.assertTrue(response["result"]["isError"])

    def test_notifications_do_not_emit_responses(self):
        self.assertIsNone(mcp_server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))

