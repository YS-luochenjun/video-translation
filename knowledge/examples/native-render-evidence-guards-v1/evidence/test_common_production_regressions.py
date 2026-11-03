"""Actual font/libass geometry and synthetic report contradictions, not AV acceptance."""
import copy
from pathlib import Path
import shutil
import tempfile
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))

from video_localizer import audio, compositor, fonts, layout, media, restoration_probes
from video_localizer.common import CODE_ROOT, WorkflowError, file_hash, write_json, read_json

FONT = next((p for p in (CODE_ROOT/'assets/fonts/arial.ttf', Path('/System/Library/Fonts/Supplemental/Arial.ttf')) if p.is_file()), None)
BOLD = next((p for p in (CODE_ROOT/'assets/fonts/arialbd.ttf', Path('/System/Library/Fonts/Supplemental/Arial Bold.ttf')) if p.is_file()), None)


class SpeechContradictionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)
        self.candidate = {'sha256': 'a'*64}
        self.path = self.run/'review'/('a'*12)/'audio-model-review.json'
        self.report = {'source_sha256': 'b'*64, 'video_sha256': 'a'*64, 'analysis': {
            'background_music': {'same_track': True}, 'sound_effects': {'preserved': True},
            'dialogue_translation': {'complete': True}, 'sync': {'acceptable': True}}}
        self.inventory = {'audio': {'has_speech': True}, 'speech_segments': [{'target_text': 'Complete CTA'}]}

    def check(self):
        write_json(self.run/'analysis/inventory.json', self.inventory)
        write_json(self.path, self.report)
        captured = {'video_sha256': self.candidate['sha256'], 'files': {self.path.relative_to(self.run).as_posix(): file_hash(self.path)}}
        return audio.model_review_check(self.run, self.candidate, 'b'*64, captured)

    def test_complete_summary_cannot_overrule_reported_absent_required_speech(self):
        self.report['analysis']['has_speech'] = False
        self.assertIn('required_speech_reported_absent', self.check()['failures'])

    def test_empty_or_blank_transcript_does_not_establish_translated_speech(self):
        for value in ([], [{'source_text': '  '}], [{'speaker': 'female'}]):
            self.report['analysis']['speech_segments'] = value
            self.assertIn('required_speech_transcript_empty', self.check()['failures'])

    def test_malformed_transcript_is_not_silently_accepted(self):
        self.report['analysis']['speech_segments'] = 'present'
        self.assertIn('audio_model_transcript_invalid', self.check()['failures'])

    def test_different_segmentation_or_asr_spelling_is_not_auto_rejected(self):
        self.report['analysis']['speech_segments'] = [{'source_text': 'Actual differently grouped phrase'}]
        self.assertEqual(self.check()['decision'], 'pass')

    def test_legacy_report_without_speech_field_remains_readable(self):
        self.assertEqual(self.check()['decision'], 'pass')

    def test_silent_source_does_not_require_invented_narration(self):
        self.inventory = {'audio': {'has_speech': False}, 'speech_segments': []}
        self.report['analysis'].update(has_speech=False, speech_segments=[])
        self.assertEqual(self.check()['decision'], 'pass')


class NativeBoundaryGuardTests(unittest.TestCase):
    def test_one_frame_after_erase_interval_is_actually_selected(self):
        item = {'id': 'held-caption', 'start': .1, 'end': .3}
        frames = restoration_probes.sample_frames(item, [n/30 for n in range(15)])
        self.assertIn(2, frames)
        self.assertIn(9, frames)
        self.assertLessEqual(len(frames), 5)

    def test_final_real_frame_is_not_a_contact_sheet_padding_tile(self):
        item = {'id': 'cta', 'start': 0, 'end': 4/30}
        self.assertEqual(restoration_probes.sample_frames(item, [0, 1/30, 2/30, 3/30]), [0, 1, 3])

    def test_ghost_window_has_bounded_neighbor_samples(self):
        item = {'id': 'caption', 'start': 1, 'end': 2, 'source_ghost_interval': [3, 4]}
        frames = restoration_probes.sample_frames(item, [n/30 for n in range(180)])
        self.assertIn(29, frames)
        self.assertIn(120, frames)
        self.assertLessEqual(len(frames), 10)


@unittest.skipUnless(FONT and BOLD, 'Real regular/bold font files required')
class RenderedFontTests(unittest.TestCase):
    def setUp(self):
        temp_root = CODE_ROOT/'work/test-tmp'
        temp_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root/'runs/font-effects'
        self.run.mkdir(parents=True)

    def test_fit_includes_outermost_outline_and_shadow(self):
        item = {'target_text': 'MMMMMMMM', 'font_family': 'Arial', 'font_size': 48,
                'fit_text': True, 'bbox': [0,0,240,100], 'padding': 2, 'min_font_size': 16}
        plain = layout.font_size(item)
        item.update(outline=2, outline_layers=[{'width': 20}], shadow=4)
        self.assertLess(layout.font_size(item), plain)

    def test_effects_cannot_force_text_below_explicit_readable_minimum(self):
        item = {'target_text': 'MMMMMMMM', 'font_family': 'Arial', 'font_size': 40,
                'fit_text': True, 'bbox': [0,0,240,100], 'min_font_size': 40,
                'outline_layers': [{'width': 24}]}
        with self.assertRaisesRegex(WorkflowError, 'cannot fit'):
            layout.font_size(item)

    def test_distinct_weights_of_same_family_get_distinct_exact_ass_families(self):
        from video_localizer.typography import _font_modules
        heavy = self.root/'heavy.ttf'
        with _font_modules().TTFont(BOLD, recalcTimestamp=False) as font:
            font['OS/2'].usWeightClass = 900
            font.save(heavy)
        original_sha = file_hash(heavy)
        bound = [fonts.bind_file(self.run, p, 'Glyph') for p in (BOLD, heavy)]
        directory = self.run/'render'
        faces = [fonts.ass_asset(self.run, a, directory, 'Glyph', True, False) for a in bound]
        self.assertEqual(faces[0]['family'], faces[1]['family'])
        self.assertNotEqual(faces[0]['ass_family'], faces[1]['ass_family'])
        self.assertEqual([f['weight'] for f in faces], [700, 900])
        for face in faces:
            output = directory/'fonts'/(face['ass_family']+face['path'].suffix)
            with _font_modules().TTFont(output) as font:
                self.assertEqual(font['name'].getDebugName(1), face['ass_family'])
                self.assertEqual(font['OS/2'].usWeightClass, face['weight'])
                with _font_modules().TTFont(face['path']) as original:
                    self.assertEqual(font.getBestCmap(), original.getBestCmap())
        self.assertEqual(file_hash(heavy), original_sha)
        self.assertEqual(fonts.ass_asset(self.run, bound[0], directory, 'Glyph', True, False)['ass_family'], faces[0]['ass_family'])

    def test_motion_fallback_preserves_two_bound_faces_of_one_family(self):
        from video_localizer import typography
        a, b = [fonts.bind_file(self.run, p, 'Go') for p in (FONT, BOLD)]
        base = {'id': 'a', 'source_text': 'Go', 'target_text': 'Go', 'action': 'model_edit',
                'text_role': 'scene_text', 'start': 0, 'end': .3, 'bbox': [10,10,140,100]}
        items = []
        for n, asset in enumerate([a, b]):
            item = copy.deepcopy(base)
            item.update(id=str(n), bbox=[10+160*n,10,140,100])
            item['display'] = {'font_asset':asset, 'bold':bool(n), 'font_size':24,
                               'motion': {'kind':'title','effect':'none'}}
            items.append(item)
        props, _ = typography._prepare(self.run, {'start':0,'end':.3}, items,
                                       {'width':320,'height':120}, self.run/'motion')
        self.assertEqual(len(props['fonts']), 2)
        self.assertNotEqual(props['blocks'][0]['assFamily'], props['blocks'][1]['assFamily'])
        self.assertEqual([b['bold'] for b in props['blocks']], [False, True])

    def test_tampered_render_font_is_detected_instead_of_silent_fallback(self):
        asset = fonts.bind_file(self.run, FONT, 'Glyph')
        d = self.run/'render'
        f = fonts.ass_asset(self.run, asset, d, 'Glyph', False, False)
        (d/'fonts'/(f['ass_family']+f['path'].suffix)).write_bytes(b'changed')
        with self.assertRaisesRegex(WorkflowError, 'changed'):
            fonts.ass_asset(self.run, asset, d, 'Glyph', False, False)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'Actual libass required')
    def test_actual_libass_ink_with_thick_outline_stays_inside_reviewed_box(self):
        from PIL import Image
        item = {'id': 't', 'source_text': 'source', 'target_text': 'MMMMMMMM',
                'start': 0, 'end': .3, 'bbox': [10,10,300,100], 'action': 'model_edit',
                'display': {'font_family': 'Arial', 'bold': True, 'font_size': 52,
                            'outline': 2, 'outline_color': '#FFFFFF',
                            'outline_layers': [{'width': 20, 'color': '#FFFFFF'}]}}
        d = self.run/'actual';meta = {'width':320,'height':120}
        events = compositor.text_events({'start':0,'end':.3}, [item], meta, d)
        (d/'test.ass').write_text('\n'.join(compositor.header(meta)+events+['']), encoding='utf-8-sig')
        media.ffmpeg(['-f','lavfi','-i','color=black:s=320x120:r=30:d=0.1',
                      '-vf',media.ass_filter('test.ass',d/'fonts'),'-frames:v','1', d/'native.png'], cwd=d)
        image = Image.open(d/'native.png').convert('L')
        box = image.point(lambda n: 255 if n>32 else 0).getbbox()
        self.assertIsNotNone(box)
        self.assertTrue(10 < box[0] < box[2] < 310, box)
        self.assertTrue(10 < box[1] < box[3] < 110, box)
