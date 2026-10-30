import copy
import json
import shutil
import sys
import tempfile
import unittest
from workspace_fixture import copy_project_knowledge
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from video_localizer import audio, cli, common, demo, knowledge, media, workflow
from video_localizer.common import WorkflowError, file_hash, read_json, write_json
from video_localizer.contracts import validate_inventory

PROJECT = Path(__file__).resolve().parents[1]
TEMP = PROJECT / "work/test-tmp"
TEMP.mkdir(parents=True, exist_ok=True)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class AudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(dir=TEMP)
        cls.root = Path(cls.temporary.name)
        cls.source = cls.root / "source.mp4"
        media.ffmpeg(["-f", "lavfi", "-i", "color=green:s=160x96:r=30:d=2",
                      "-f", "lavfi", "-i", "anoisesrc=color=pink:sample_rate=48000:duration=2:seed=42",
                      "-af", "volume=0.15", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", cls.source])
        cls.visual = cls.root / "visual.mp4"
        media.normalize(cls.source, 2, media.probe(cls.source), cls.visual)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_preserve_mux_keeps_audible_source_after_silent_visual_processing(self):
        output = self.root / "retained.mp4"
        media.assemble([self.visual], self.source, output, 2)
        result = audio.evaluate(self.source, output, {"strategy": "preserve"}, 2)
        self.assertFalse(result["failures"], result)
        self.assertGreater(result["waveform_match"]["correlation"], 0.97)

    def test_audio_track_containing_silence_is_rejected(self):
        output = self.root / "silent-track.mp4"
        media.ffmpeg(["-i", self.visual, "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                      "-t", "2", "-c:v", "copy", "-c:a", "aac", output])
        result = audio.evaluate(self.source, output, {"strategy": "preserve"}, 2)
        self.assertTrue(result["candidate"]["has_track"])
        self.assertIn("audio_silent_or_near_silent", result["failures"])

    def test_missing_audio_is_rejected_when_source_has_sound(self):
        result = audio.evaluate(self.source, self.visual, {"strategy": "preserve"}, 2)
        self.assertIn("audio_track_mismatch", result["failures"])

    def test_different_soundtrack_cannot_pass_as_retained_music(self):
        output = self.root / "wrong-music.mp4"
        media.ffmpeg(["-i", self.visual, "-f", "lavfi", "-i", "sine=f=880:r=48000:d=2",
                      "-t", "2", "-c:v", "copy", "-c:a", "aac", output])
        result = audio.evaluate(self.source, output, {"strategy": "preserve"}, 2)
        self.assertIn("source_music_or_effects_changed", result["failures"])

    def test_shifted_music_is_rejected_even_when_the_waveform_matches(self):
        output = self.root / "shifted.mp4"
        media.ffmpeg(["-i", self.source, "-af", "adelay=80:all=1", "-t", "2",
                      "-c:v", "copy", "-c:a", "aac", output])
        result = audio.evaluate(self.source, output, {"strategy": "preserve"}, 2)
        self.assertIn("audio_sync_shift", result["failures"])

    def test_model_audio_can_be_selected_without_reusing_foreign_source_mix(self):
        first = audio.extract_track(self.source, self.root / "part1.wav", 0, 1)
        second = audio.extract_track(self.source, self.root / "part2.wav", 1, 1)
        selected = audio.concatenate([first, second], self.root / "translated-mix.wav")
        output = self.root / "model-audio.mp4"
        media.assemble([self.visual], selected, output, 2)
        result = audio.evaluate(self.source, output, {"strategy": "model"}, 2)
        self.assertTrue(result["candidate"]["audible_signal"])
        self.assertFalse(result["failures"])

    def test_missing_model_audio_does_not_fall_back_to_source_or_silence(self):
        with self.assertRaisesRegex(WorkflowError, "missing"):
            audio.extract_track(self.visual, self.root / "missing.wav", 0, 1)

    def test_short_model_audio_tail_does_not_shift_the_next_segment(self):
        short = self.root / "short-audio.wav"
        media.ffmpeg(["-i", self.source, "-vn", "-t", "1.85", "-c:a", "pcm_s16le", short])
        aligned = audio.extract_track(short, self.root / "aligned.wav", 0, 2)
        self.assertAlmostEqual(audio.inspect(aligned)[0]["duration"], 2, places=3)
        self.assertAlmostEqual(read_json(aligned.with_suffix(".json"))["tail_padding_seconds"], 0.15, places=2)

    def test_prompt_delegates_dialogue_even_when_agent_cannot_hear(self):
        prompt = "\n".join(audio.prompt({"strategy": "model", "has_speech": None}, "zh-CN", True, [], 0, 2))
        self.assertIn("background music and sound effects", prompt)
        self.assertIn("translate", prompt)
        self.assertIn("cannot verify the speech", prompt)
        self.assertNotIn("no audio", prompt)

    def test_no_track_source_does_not_authorize_invented_music(self):
        prompt = "\n".join(audio.prompt({"strategy": "preserve", "has_speech": False}, "zh-CN", False, [], 0, 2))
        self.assertIn("NO audio stream", prompt)
        self.assertIn("Keep this source silent", prompt)

    def test_source_region_restoration_keeps_unedited_banner_and_edited_scene(self):
        edited = self.root / "red-edit.mp4"
        media.ffmpeg(["-f", "lavfi", "-i", "color=red:s=160x96:r=30:d=2",
                      "-c:v", "libx264", "-pix_fmt", "yuv420p", edited])
        result = media.restore_regions(self.source, edited, {"start": 0, "end": 2}, [[0, 0, 160, 40]], self.root / "regions")
        def pixel(y):
            import subprocess
            value = subprocess.run(["ffmpeg", "-v", "error", "-i", str(result), "-vf", f"crop=2:2:50:{y}",
                                    "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
                                   check=True, capture_output=True)
            return value.stdout[:3]
        top, bottom = pixel(10), pixel(70)
        self.assertGreater(top[1], top[0] + 80)
        self.assertGreater(bottom[0], bottom[1] + 150)

    def test_capture_uses_video_end_when_audio_outlasts_picture(self):
        run = self.root / "long-audio-capture"
        for folder in ["inputs", "outputs", "analysis"]:
            (run / folder).mkdir(parents=True, exist_ok=True)
        source = run / "inputs/source.mp4"
        media.ffmpeg(["-i", self.visual, "-f", "lavfi", "-i", "sine=f=440:r=48000:d=2.2",
                      "-c:v", "copy", "-c:a", "aac", source])
        write_json(run / "run.json", {"source": "inputs/source.mp4", "source_sha256": file_hash(source)})
        write_json(run / "analysis/media.json", media.probe(source))
        write_json(run / "analysis/inventory.json", {"audio": {"strategy": "preserve", "has_speech": False}})
        write_json(run / "outputs/candidate.json", {"path": "inputs/source.mp4", "sha256": file_hash(source), "plan_id": "fixture"})
        cli.capture(run)
        record = read_json(run / "review/capture.json")
        self.assertTrue(any(path.endswith("boundary-end.jpg") for path in record["files"]))


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class NativeAudioContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(dir=TEMP)
        cls.root = Path(cls.temporary.name)
        for name in ("config/workspace.json", "config/quality.json", "config/profiles/company-default/profile.json"):
            output = cls.root / name
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(PROJECT / name, output)
        copy_project_knowledge(PROJECT, cls.root)
        cls.patches = [patch.object(module, "ROOT", cls.root) for module in (common, cli, demo, knowledge, workflow)]
        for item in cls.patches:
            item.start()
            cls.addClassCleanup(item.stop)
        demo.create_demo("audio-contract", "local_overlay")
        from workspace_fixture import legacy_typography_fixture
        legacy_typography_fixture(common.get_run('audio-contract'))
        cls.run_dir = common.get_run("audio-contract")
        cls.original_inventory = read_json(cls.run_dir / "analysis/inventory.json")

    @classmethod
    def tearDownClass(cls):
        for item in reversed(cls.patches):
            item.stop()
        cls.temporary.cleanup()

    def setUp(self):
        write_json(self.run_dir / "analysis/inventory.json", self.original_inventory)

    def test_source_audio_cannot_be_muted_without_authorization(self):
        data = copy.deepcopy(self.original_inventory)
        data["audio"]["strategy"] = "mute"
        with self.assertRaisesRegex(WorkflowError, "authorization"):
            validate_inventory(data, self.run_dir, read_json(self.run_dir / "analysis/media.json"))

    def test_audio_analysis_submission_reuses_receipt_instead_of_charging_again(self):
        from workspace_fixture import isolate_mock_provider
        isolate_mock_provider(self)
        count = []
        class Client:
            def upload(self, path):
                return "https://example.org/audio.wav"
            def analyze_audio(self, urls, prompt, model=None):
                count.append(urls)
                return {"id": "synthetic-audio-receipt", "choices": [{"message": {"content": '{"has_speech": false, "speech_segments": []}'}}],
                        "credits_consumed": 0.1}
        first = workflow.analyze_audio(self.run_dir, Client())
        second = workflow.analyze_audio(self.run_dir, Client())
        self.assertEqual(first["job"], second["job"])
        self.assertTrue(second["reused"])
        self.assertEqual(len(count), 1)

    def test_native_model_audio_enables_auto_audio_in_actual_packet(self):
        data = copy.deepcopy(self.original_inventory)
        data["audio"].update({"strategy": "model", "has_speech": None,
                              "reason": "Explicit delegated audio inspection; not a passing speech claim"})
        data["coverage"]["speech"]["status"] = "pending"
        for shot in data["shots"]:
            shot["video_model"] = "wan/2-7-videoedit"
        for item in data["text_instances"]:
            if item["action"] != "preserve":
                item["action"] = "model_edit"
        write_json(self.run_dir / "analysis/inventory.json", data)
        workflow.build_plan(self.run_dir)
        packet = workflow.prepare_packet(self.run_dir, "s001")
        self.assertEqual(packet["payload"]["input"]["audio_setting"], "auto")
        self.assertIsNone(packet["audio_contract"]["has_speech"])
        self.assertIn("translate", packet["payload"]["input"]["prompt"])

    def test_returned_sound_is_muxed_but_unreviewed_semantics_blocks_delivery(self):
        data = copy.deepcopy(self.original_inventory)
        data["audio"].update({"strategy": "model", "has_speech": False,
                              "reason": "Known synthetic no-speech contract fixture, not a real dubbing evaluation"})
        for shot in data["shots"]:
            shot["video_model"] = "wan/2-7-videoedit"
        for item in data["text_instances"]:
            if item["action"] != "preserve":
                item["action"] = "model_edit"
        write_json(self.run_dir / "analysis/inventory.json", data)
        workflow.build_plan(self.run_dir)
        plan = read_json(self.run_dir / "plan.json")
        source = self.run_dir / "inputs/source.mp4"
        write_json(self.run_dir / "jobs/fixture.json", {"plan_id": plan["id"], "segment": "s001", "state": "success",
                   "result": "inputs/source.mp4", "result_sha256": file_hash(source), "task_id": "synthetic-native-audio"})
        workflow.render(self.run_dir)
        candidate = read_json(self.run_dir / "outputs/candidate.json")
        self.assertTrue(media.probe(self.run_dir / candidate["path"])["has_audio"])
        cli.capture(self.run_dir)
        capture = read_json(self.run_dir / "review/capture.json")
        frame = next(path for path in capture["files"] if path.endswith("frame-00001.jpg"))
        wav = next(path for path in capture["files"] if path.endswith("audio.wav"))
        review = read_json(self.run_dir / "review/template.json")
        review.update({"reviewer": "automated audio contract fixture", "method": "Test stub; no semantic acceptance claim",
                       "video_sha256": candidate["sha256"], "decision": "pass"})
        review["scores"] = {key: 5 for key in review["scores"]}
        for item in review["instances"]:
            item.update({"decision": "pass", "evidence": [frame]})
        review["coverage"] = {key: {"status": "reviewed", "evidence": [wav if key == "audio" else frame]}
                              for key in ("visual", "audio", "timing")}
        write_json(self.run_dir / "review/review.json", review)
        failed = workflow.quality(self.run_dir)
        self.assertIn("audio_semantics_unverified:background_music", failed["failures"])
        self.assertIn("audio_semantics_unverified:dialogue_translation", failed["failures"])
        for item in review["audio_checks"].values():
            item.update({"decision": "pass", "method": "Known generated fixture, contract stub only", "evidence": [wav]})
        write_json(self.run_dir / "review/review.json", review)
        from workspace_fixture import observe_visual_fixture
        observe_visual_fixture(self.run_dir)
        cli.capture(self.run_dir)
        self.assertEqual(workflow.quality(self.run_dir)["decision"], "pass")
        report_path = self.run_dir / "review" / candidate["sha256"][:12] / "audio-model-review.json"
        write_json(report_path, {"source_sha256": file_hash(source), "video_sha256": candidate["sha256"],
                   "analysis": {"background_music": {"same_track": False}, "sound_effects": {"preserved": True},
                                "dialogue_translation": {"complete": True}, "sync": {"acceptable": True},
                                "foreign_speech_remaining": []}})
        self.assertIn("background_music_not_verified_preserved", workflow.quality(self.run_dir)["failures"])

