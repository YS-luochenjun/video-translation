"""Continuous dubbed narration must not resurrect original speech at joins/EOF."""
import json
import shutil
import tempfile
import types
import unittest
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import numpy as np
from video_localizer import local_audio
from video_localizer.common import file_hash


class ContinuousNarrationTest(unittest.TestCase):
    def test_fades_are_outside_source_removal_and_preserve_long_gaps(self):
        rate = 1000
        original = np.full((2000, 2), .4, dtype=np.float32)
        stem = np.full_like(original, .1)
        bed, blend, transitions = local_audio.background_mix(original, stem, rate, [(200, 500), (510, 800), (1300, 2000)])
        np.testing.assert_allclose(bed[200:800], stem[200:800])
        np.testing.assert_allclose(bed[1300:], stem[1300:])
        np.testing.assert_array_equal(bed[920:1180], original[920:1180])
        self.assertEqual(blend[199], 1)
        self.assertEqual(blend[800], 1)
        self.assertTrue(any(item['direction'] == 'keep_stem_short_gap' for item in transitions))

    def test_voice_limiter_does_not_attenuate_background(self):
        rate = 8000
        bed = np.full((rate, 2), .6, dtype=np.float32)
        voice = np.zeros_like(bed)
        voice[2000:4000] = .8
        result, envelope = local_audio.voice_only_limit(bed, voice, rate)
        self.assertLessEqual(float(np.max(np.abs(result))), .986)
        np.testing.assert_array_equal(result[:2000], bed[:2000])
        np.testing.assert_array_equal(result[4000:], bed[4000:])
        np.testing.assert_allclose(result - voice * envelope[:, None], bed, atol=1e-7)
        self.assertLess(float(envelope[3000]), .5)

    def test_preserves_loud_background_even_when_voice_has_no_headroom(self):
        bed = np.array([[.999, -.999], [.2, -.2]], dtype=np.float32)
        voice = np.array([[.5, -.5], [-.1, .1]], dtype=np.float32)
        result, envelope = local_audio.voice_only_limit(bed, voice, 1000)
        np.testing.assert_array_equal(result[0], bed[0])
        self.assertEqual(envelope[0], 0)

    def test_balance_raises_masked_voice_with_bounded_smooth_music_duck(self):
        rate = 8000
        time = np.arange(rate * 2) / rate
        bed = np.repeat((.25 * np.sin(2 * np.pi * 180 * time))[:, None], 2, axis=1)
        voice = np.zeros_like(bed)
        voice[rate//2:rate*3//2] = .08 * np.sin(2*np.pi*480*time[rate//2:rate*3//2])[:, None]
        result, _, report = local_audio.balance_voice(bed, voice, rate)
        self.assertLess(report['before']['voice_over_background_db'], 0)
        self.assertGreater(report['after']['voice_over_background_db'], 0)
        self.assertLessEqual(report['maximum_background_duck_db'], 4)
        self.assertLessEqual(report['automatic_voice_gain_db'], 9)
        self.assertLessEqual(float(np.max(np.abs(result))), .986)
        np.testing.assert_array_equal(result[:rate//4], bed[:rate//4])
        np.testing.assert_array_equal(result[-rate//4:], bed[-rate//4:])

    def test_balance_preserves_already_clear_voice_and_silent_background(self):
        rate = 8000
        bed = np.full((rate, 2), .02)
        voice = np.full_like(bed, .2)
        for background in (bed, np.zeros_like(bed)):
            mixed, _, report = local_audio.balance_voice(background, voice, rate)
            np.testing.assert_allclose(mixed, background + voice)
            self.assertEqual(report['automatic_voice_gain_db'], 0)
            self.assertEqual(report['maximum_background_duck_db'], 0)
            self.assertFalse(report['review_required'])

    def test_encoded_mix_contains_no_original_at_adjacent_join_or_eof(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp);(run/'inputs').mkdir();(run/'analysis').mkdir()
            source=run/'inputs/source.mp4';source.write_bytes(b'fixture source')
            original=run/'inputs/original.wav';bed=run/'inputs/bed.wav';voice=run/'inputs/voice.wav'
            rate=8000
            local_audio.save(original,np.full((rate*2,2),.4,dtype=np.float32),rate)
            local_audio.save(bed,np.full((rate*2,2),.1,dtype=np.float32),rate)
            local_audio.save(voice,np.full((rate//5,2),.05,dtype=np.float32),rate)
            lines=[{'id':f'a{i+1}','start':i,'end':i+1,'target_text':'fixture','voice':{'path':'inputs/voice.wav','sha256':file_hash(voice)}} for i in range(2)]
            plan={'source_sha256':file_hash(source),'background':{'path':'inputs/bed.wav','sha256':file_hash(bed)},'lines':lines}
            (run/'inputs/narration-plan.json').write_text(json.dumps(plan))
            (run/'analysis/inventory.json').write_text(json.dumps({'speech_segments':lines}))
            def encode(args):
                shutil.copyfile(args[args.index('-i')+1],args[-1])
            with patch.object(local_audio,'source_track',return_value=original),patch.object(local_audio.workflow,'source_path',return_value=source),patch.object(local_audio.captions,'validate_spoken_copy'),patch.object(local_audio.media,'command',return_value=types.SimpleNamespace(stdout='test encoder')),patch.object(local_audio.media,'ffmpeg',side_effect=encode):
                result=local_audio.mix.__wrapped__(run)
            samples,_=local_audio.pcm(run/result['path'])
            # The original .4 signal is distinguishable from bed .1 + dub .05.
            # Check the saved WAV, including every sample at joins and true EOF.
            self.assertLess(float(samples.max()),.35)
            self.assertGreater(float(samples.min()),.06)
            self.assertAlmostEqual(float(samples[-1,0]),.1,places=3)
            provenance = json.loads((run/result['path']).with_name('provenance.json').read_text())
            self.assertIn('source_level_baseline', provenance)
            self.assertTrue(all('speech_balance' in line for line in provenance['lines']))


if __name__=='__main__':unittest.main()
