import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import test_fireplay as fixtures
from test_fireplay_publication import PublicationTests
from video_localizer import bundles, fireplay, fireplay_publication, quality_holds
from video_localizer.common import WorkflowError, file_hash, read_json, write_json


class AcceptedPublicationHoldTests(unittest.TestCase):
    setUp = fixtures.FireplayTests.setUp
    register = fixtures.FireplayTests.register
    record = fixtures.FireplayTests.record
    save = fixtures.FireplayTests.save
    downloaded = fixtures.FireplayTests.downloaded
    returned_setup = fixtures.FireplayTests.returned_setup
    complete_output = PublicationTests.complete_output

    def accepted_output(self):
        spec, assessment = self.complete_output("major", many=True)
        item = spec["packages"][0]
        prior = fireplay_publication.review(fixtures.CODE, {"package": item["package"], "assessment": assessment}, self.root)
        folder = self.root / item["package"]
        source = prior["source_sha256"] if "source_sha256" in prior else bundles.verify(folder)["metadata"]["source_sha256"]
        approval = {"authority": "user", "accepted": True, "authorization_ref": "trusted-user-message",
                    "source_quote": "Accept the displayed repaired version and upload it",
                    "video_sha256": prior["video_sha256"]}
        accepted = fireplay_publication.review(fixtures.CODE, {"package": item["package"], "user_acceptance": approval}, self.root)
        return spec, folder, source, prior["video_sha256"], accepted

    def test_exact_acceptance_clears_only_scoped_publication_hold(self):
        spec, folder, source, digest, accepted = self.accepted_output()
        with patch("video_localizer.quality_holds.active", return_value=[{"id": "old-objection", "reason": "Visible repair seam", "recorded_at": "2020-01-01T00:00:00Z"}]):
            self.assertFalse(fireplay_publication.held(fixtures.CODE, source, digest, self.root))
            self.assertTrue(fireplay_publication.held("APC-20261027-999", source, digest, self.root))
            self.assertTrue(fireplay_publication.held(fixtures.CODE, source, "f" * 64, self.root))
            with self.assertRaisesRegex(WorkflowError, "Quality hold"):
                quality_holds.require_clear(source, digest, self.root)
        self.assertTrue(accepted["internal_quality_unchanged"])

    def test_new_objection_after_acceptance_is_still_active(self):
        spec, folder, source, digest, accepted = self.accepted_output()
        with patch("video_localizer.quality_holds.active", return_value=[{"id": "new-objection", "recorded_at": "2999-01-01T00:00:00Z"}]):
            self.assertTrue(fireplay_publication.held(fixtures.CODE, source, digest, self.root))

    def test_changed_prior_review_cannot_release_hold(self):
        spec, folder, source, digest, accepted = self.accepted_output()
        path = self.root / accepted["prior_review"]["path"]
        altered = read_json(path)
        altered["assessment"]["translation_complete"] = False
        write_json(path, altered)
        with patch("video_localizer.quality_holds.active", return_value=[{"id": "old-objection"}]):
            with self.assertRaisesRegex(WorkflowError, "acceptance.*changed"):
                fireplay_publication.held(fixtures.CODE, source, digest, self.root)

    def test_explicit_repair_revision_adopts_current_naming_without_changing_prior_receipts(self):
        spec = self.returned_setup()
        prior_path = self.root / "state/fireplay" / fixtures.CODE / "return-1.json"
        old = read_json(prior_path)
        old["state"] = "returned"
        old["operations"] = {"bind": {"state": "verified"}}
        write_json(prior_path, old)
        digest = file_hash(prior_path)
        config = self.root / "config/fireplay-intake.json"
        defaults = read_json(config)
        defaults["publication"]["upload_metadata"] = {"version": 1, "authority": "user", "authorization_ref": "new-title-rule",
            "name_fields": ["language", "category", "pid", "did", "requirement_code"], "separator": " "}
        defaults["designer_selection"]["tag"] = "derivative"
        write_json(config, defaults)
        spec["material_metadata"] = {"category": "FaceZoom", "pid": "11", "evidence_ref": "actual-requester-pid"}
        spec["repair_revision"] = {"authority": "user", "authorization_ref": "repair-approval",
                                  "source_quote": "Complete and upload repaired versions",
                                  "reason": "New repaired full outputs", "previous_outbox_sha256": digest}
        for item in spec["packages"]:
            original = self.root / item["package"]
            manifest = bundles.verify(original)
            movie = self.root / "work" / (item["locale"] + "-repaired.mp4")
            movie.write_bytes(b"new-repaired-" + item["locale"].encode())
            quality = self.root / "work" / (item["locale"] + "-quality.json")
            write_json(quality, {"decision": "pass", "video_sha256": file_hash(movie)})
            target = original.with_name(original.name + "-repair")
            bundles.create(target, "delivery", file_hash(movie),
                           {"final.mp4": movie, "payload/outputs/quality.json": quality},
                           {**manifest["metadata"], "video_sha256": file_hash(movie)})
            item["package"] = str(target.relative_to(self.root))
        result = fireplay.prepare_return(fixtures.CODE, spec, self.root)
        self.assertEqual(result["packages"][0]["display_name"].split()[1:3], ["FaceZoom", "11"])
        archive = self.root / result["revision_history"][-1]["prior_outbox"]
        self.assertEqual(file_hash(archive), digest)


if __name__ == "__main__":
    unittest.main()
