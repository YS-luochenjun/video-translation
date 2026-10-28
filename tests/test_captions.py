"""Regression tests for separate translations and reused English timing.

Media integration uses a labeled sine-wave fixture, not real speech acceptance.
"""
import copy
import shutil
import subprocess
import sys
import tempfile
import unittest
from workspace_fixture import copy_project_knowledge
from pathlib import Path
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from video_localizer import captions, cli, common, demo, knowledge, media, model_tasks, workflow
from video_localizer.common import WorkflowError, file_hash, object_hash, read_json, write_json

TEMP = PROJECT / "work/test-tmp"
TEMP.mkdir(parents=True, exist_ok=True)
POLICY = read_json(PROJECT / "config/quality.json")["caption_sync"]


def example_inventory():
    return {"source_sha256": "source-hash", "audio": {"has_speech": True, "strategy": "replace", "replacement_path": "mix.wav"},
            "text_instances": [
                {"id": "t001", "speech_id": "a001", "text_role": "speech_caption", "action": "model_edit",
                 "target_text": "手势翻转棱镜特效怎么做？其实很简单，跟我一起学！", "start": 0, "end": 5.6,
                 "bbox": [0, 0, 600, 100]},
                {"id": "t002", "text_role": "scene_text", "target_text": "开始", "action": "model_edit", "start": 1, "end": 5.6}],
            "speech_segments": [{"id": "a001", "target_text": "手势翻转棱镜特效怎么做？其实很简单，跟我一起学！",
                                 "caption_policy": "verbatim", "caption_ids": ["t001"]}]}


class CaptionContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=TEMP)
        self.run = Path(self.temporary.name)
        self.inventory = example_inventory()
        (self.run / "mix.wav").write_bytes(b"known synthetic alignment asset, not actual voice")
        write_json(self.run / "inputs/request.json", {"target_language": "zh-CN"})
        write_json(self.run / "analysis/media.json", {"duration": 6})
        self.alignment = {"schema_version": 1, "source_sha256": "source-hash", "target_language": "zh-CN",
                          "audio": {"path": "mix.wav", "sha256": file_hash(self.run / "mix.wav")},
                          "timeline": "final_mix_seconds", "status": "reviewed", "reviewer": "synthetic fixture",
                          "method": "manual_listening", "segments": [{"speech_id": "a001", "units": [
                              {"text": "手势翻转棱镜特效怎么做？", "start": .05, "end": 2.2},
                              {"text": "其实很简单，跟我一起学！", "start": 2.3, "end": 4.1}]}]}

    def tearDown(self):
        self.temporary.cleanup()

    def test_actual_separate_translation_failure_is_rejected(self):
        self.inventory["text_instances"][0]["target_text"] = "如何制作手势翻转棱镜特效？其实很简单，跟我学！"
        with self.assertRaisesRegex(WorkflowError, "differs from final speech"):
            captions.contract(self.inventory)

    def test_missing_caption_classification_cannot_silently_bypass_gate(self):
        self.inventory["text_instances"][0].pop("text_role")
        with self.assertRaisesRegex(WorkflowError, "Classify text_role"):
            captions.contract(self.inventory)

    def test_independent_button_does_not_need_to_repeat_narration(self):
        self.assertEqual(captions.contract(self.inventory)["caption_ids"], ["t001"])

    def test_publisher_mark_does_not_become_a_spoken_caption(self):
        self.inventory["text_instances"].append({
            "id": "t003", "text_role": "publisher_mark", "action": "reference_plate",
            "publisher_identity": "mindjournal", "mark_form": "watermark",
            "source_text": "MindJournal", "target_text": ""})
        self.assertEqual(captions.contract(self.inventory)["caption_ids"], ["t001"])
        self.inventory["text_instances"][0]["target_text"] = "Unrelated copy"
        with self.assertRaisesRegex(WorkflowError, "differs from final speech"):
            captions.contract(self.inventory)

    def test_uncaptioned_speech_requires_explicit_reason(self):
        self.inventory["text_instances"][0]["text_role"] = "scene_text"
        self.inventory["speech_segments"][0].update(caption_policy="none", caption_ids=[])
        with self.assertRaisesRegex(WorkflowError, "requires a reason"):
            captions.contract(self.inventory)
        self.inventory["speech_segments"][0]["caption_reason"] = "Reviewed source contains no spoken captions"
        self.assertEqual(captions.contract(self.inventory)["caption_ids"], [])

    def test_unknown_speech_cannot_be_marked_caption_not_applicable(self):
        self.inventory['audio']['has_speech'] = None
        self.assertIn('caption_speech_presence_unverified', captions.evaluate(self.run, {}, self.inventory, {}, POLICY)['failures'])

    def test_fragment_clipping_uses_segment_time_and_preserves_input(self):
        item = self.inventory['text_instances'][0]
        item.update(start=3, end=6, source_interval=[3, 6], display={'timed_fragments': [[3.2, 4, '甲'], [4, 5, '乙']]})
        before = copy.deepcopy(item)
        shifted = captions.shift_instances([item], 4, 2)[0]
        selected = captions.render_instances([shifted])
        self.assertEqual(selected[-1]['start'], 0)
        self.assertEqual(selected[-1]['end'], 1)
        self.assertEqual(shifted['source_interval'], [0, 2])
        self.assertEqual(item, before)

    def test_numeric_and_word_changes_are_not_punctuation_normalization(self):
        self.assertEqual(captions.normalized("跟我学！"), captions.normalized("跟我学。"))
        for left, right in (("95%", "95"), ("1.5", "15"), ("95%", "99%"), ("一起学", "学"), ("can't", "cant")):
            self.assertNotEqual(captions.normalized(left), captions.normalized(right))

    def test_mixer_cannot_read_independent_retranslation(self):
        with self.assertRaisesRegex(WorkflowError, "Narration copy differs"):
            captions.validate_spoken_copy(self.inventory, [{"id": "a001", "target_text": "如何制作手势特效？"}])

    def test_real_mix_timing_shortens_display_but_retains_english_erase_window(self):
        write_json(self.run / "analysis/inventory.json", self.inventory)
        write_json(self.run / "analysis/alignment.json", self.alignment)
        before = file_hash(self.run / "analysis/inventory.json")
        preview = captions.apply_alignment(self.run, "analysis/alignment.json")
        self.assertEqual(file_hash(self.run / "analysis/inventory.json"), before)
        self.assertFalse(preview["applied"])
        captions.apply_alignment(self.run, "analysis/alignment.json", apply=True)
        updated = read_json(self.run / "analysis/inventory.json")
        item = updated["text_instances"][0]
        self.assertEqual(item["source_interval"], [0, 5.6])
        rendered = captions.render_instances([item])
        self.assertEqual(rendered[-1]["end"], 4.1)
        self.assertEqual(updated["text_instances"][1], self.inventory["text_instances"][1])
        captions.plan_assets(self.run, updated, 6)
        (self.run / "mix.wav").write_bytes(b"different voice or mix")
        with self.assertRaisesRegex(WorkflowError, "audio missing or changed"):
            captions.plan_assets(self.run, updated, 6)

    def test_raw_tts_timeline_and_unreviewed_asr_are_rejected(self):
        for field, value in (("timeline", "raw_tts_seconds"), ("status", "pending")):
            changed = {**self.alignment, field: value}
            with self.assertRaises(WorkflowError):
                captions.compile_alignment(self.run, self.inventory, changed, 6)

    def test_new_alignment_can_replace_old_bad_fragments_after_copy_revision(self):
        self.inventory['text_instances'][0]['display'] = {'timed_fragments': [[0, 7, '旧字幕残留']]}
        with self.assertRaises(WorkflowError):
            captions.contract(self.inventory)
        write_json(self.run / 'analysis/inventory.json', self.inventory)
        write_json(self.run / 'analysis/alignment.json', self.alignment)
        captions.apply_alignment(self.run, 'analysis/alignment.json', apply=True)
        updated = read_json(self.run / 'analysis/inventory.json')
        self.assertTrue(captions.contract(updated)['required'])
        self.assertEqual(captions.units(updated['text_instances'][0])[-1]['end'], 4.1)

    def test_alignment_cannot_drop_last_clause_or_use_overlapping_words(self):
        changed = copy.deepcopy(self.alignment)
        changed["segments"][0]["units"].pop()
        with self.assertRaisesRegex(WorkflowError, "differs from final script"):
            captions.compile_alignment(self.run, self.inventory, changed, 6)
        changed = copy.deepcopy(self.alignment)
        changed["segments"][0]["units"][1]["start"] = 1
        with self.assertRaisesRegex(WorkflowError, "overlap"):
            captions.compile_alignment(self.run, self.inventory, changed, 6)

    def review_fixture(self):
        item = self.inventory["text_instances"][0]
        item["display"] = {"timed_fragments": [[0, 4.1, item["target_text"]]]}
        write_json(self.run / "analysis/inventory.json", self.inventory)
        candidate = {"sha256": "synthetic-video-hash", "plan_id": "p001"}
        directory = self.run / "review/synthetic-vi"
        directory.mkdir(parents=True)
        wav, frame = directory / "audio.wav", directory / "caption-t001-000-1.jpg"
        wav.write_bytes(b"actual captured fixture audio")
        frame.write_bytes(b"actual captured fixture frame")
        paths = [path.relative_to(self.run).as_posix() for path in (wav, frame)]
        captured = {"video_sha256": candidate["sha256"], "files": {path: file_hash(self.run / path) for path in paths}}
        report = captions.review_template(self.run, candidate, self.inventory, {"path": paths[0], "sha256": file_hash(wav)})
        report.update(reviewer="synthetic contract stub", method="Known fixture; no business acceptance", decision="pass", evidence=paths)
        row = report["instances"][0]
        row.update(audio_units=copy.deepcopy(row["planned_units"]), visual_units=copy.deepcopy(row["planned_units"]),
                   decision="pass", method="Synthetic AV timing fixture", evidence=paths)
        return candidate, captured, report, directory / "caption-sync.json"

    def test_aligned_av_review_passes_and_english_timing_lag_fails(self):
        candidate, captured, report, path = self.review_fixture()
        write_json(path, report)
        self.assertEqual(captions.evaluate(self.run, candidate, self.inventory, captured, POLICY)["decision"], "pass")
        report["instances"][0]["visual_units"][0]["end"] = 5.6
        write_json(path, report)
        result = captions.evaluate(self.run, candidate, self.inventory, captured, POLICY)
        self.assertIn("caption_audio_out_of_sync:t001:0", result["failures"])

    def test_audio_only_sync_pass_does_not_prove_caption_sync(self):
        candidate, captured, report, path = self.review_fixture()
        report["instances"][0]["visual_units"] = []
        write_json(path, report)
        self.assertEqual(captions.evaluate(self.run, candidate, self.inventory, captured, POLICY)["decision"], "revise")

    def test_changed_video_audio_and_caption_track_cannot_reuse_old_sync_review(self):
        candidate, captured, report, path = self.review_fixture()
        report["video_sha256"] = "other-video"
        report["audio"]["sha256"] = "other-audio"
        report["track_sha256"] = "old-captions"
        write_json(path, report)
        result = captions.evaluate(self.run, candidate, self.inventory, captured, POLICY)
        self.assertIn("caption_sync_binding_mismatch", result["failures"])
        self.assertIn("caption_sync_actual_audio_missing_or_changed", result["failures"])

    def test_source_frame_is_not_candidate_caption_evidence(self):
        candidate, captured, report, path = self.review_fixture()
        report["instances"][0]["evidence"] = ["analysis/shot-001.jpg"]
        write_json(path, report)
        self.assertEqual(captions.evaluate(self.run, candidate, self.inventory, captured, POLICY)["decision"], "revise")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg media integration")
class CaptionMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(dir=TEMP)
        cls.root = Path(cls.temporary.name)
        for relative in ("config/workspace.json", "config/quality.json", "config/profiles/company-default/profile.json"):
            target = cls.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(PROJECT / relative, target)
        copy_project_knowledge(PROJECT, cls.root)
        cls.patches = [patch.object(module, "ROOT", cls.root) for module in (common, cli, demo, knowledge, workflow)]
        for item in cls.patches:
            item.start()
            cls.addClassCleanup(item.stop)
        demo.create_demo("caption-contract", "local_overlay", 2)
        cls.run_dir = common.get_run("caption-contract")

    @classmethod
    def tearDownClass(cls):
        for item in reversed(cls.patches):
            item.stop()
        cls.temporary.cleanup()

    def test_real_renderer_capture_and_quality_gate(self):
        run = self.run_dir
        media.ffmpeg(["-i", run / "inputs/source.mp4", "-vn", "-c:a", "pcm_s16le", run / "mix.wav"])
        inventory = read_json(run / "analysis/inventory.json")
        for item in inventory["text_instances"]:
            item["text_role"] = "preserve" if item["action"] == "preserve" else "scene_text"
        caption = inventory["text_instances"][1]
        caption.update(target_text="Hello world", text_role="speech_caption", speech_id="a001")
        inventory["audio"] = {"strategy": "replace", "has_speech": True, "replacement_path": "mix.wav",
                              "reason": "Synthetic contract stub, sine wave only; not real speech evaluation"}
        inventory["speech_segments"] = [{"id": "a001", "source_text": "Hello world", "target_text": "Hello world",
                                         "character_id": "synthetic_narrator", "speech_role": "narration",
                                         "start": 0, "end": 2, "caption_policy": "verbatim", "caption_ids": [caption["id"]],
                                         "evidence": ["analysis/fixture-provenance.txt"]}]
        inventory['routing_assessment']['primary_type'] = 'mixed'
        inventory['routing_assessment']['method_choices'].append({
            'domain':'speech','method_id':'method-spoken-caption-verification-v4',
            'reason':'Synthetic caption/sine-wave timing contract only; no speech acceptance claim',
            'alternative':'Revise the generated fixture timing specification',
            'switch_when':'The actual encoded caption differs from the fixture timestamps',
            'stop_when':'The synthetic timing contract passes or the test fails'})
        write_json(run / "analysis/inventory.json", inventory)
        workflow.build_plan(run)
        with self.assertRaisesRegex(WorkflowError, "Align speech captions"):
            workflow.render(run)
        alignment = {"schema_version": 1, "source_sha256": inventory["source_sha256"], "target_language": "zh-CN",
                     "audio": {"path": "mix.wav", "sha256": file_hash(run / "mix.wav")},
                     "timeline": "final_mix_seconds", "status": "reviewed", "reviewer": "Synthetic timing spec",
                     "method": "manual_listening", "segments": [{"speech_id": "a001", "units": [
                         {"text": "Hello", "start": .2, "end": .6}, {"text": "world", "start": .6, "end": 1}]}]}
        write_json(run / "analysis/alignment.json", alignment)
        captions.apply_alignment(run, "analysis/alignment.json", True)
        workflow.build_plan(run)
        workflow.render(run)
        candidate = read_json(run / "outputs/candidate.json")
        cli.capture(run)
        report_path = run / "review" / candidate["sha256"][:12] / "caption-sync.json"
        self.assertTrue(report_path.exists())
        self.assertIn("caption_sync_unverified", workflow.quality(run)["failures"])
        report = read_json(report_path)
        captured = read_json(run / "review/capture.json")
        wav = next(path for path in captured["files"] if path.endswith("/audio.wav"))
        frame = next(path for path in captured["files"] if "/caption-" in path and path.endswith(".jpg"))
        report.update(reviewer="Synthetic contract test", method="Fixture timestamps only", decision="pass", evidence=[wav, frame])
        for row in report["instances"]:
            row.update(audio_units=copy.deepcopy(row["planned_units"]), visual_units=copy.deepcopy(row["planned_units"]),
                       decision="pass", method="Fixture timestamps only", evidence=[wav, frame])
        write_json(report_path, report)
        cli.capture(run)  # Freeze the completed review into the capture manifest.
        review = read_json(run / "review/template.json")
        review.update(reviewer="Synthetic contract test", method="Not semantic speech acceptance", video_sha256=candidate["sha256"], decision="pass")
        review["scores"] = {key: 5 for key in review["scores"]}
        for row in review["instances"]:
            row.update(decision="pass", evidence=[wav, frame])
        review["coverage"] = {key: {"status": "reviewed", "evidence": [wav if key == "audio" else frame]}
                              for key in ("visual", "audio", "timing")}
        for check in review["audio_checks"].values():
            check.update(decision="pass", method="Synthetic fixture", evidence=[wav])
        write_json(run / "review/review.json", review)
        from workspace_fixture import observe_visual_fixture
        observe_visual_fixture(run)
        cli.capture(run)
        self.assertEqual(workflow.quality(run)["decision"], "pass")
        # Check rendered pixels, rather than only inspecting generated ASS text.
        def crop(second):
            result = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(second), "-i", str(run / candidate["path"]),
                                     "-vf", "crop=680:60:300:315", "-frames:v", "1", "-pix_fmt", "gray", "-f", "rawvideo", "pipe:1"],
                                    check=True, capture_output=True)
            return result.stdout
        during, after = crop(.4), crop(1.5)
        self.assertGreater(sum(value < 130 for value in during), 100)
        self.assertLess(sum(value < 130 for value in after), 50)
        # A late caption still fails even when every numeric quality score is five.
        report["instances"][0]["visual_units"][-1]["end"] = 1.8
        write_json(report_path, report)
        cli.capture(run)
        self.assertEqual(workflow.quality(run)["decision"], "revise")
        with self.assertRaisesRegex(WorkflowError, "not accepted"):
            workflow.deliver(run)
        (run / "analysis/alignment.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(WorkflowError, "Caption alignment/audio changed"):
            workflow.current_plan(run)


if __name__ == "__main__":
    unittest.main()
