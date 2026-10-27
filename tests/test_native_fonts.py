import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'src'))
from video_localizer import fonts, layout, media, render_cache, typography
from video_localizer.common import WorkflowError, file_hash, read_json, write_json


class NativeFontContractTests(unittest.TestCase):
    def test_exact_requested_windows_family_is_never_disguised_as_native_font(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(sys, 'platform', 'darwin'):
            face = layout.measurement_face(directory, 'Microsoft YaHei', True)
            self.assertEqual(face['path'], Path(directory) / 'assets/fonts/msyhbd.ttc')
            self.assertEqual(face['index'], 0)

    def test_defaults_follow_language_before_script_and_keep_native_names(self):
        with patch.object(sys, 'platform', 'darwin'):
            self.assertEqual(fonts.default_family('開始', 'zh-TW'), 'Heiti TC')
            self.assertEqual(fonts.default_family('開始', 'ja'), 'Hiragino Sans')
            self.assertEqual(fonts.default_family('日本語かな'), 'Hiragino Sans')
            self.assertEqual(fonts.default_family('한국어'), 'Apple SD Gothic Neo')
            self.assertEqual(fonts.default_family('हिन्दी'), 'Devanagari Sangam MN')
            self.assertEqual(fonts.default_family('العربية'), 'Arial')

    def test_project_extracted_font_precedes_system_collection_and_uses_face_zero(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(sys, 'platform', 'darwin'):
            path = Path(directory) / 'assets/fonts/AppleSDGothicNeo-Bold.ttf'
            path.parent.mkdir(parents=True)
            path.write_bytes(b'lookup fixture')
            face = layout.measurement_face(directory, 'Apple SD Gothic Neo', True)
            self.assertEqual(face['path'], path)
            self.assertEqual(face['index'], 0)

    def test_native_style_index_is_explicit_and_not_implicitly_first_face(self):
        with patch.object(sys, 'platform', 'darwin'):
            self.assertEqual(layout.measurement_face('/fixture', 'Heiti SC')['index'], 1)
            self.assertEqual(layout.measurement_face('/fixture', 'Apple SD Gothic Neo', True)['index'], 6)


@unittest.skipUnless(sys.platform == 'darwin', 'Native Mac font integration')
class NativeFontRenderTests(unittest.TestCase):
    def setUp(self):
        base = PROJECT / 'work/test-tmp'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / 'runs/native-fonts'
        write_json(self.run / 'run.json', {'id': 'native-fonts'})

    def test_all_required_scripts_have_real_regular_bold_faces_and_sample_glyphs(self):
        report = fonts.language_report(PROJECT)
        self.assertEqual(len(report), 8)
        self.assertTrue(all(r['status'] == 'ready' for r in report.values()), report)

    def test_binding_bold_collection_face_is_idempotent_and_rejects_tampering(self):
        text = '한국어 테스트'
        asset = fonts.bind(self.run, 'Apple SD Gothic Neo', True, text)
        self.assertEqual(asset, fonts.bind(self.run, 'Apple SD Gothic Neo', True, text))
        with typography._font_modules().TTFont(self.run / asset['path']) as face:
            self.assertEqual(face['name'].getDebugName(1), 'Apple SD Gothic Neo')
            self.assertEqual(face['OS/2'].usWeightClass, 700)
        (self.run / asset['path']).write_bytes(b'tampered font')
        with self.assertRaisesRegex(WorkflowError, 'changed'):
            fonts.bind(self.run, 'Apple SD Gothic Neo', True, text)

    def test_missing_glyph_is_rejected_before_exporting_or_measuring(self):
        with self.assertRaisesRegex(WorkflowError, 'missing glyphs'):
            fonts.bind(self.run, 'Arial', False, '한글')
        with self.assertRaisesRegex(WorkflowError, 'missing glyphs'):
            layout.font_size({'target_text': '한글', 'font_family': 'Arial', 'bbox': [0, 0, 300, 80], 'fit_text': True})

    def test_measuring_uses_the_exact_bold_face_index(self):
        from PIL import ImageFont
        original = ImageFont.truetype
        calls = []
        def load(*args, **kwargs):
            calls.append(kwargs.get('index'))
            return original(*args, **kwargs)
        with patch('PIL.ImageFont.truetype', side_effect=load):
            layout.font_size({'target_text': '한국어', 'font_family': 'Apple SD Gothic Neo',
                              'bbox': [0, 0, 300, 80], 'font_size': 32, 'bold': True, 'fit_text': True})
        self.assertTrue(calls)
        self.assertEqual(set(calls), {6})

    def test_korean_real_bold_font_is_accepted_by_motion_preflight(self):
        asset = fonts.bind(self.run, 'Apple SD Gothic Neo', True, '지금 시작')
        item = {'id': 'title', 'start': 0, 'end': .4, 'bbox': [10, 10, 600, 150],
                'target_text': '지금 시작', 'action': 'model_edit', 'display': {'font_asset': asset, 'bold': True,
                'font_size': 32, 'motion': {'kind': 'title', 'effect': 'none'}}}
        props, _ = typography._prepare(self.run, {'start': 0, 'end': .4}, [item],
                                        {'width': 640, 'height': 180}, self.run / 'outputs/motion')
        self.assertTrue(props['blocks'][0]['bold'])

    def test_real_ffmpeg_uses_language_specific_native_families_without_fallback(self):
        from PIL import Image
        source = self.root / 'plate.mp4'
        media.ffmpeg(['-f', 'lavfi', '-i', 'color=black:s=640x180:r=30:d=0.3', '-an', '-c:v', 'libx264', source])
        for locale, sample in fonts.policy()['samples'].items():
            family = fonts.default_family(sample, None if locale == 'latin' else locale)
            item = {'id': 'label', 'source_text': 'fixture', 'target_text': sample, 'start': 0, 'end': .3,
                    'bbox': [5, 10, 630, 150], 'action': 'model_edit',
                    'display': {'font_family': family, 'font_size': 28, 'bold': True, 'outline': 0}}
            from video_localizer.compositor import text
            directory = self.root / locale
            output = text(source, {'start': 0, 'end': .3}, [item], {'width': 640, 'height': 180}, directory)
            image = directory / 'frame.png'
            media.ffmpeg(['-i', output, '-frames:v', '1', image])
            self.assertGreater(Image.open(image).convert('L').getextrema()[1], 100)
            self.assertIn('\\fn' + family, (directory / 'tracked.ass').read_text(encoding='utf-8-sig'))
            diagnostic = media.command(['ffmpeg', '-hide_banner', '-loglevel', 'verbose', '-i', source,
                                       '-vf', media.ass_filter('tracked.ass', directory / 'fonts'), '-t', '0.1', '-f', 'null', '-'], cwd=directory)
            self.assertNotIn('failed to find any fallback', diagnostic.stderr.lower())
            self.assertNotIn('Glyph 0x', diagnostic.stderr)


if __name__ == '__main__':
    unittest.main()
