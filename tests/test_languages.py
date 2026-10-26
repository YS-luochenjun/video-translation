import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from video_localizer import languages, workflow
from video_localizer.common import WorkflowError, read_json, write_json

TEMP = PROJECT / "work/test-tmp"
TEMP.mkdir(parents=True, exist_ok=True)


class LanguageAliasTests(unittest.TestCase):
    def test_all_user_aliases_and_display_names_resolve(self):
        data = read_json(PROJECT / "config/language-aliases.json")
        self.assertEqual(len(data["groups"]), 27)
        for code, aliases in data["groups"].items():
            for alias in aliases + [data["names_zh"][code]]:
                with self.subTest(alias=alias):
                    result = languages.resolve(" " + alias.upper() + " ", PROJECT)
                    if '-' in alias:
                        self.assertEqual(result['target_language'].casefold(), alias.casefold())
                        self.assertFalse(result['matched_alias'])
                        continue
                    self.assertEqual(result["target_language"], code)
                    self.assertTrue(result["matched_alias"])

    def test_business_aliases_and_explicit_unlisted_locales(self):
        expected = {"Japan": "ja", "日语": "ja", "us2": "en", "br": "pt", "pt-BR": "pt-BR",
                    "hk": "zh", "in": "hi", "tl": "fil", "zhtw": "zh-TW",
                    "zh-CN": "zh-CN", "ja-JP": "ja-JP", "es-MX": "es-MX", "zh-HK": "zh-HK"}
        for alias, code in expected.items():
            with self.subTest(alias=alias):
                self.assertEqual(languages.resolve(alias, PROJECT)["target_language"], code)

    def test_unknown_names_and_conflicting_dictionary_are_rejected(self):
        for alias in ("", "   ", "not-a-language-name", "../ja", "未指定语言"):
            with self.subTest(alias=alias), self.assertRaises(WorkflowError):
                languages.resolve(alias, PROJECT)
        with tempfile.TemporaryDirectory(dir=TEMP) as directory:
            root = Path(directory)
            write_json(root / "config/language-aliases.json",
                       {"groups": {"ja": ["jp"], "en": ["JP"]}, "names_zh": {}})
            with self.assertRaisesRegex(WorkflowError, "Ambiguous"):
                languages.resolve("jp", root)

    def test_new_request_normalizes_target_and_preserves_original_without_a_real_video(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as directory:
            root = Path(directory)
            (root / "config").mkdir()
            shutil.copyfile(PROJECT / "config/language-aliases.json", root / "config/language-aliases.json")
            write_json(root / "config/workspace.json",
                       {"default_workflow": "video-localization", "default_profile": "company-default"})
            write_json(root / "config/profiles/company-default/profile.json", {})
            video = root / "fixture.mp4"
            video.write_bytes(b"mocked media probe; not a real video")
            with patch.object(workflow, "ROOT", root), patch.object(workflow.media, "probe", return_value={"duration": 2}):
                workflow.create_run(video, "Japan", "Keep brand", "alias-test")
            request = read_json(root / "runs/alias-test/inputs/request.json")
            self.assertEqual(request["target_language"], "ja")
            self.assertEqual(request["requested_target_language"], "Japan")
            self.assertEqual(request["brief"], "Keep brand")

    def test_existing_workspace_without_dictionary_keeps_language_tags(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as directory:
            self.assertEqual(languages.resolve("zh-CN", directory)["target_language"], "zh-CN")

    def test_language_policy_does_not_compete_with_production_methods(self):
        index = read_json(PROJECT / "knowledge/index.json")
        policy = next(e for e in index["entries"] if e["id"] == "language-aliases-v1")
        self.assertEqual(policy["scope"], {"workflow": "video-localization", "phase": "language_resolution"})
        evidence = PROJECT / policy["case"] / "evidence/language-aliases.json"
        self.assertEqual(json.loads(evidence.read_text(encoding="utf-8")),
                         read_json(PROJECT / "config/language-aliases.json"))


if __name__ == "__main__":
    unittest.main()
