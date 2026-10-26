import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from video_localizer import bundles, delivery_index
from video_localizer.common import file_hash, read_json, write_json


class DeliveryIndexTests(unittest.TestCase):
    def setUp(self):
        temp = PROJECT / "work/test-tmp"
        temp.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = self.root / "fixture.mp4"
        source.write_bytes(b"actual video fixture")
        self.sha = file_hash(source)
        self.package = self.root / "outputs/source/es/version"
        self.entry = {"source_sha256": "a" * 64, "target_language": "es",
                      "video_sha256": self.sha, "status": "historical_reference",
                      "origin_run_id": '<img src=x onerror="bad()">',
                      "package": "outputs/source/es/version"}
        bundles.create(self.package, "delivery", self.sha, {"final.mp4": source},
                       {**self.entry, "technical_decision": "revise"})
        self.entry["manifest_sha256"] = file_hash(self.package / "manifest.json")
        write_json(self.root / "outputs/index.json", {"entries": [self.entry]})

    def test_page_escapes_names_keeps_reference_status_and_does_not_copy_video(self):
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        result = delivery_index.refresh(self.root)
        page = (self.root / result["page"]).read_text(encoding="utf-8")
        self.assertIn("&lt;img", page)
        self.assertNotIn('<img src=x', page)
        self.assertIn('href="source/es/version/final.mp4"', page)
        self.assertEqual(result["counts"], {"delivered": 0, "with_issues": 0, "reference": 1, "unavailable": 0})
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(set(after) - set(before), {Path("outputs/index.html")})
        for path, data in before.items():
            self.assertEqual(after[path], data)

    def test_changed_video_missing_file_and_escaping_path_are_not_linked(self):
        for change in ("changed", "missing", "escape"):
            with self.subTest(change=change):
                video = self.package / "final.mp4"
                if change == "changed":
                    video.write_bytes(b"changed")
                elif change == "missing":
                    video.unlink()
                else:
                    self.entry["package"] = "../outside"
                    write_json(self.root / "outputs/index.json", {"entries": [self.entry]})
                result = delivery_index.refresh(self.root)
                self.assertEqual(result["counts"]["unavailable"], 1)
                self.assertNotIn("打开视频", (self.root / result["page"]).read_text(encoding="utf-8"))

    def test_catalog_cannot_relabel_reference_as_delivered(self):
        self.entry["status"] = "delivered"
        write_json(self.root / "outputs/index.json", {"entries": [self.entry]})
        result = delivery_index.refresh(self.root)
        self.assertEqual(result["counts"]["delivered"], 0)
        self.assertEqual(result["counts"]["unavailable"], 1)
        self.assertEqual(result['diagnostics'][0]['reason'], 'Catalog differs from manifest: status')

    def test_invalid_manifest_is_diagnosed_and_html_escaped_without_link(self):
        manifest = self.package / 'manifest.json'
        manifest.write_text('', encoding='utf-8')
        self.entry['manifest_sha256'] = file_hash(manifest)
        write_json(self.root / 'outputs/index.json', {'entries': [self.entry]})
        result = delivery_index.refresh(self.root)
        self.assertIn('manifest.json', result['diagnostics'][0]['reason'])
        self.assertEqual(result['counts']['unavailable'], 1)
        self.assertNotIn('打开视频', (self.root / result['page']).read_text())


    def test_valid_delivery_and_empty_new_workspace(self):
        manifest = read_json(self.package / "manifest.json")
        manifest["metadata"].update(status="delivered", technical_decision="pass")
        write_json(self.package / "manifest.json", manifest)
        self.entry.update(status="delivered", manifest_sha256=file_hash(self.package / "manifest.json"))
        write_json(self.root / "outputs/index.json", {"entries": [self.entry]})
        self.assertEqual(delivery_index.refresh(self.root)["counts"]["delivered"], 1)
        fresh = self.root / "fresh"
        fresh.mkdir()
        self.assertEqual(delivery_index.refresh(fresh)["counts"],
                         {"delivered": 0, "with_issues": 0, "reference": 0, "unavailable": 0})


if __name__ == "__main__":
    unittest.main()
