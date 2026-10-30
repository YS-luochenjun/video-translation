import copy
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_localizer import fonts, media, style_layers, surface
from video_localizer.common import CODE_ROOT, WorkflowError, file_hash, read_json, write_json

FONT = next((p for p in [Path('/System/Library/Fonts/Supplemental/Arial.ttf'),
    CODE_ROOT / 'assets/fonts/arial.ttf', Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')] if p.is_file()), None)


@unittest.skipUnless(FONT and shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Real font and FFmpeg required')
class StyleLayerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(dir=CODE_ROOT / 'work/test-tmp')
        cls.source = Path(cls.temp.name) / 'source.mp4'
        media.ffmpeg(['-f', 'lavfi', '-i', 'color=c=teal:s=320x180:r=24:d=1',
                      '-c:v', 'libx264', '-pix_fmt', 'yuv420p', cls.source])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=CODE_ROOT / 'work/test-tmp')
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name) / 'runs/fixture'
        (self.run / 'inputs').mkdir(parents=True)
        shutil.copyfile(self.source, self.run / 'inputs/source.mp4')
        self.sha = file_hash(self.run / 'inputs/source.mp4')
        write_json(self.run / 'run.json', {'source': 'inputs/source.mp4', 'source_sha256': self.sha})
        write_json(self.run / 'inputs/request.json', {'target_language': 'en'})
        self.font = fonts.bind_file(self.run, FONT, 'Hello world')
        self.item = {'id': 't1', 'start': 0, 'end': 1, 'source_text': 'Original', 'target_text': 'Hello world',
            'text_role': 'speech_caption', 'speech_id': 'a1',
            'bbox': [20, 20, 280, 70], 'action': 'model_edit',
            'style_treatment': {'route': 'typeset'},
            'display': {'font_asset': self.font, 'font_size': 32, 'min_font_size': 20, 'bold': False,
                'bbox': [20, 20, 280, 70], 'outline': 1, 'color': '#FFFFFF',
                'timed_fragments': [[.1, .4, 'Hello'], [.5, .9, 'world']]}}
        self.inventory = {'source_sha256': self.sha, 'text_instances': [self.item],
            'shots': [{'id': 's1', 'start': 0, 'end': 1}]}
        self.spec = {'source_sha256': self.sha, 'shot': 's1', 'reason': 'Explicit synthetic typography integration',
                     'typeset_ids': ['t1'], 'artwork': []}
        self.save()

    def save(self):
        write_json(self.run / 'analysis/inventory.json', self.inventory)
        write_json(self.run / 'inputs/style-layer.json', self.spec)

    def render(self, apply=False):
        self.save()
        return style_layers.render(self.run, 'inputs/style-layer.json', apply)

    def test_native_timing_alpha_phrase_switch_and_idempotent_apply(self):
        from PIL import Image
        result = self.render(apply=True)
        self.assertEqual(result['native_frames'], 24)
        self.assertFalse(result['automatic_pass'])
        self.assertFalse(result['reused'])
        inv = read_json(self.run / 'analysis/inventory.json')
        self.assertEqual(inv['shots'][0]['surface_typography'], result['asset'])
        surface.verify(self.run, result['asset'], self.sha, 'en', inv['text_instances'])
        layer = self.run / result['asset']['path']
        pictures = []
        for position in (0, .2, .7):
            path = self.run / f'frame-{position}.png'
            media.ffmpeg(['-ss', position, '-i', layer, '-frames:v', '1', path])
            image = Image.open(path).convert('RGBA')
            self.assertEqual(image.getpixel((0, 179))[3], 0)
            pictures.append(image)
        self.assertIsNone(pictures[0].getbbox())
        self.assertIsNotNone(pictures[1].getbbox())
        self.assertNotEqual(pictures[1].tobytes(), pictures[2].tobytes())
        before = next((self.run / 'inputs/style-layers').glob('*-before.json')).read_bytes()
        with patch.object(media, 'ffmpeg', side_effect=AssertionError('Unchanged layer must reuse encoding')):
            again = style_layers.render(self.run, 'inputs/style-layer.json', apply=True)
        self.assertTrue(again['reused'])
        self.assertEqual(again['asset'], result['asset'])
        self.assertEqual(next((self.run / 'inputs/style-layers').glob('*-before.json')).read_bytes(), before)

    def test_missing_phrase_and_protected_subject_block_before_encoding(self):
        self.item['display']['timed_fragments'].pop()
        with self.assertRaisesRegex(WorkflowError, 'complete finalized copy'):
            self.render()
        self.item['display']['timed_fragments'].append([.5, .9, 'world'])
        self.item['protected_regions'] = [[20, 20, 20, 20]]
        with self.assertRaisesRegex(WorkflowError, 'protected content'):
            self.render()

    def test_art_asset_pop_is_batched_and_exact_copy_and_transparency_are_required(self):
        from PIL import Image, ImageDraw
        image = Image.new('RGBA', (120, 40))
        ImageDraw.Draw(image).rectangle([10, 5, 110, 35], fill='yellow')
        path = self.run / 'inputs/synthetic-art.png'; image.save(path)
        art = {'id': 'a1', 'source_text': 'Synthetic CTA', 'target_text': 'CTA', 'start': .2, 'end': 1,
               'bbox': [100, 110, 120, 40], 'action': 'model_edit',
               'display': {'bbox': [100, 110, 120, 40]}, 'style_treatment': {'route': 'imagegen_asset'}}
        self.inventory['text_instances'].append(art)
        self.spec['artwork'] = [{'instance_id': 'a1', 'asset': {'path': 'inputs/synthetic-art.png', 'sha256': file_hash(path)},
            'text_checked': 'CTA', 'observed_by': 'Synthetic geometric fixture, NOT ImageGen or semantic artwork proof',
            'motion': {'kind': 'pop', 'entrance_seconds': .1, 'initial_scale': .8, 'pulse': .01},
            'motion_reason': 'Known fixture scale test'}]
        self.assertEqual(self.render()['native_frames'], 24)
        self.spec['artwork'][0]['text_checked'] = 'Wrong'
        with self.assertRaisesRegex(WorkflowError, 'exact-copy'):
            self.render()
        self.spec['artwork'][0]['text_checked'] = 'CTA'
        Image.new('RGBA', (120, 40), 'yellow').save(path)
        self.spec['artwork'][0]['asset']['sha256'] = file_hash(path)
        with self.assertRaisesRegex(WorkflowError, 'transparency'):
            self.render()

    def test_tampered_layer_is_not_silently_reused(self):
        result = self.render()
        (self.run / result['asset']['path']).write_bytes(b'synthetic tampering')
        with self.assertRaisesRegex(WorkflowError, 'video changed'):
            self.render()

    def test_timed_subject_avoidance_uses_existing_boxes_without_changing_source_erasure(self):
        from PIL import Image
        original = copy.deepcopy(self.item['bbox'])
        self.item['trajectory'] = [{'time': 0, 'bbox': original}, {'time': .5, 'bbox': [20, 110, 280, 60]}]
        self.item['style_treatment']['adaptations'] = {'layout': 'Synthetic closeup subject requires the second phrase lower'}
        result = self.render(apply=True)
        updated = read_json(self.run / 'analysis/inventory.json')['text_instances'][0]
        self.assertEqual(updated['bbox'], original)
        layer = self.run / result['asset']['path']
        image = self.run / 'lower-phrase.png'
        media.ffmpeg(['-ss', .7, '-i', layer, '-frames:v', '1', image])
        self.assertGreater(Image.open(image).getbbox()[1], 100)
