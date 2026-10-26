import shutil
import tempfile
import unittest
from pathlib import Path

from video_localizer import audio, media
from video_localizer.common import ROOT


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class LongAudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(dir=ROOT/'work/test-tmp')
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.root=Path(cls.tmp.name)
        cls.source=cls.root/'source.wav'
        cls.dropout=cls.root/'late-dropout.wav'
        media.ffmpeg(['-f','lavfi','-i','anoisesrc=color=pink:sample_rate=16000:duration=200:seed=42',
            '-af','volume=0.15','-ac','1','-c:a','pcm_s16le',cls.source])
        media.ffmpeg(['-i',cls.source,'-af',"volume=0:enable='gte(t,190)'",'-c:a','pcm_s16le',cls.dropout])

    def test_full_duration_and_late_dropout_are_checked(self):
        report=audio.evaluate(self.source,self.dropout,{'strategy':'preserve'},200)
        self.assertAlmostEqual(report['candidate']['duration'],200,places=3)
        self.assertEqual(report['candidate']['measurement_scope'],'complete_decoded_audio')
        self.assertGreater(report['candidate']['windows'][-1]['start'],199)
        self.assertNotIn('audio_duration_mismatch',report['failures'])
        self.assertIn('audio_dropout',report['failures'])

    def test_audio_segment_after_old_181_second_boundary_is_available(self):
        target=audio.extract_track(self.source,self.root/'late-take.wav',185,10)
        report,_=audio.inspect(target)
        self.assertAlmostEqual(report['duration'],10,places=3)
        self.assertTrue(report['audible_signal'])
