import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from video_localizer import workflow
from video_localizer.common import WorkflowError, write_json

PROJECT = Path(__file__).resolve().parents[1]
TEST_TEMP = (PROJECT / "work/test-tmp").resolve()
assert TEST_TEMP.is_relative_to(PROJECT)
TEST_TEMP.mkdir(parents=True, exist_ok=True)


class RevisionBudgetTests(unittest.TestCase):
    def fixture(self, name, pixels="picture-a", record="original.json", target="开始"):
        asset = {"path": "master.mp4", "sha256": pixels, "record": record, "record_sha256": record}
        shot = {"id": "s001", "prepared_video": asset,
                "surface_typography": {"path": "type.mov", "sha256": "glyphs", "record": record, "record_sha256": record}}
        inventory = {"shots": [copy.deepcopy(shot)], "text_instances": [{"target_text": target}],
                     "speech_segments": [{"target_text": "你好"}], "audio": {"strategy": "replace"}}
        plan = {"id": name, "inventory_sha256": name, "source_sha256": "source",
                "segments": [shot], "audio_assets": [{"sha256": "sound"}], "quality_sha256": "policy"}
        return plan, inventory

    def freeze(self, root, fixture):
        plan, inventory = fixture
        directory = root / "plans" / plan["id"]
        write_json(directory / "plan.json", plan)
        write_json(directory / "inputs/inventory.json", inventory)

    def test_provenance_only_rebinding_does_not_spend_a_picture_revision(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as tmp:
            root = Path(tmp)
            self.freeze(root, self.fixture("first"))
            self.freeze(root, self.fixture("receipt-moved", record="shared/receipt.json"))
            self.freeze(root, self.fixture("first-picture-revision", pixels="picture-b"))
            plan, inventory = self.fixture("second-picture-revision", pixels="picture-c")
            workflow._check_revision_budget(root, plan, inventory, 2)

    def test_fourth_distinct_picture_is_still_blocked(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as tmp:
            root = Path(tmp)
            for index in range(3):
                self.freeze(root, self.fixture(str(index), pixels=f"picture-{index}"))
            plan, inventory = self.fixture("fourth", pixels="new-picture")
            with self.assertRaisesRegex(WorkflowError, "Revision budget reached"):
                workflow._check_revision_budget(root, plan, inventory, 2)

    def test_copy_speech_or_audio_changes_are_not_provenance_rebindings(self):
        base, inventory = self.fixture("first")
        baseline = workflow._revision_signature(base, inventory)
        for kind in ("copy", "speech", "audio", "policy"):
            plan, changed = copy.deepcopy(base), copy.deepcopy(inventory)
            if kind == "copy": changed["text_instances"][0]["target_text"] = "下一步"
            if kind == "speech": changed["speech_segments"][0]["target_text"] = "再见"
            if kind == "audio": plan["audio_assets"][0]["sha256"] = "different-sound"
            if kind == "policy": plan["quality_sha256"] = "different-policy"
            with self.subTest(kind=kind):
                self.assertNotEqual(workflow._revision_signature(plan, changed), baseline)

    def test_missing_frozen_inventory_is_counted_conservatively(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as tmp:
            root = Path(tmp)
            for index in range(3):
                plan, _ = self.fixture(str(index))
                write_json(root / "plans" / str(index) / "plan.json", plan)
            plan, inventory = self.fixture("another")
            with self.assertRaisesRegex(WorkflowError, "Revision budget reached"):
                workflow._check_revision_budget(root, plan, inventory, 2)


if __name__ == "__main__":
    unittest.main()
