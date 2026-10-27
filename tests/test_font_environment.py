from pathlib import Path
import tempfile
import unittest
import sys
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))

from video_localizer import font_environment,render_cache
from video_localizer.common import CODE_ROOT,file_hash


class FontEnvironmentTests(unittest.TestCase):
    def test_project_fonts_are_discovered_on_mac_without_windows_directory(self):
        with tempfile.TemporaryDirectory(dir=CODE_ROOT/'work/test-tmp') as temp:
            root=Path(temp);p=root/'assets/fonts/fixture.otf';p.parent.mkdir(parents=True);p.write_bytes(b'synthetic font identity')
            with patch.object(font_environment.sys,'platform','darwin'):
                self.assertIn(p.resolve(),font_environment.files(root))

    def test_operation_cache_reuses_reads_and_detects_font_changes(self):
        with tempfile.TemporaryDirectory(dir=CODE_ROOT/'work/test-tmp') as temp:
            path=Path(temp)/'font.ttf';path.write_bytes(b'old fixture');cache={}
            with patch.object(font_environment,'files',return_value=[path]),patch('video_localizer.common.file_hash',wraps=file_hash) as hashed:
                before=font_environment.fingerprint(temp,cache)
                self.assertEqual(before,font_environment.fingerprint(temp,cache));self.assertEqual(hashed.call_count,1)
                path.write_bytes(b'changed fixture with a new length')
                self.assertNotEqual(before,font_environment.fingerprint(temp,cache));self.assertEqual(hashed.call_count,2)
                font_environment.fingerprint(temp);self.assertEqual(hashed.call_count,3)

    def test_unknown_font_environment_still_disables_segment_reuse(self):
        with patch.object(font_environment,'files',return_value=[]):
            self.assertIsNone(font_environment.fingerprint(CODE_ROOT))
            self.assertIsNone(render_cache.signature(CODE_ROOT/'runs/fixture',{'source_sha256':'a'*64},
                {'id':'s001','route':'local_overlay','instance_ids':[],'start':0,'end':1},{'text_instances':[]},{'duration':1}))


if __name__=='__main__':unittest.main()
