"""Synthetic media regressions: fast checkboxes must not bypass common AV gates."""
import copy
import shutil
import tempfile
import unittest
from pathlib import Path

from video_localizer import captions, fast_delivery, media
from video_localizer.common import file_hash, object_hash, read_json, write_json

PROJECT = Path(__file__).resolve().parents[1]
TEMP = PROJECT / 'work/test-tmp'
TEMP.mkdir(parents=True, exist_ok=True)


class FastAudioQualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / 'runs/fixture'
        self.run.mkdir(parents=True)
        for name in ('fast-delivery.json', 'quality.json'):
            target = self.root / 'config' / name
            target.parent.mkdir(exist_ok=True)
            shutil.copyfile(PROJECT / 'config' / name, target)
        source = self.run / 'source.mp4'
        media.ffmpeg(['-f', 'lavfi', '-i', 'color=c=blue:s=320x240:r=30:d=2',
                      '-f', 'lavfi', '-i', 'sine=frequency=330:sample_rate=48000:duration=2',
                      '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', source])
        shutil.copyfile(source, self.run / 'localized.mp4')
        digest = file_hash(source)
        write_json(self.run / 'run.json', {'source': 'source.mp4', 'source_sha256': digest})
        write_json(self.run / 'inputs/request.json', {'delivery_mode': 'fast', 'target_language': 'es'})
        self.inventory = {'source_sha256': digest,
            'audio': {'has_speech': True, 'strategy': 'replace', 'replacement_path': 'mix.wav'},
            'text_instances': [{'id': 't001', 'text_role': 'speech_caption', 'speech_id': 'a001',
                'action': 'model_edit', 'target_text': 'Hola', 'start': .2, 'end': .8}],
            'speech_segments': [{'id': 'a001', 'target_text': 'Hola',
                'caption_policy': 'verbatim', 'caption_ids': ['t001']}]}
        # This tone/blue-frame fixture supplies only known contract annotations.
        # No actual speech, text recognition or real-video acceptance is claimed.
        write_json(self.run / 'analysis/inventory.json', self.inventory)
        write_json(self.run / 'analysis/media.json', media.probe(source))
        output = {'path': 'localized.mp4', 'sha256': digest}
        write_json(self.run / 'inputs/recipe.json', {'source_sha256': digest, 'output': output, 'assets': []})
        self.plan = {'mode': 'fast', 'source_sha256': digest,
            'request_sha256': file_hash(self.run / 'inputs/request.json'),
            'inventory_sha256': file_hash(self.run / 'analysis/inventory.json'),
            'policy_sha256': file_hash(self.root / 'config/fast-delivery.json'),
            'assets': [{'path': 'inputs/recipe.json', 'sha256': file_hash(self.run / 'inputs/recipe.json')}],
            'segments': [], 'caption_contract': captions.contract(self.inventory)}
        self.plan['id'] = object_hash(self.plan)[:16]
        write_json(self.run / 'plan.json', self.plan)
        self.candidate = {**output, 'plan_id': self.plan['id'], 'recipe': 'inputs/recipe.json'}
        write_json(self.run / 'outputs/candidate.json', self.candidate)
        self.directory = self.run / 'review' / digest[:12]
        self.directory.mkdir(parents=True)
        wav, frame = self.directory / 'audio.wav', self.directory / 'caption-t001-000-1.jpg'
        media.ffmpeg(['-i', source, '-vn', '-ac', '1', '-ar', '16000', wav])
        media.ffmpeg(['-ss', '0.2', '-i', source, '-frames:v', '1', frame])
        self.audio = {'path': wav.relative_to(self.run).as_posix(), 'sha256': file_hash(wav)}
        self.frame = {'path': frame.relative_to(self.run).as_posix(), 'sha256': file_hash(frame)}
        self.report = captions.review_template(self.run, self.candidate, self.inventory, self.audio)
        evidence = [self.audio['path'], self.frame['path']]
        self.report.update(reviewer='synthetic fixture', method='known synthetic annotations only',
                           decision='pass', evidence=evidence)
        for row in self.report['instances']:
            row.update(audio_units=copy.deepcopy(row['planned_units']), visual_units=copy.deepcopy(row['planned_units']),
                       decision='pass', method='known synthetic annotations only', evidence=evidence)
        write_json(self.directory / 'caption-sync.json', self.report)
        self.model = {'source_sha256': digest, 'video_sha256': digest,
            'analysis': {'background_music': {'same_track': True}, 'sound_effects': {'preserved': True},
                'dialogue_translation': {'complete': True}, 'sync': {'acceptable': True},
                'foreign_speech_remaining': [], 'uncertain_intervals': []}}
        checks = read_json(self.root / 'config/fast-delivery.json')['review_checks']
        write_json(self.run / 'review/fast-review.json', {'video_sha256': digest, 'plan_id': self.plan['id'],
            'reviewer': 'synthetic fixture', 'method': 'known fixture, not real ad acceptance',
            'covered_text_ids': ['t001'], 'covered_speech_ids': ['a001'],
            'checks': {key: {'decision': 'pass', 'observation': 'Synthetic contract annotation',
                            'evidence': [self.audio, self.frame]} for key in checks},
            'visual_finish': {'score': 3, 'normal_speed_observation': 'Known blue-frame fixture',
                              'evidence': [self.frame], 'defects': []}})
        self.capture()

    def capture(self):
        write_json(self.run / 'review/capture.json', {'video_sha256': self.candidate['sha256'],
            'files': {p.relative_to(self.run).as_posix(): file_hash(p)
                      for p in self.directory.iterdir() if p.is_file()}})

    def quality(self):
        return fast_delivery.quality(self.run)

    def test_complete_fixture_passes_without_requesting_a_model(self):
        result = self.quality()
        self.assertEqual(result['decision'], 'pass', result)
        self.assertEqual(result['caption_check']['decision'], 'pass')
        self.assertEqual(result['audio_model_check']['decision'], 'not_requested')
        self.assertFalse((self.run / 'jobs').exists())

    def test_missing_caption_review_blocks_pass_checkboxes(self):
        (self.directory / 'caption-sync.json').unlink()
        self.capture()
        self.assertIn('caption_sync_review_missing', self.quality()['failures'])

    def test_measured_caption_delay_blocks_fast_quality(self):
        self.report['instances'][0]['audio_units'][0].update(start=.5, end=1.1)
        write_json(self.directory / 'caption-sync.json', self.report)
        self.capture()
        self.assertIn('caption_audio_out_of_sync:t001:0', self.quality()['failures'])

    def test_negative_and_uncertain_audio_review_cannot_be_overridden(self):
        self.model['analysis']['background_music']['same_track'] = False
        self.model['analysis']['uncertain_intervals'] = [{'start': 0, 'end': 1, 'reason': 'fixture'}]
        write_json(self.directory / 'audio-model-review.json', self.model)
        self.capture()
        result = self.quality()
        self.assertIn('background_music_not_verified_preserved', result['failures'])
        self.assertIn('audio_model_review_uncertain', result['failures'])

    def test_positive_model_review_must_be_bound_and_recaptured(self):
        write_json(self.directory / 'audio-model-review.json', self.model)
        self.assertIn('audio_model_review_not_captured_or_changed', self.quality()['failures'])
        self.capture()
        self.assertEqual(self.quality()['decision'], 'pass')
        self.model['video_sha256'] = 'd' * 64
        write_json(self.directory / 'audio-model-review.json', self.model)
        self.capture()
        self.assertIn('audio_model_review_binding_mismatch', self.quality()['failures'])

    def test_reported_character_voice_problem_blocks_fast_quality(self):
        self.model['analysis']['character_voices'] = {'distinct': True, 'consistent': False}
        write_json(self.directory / 'audio-model-review.json', self.model)
        self.capture()
        self.assertIn('character_voices_unverified', self.quality()['failures'])

    def test_malformed_audio_report_fails_closed(self):
        (self.directory / 'audio-model-review.json').write_text('{broken', encoding='utf-8')
        self.capture()
        self.assertIn('audio_model_review_invalid', self.quality()['failures'])


if __name__ == '__main__':
    unittest.main()
