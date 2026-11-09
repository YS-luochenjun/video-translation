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
            self.assertLess(float(samples.max()),.151)
            self.assertGreater(float(samples.min()),.099)
            self.assertAlmostEqual(float(samples[-1,0]),.1,places=3)


if __name__=='__main__':unittest.main()
