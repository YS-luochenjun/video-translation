"""Reuse decoded timing facts without inheriting candidate evidence or approval."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_localizer import media, review_probes, visual_audit
from video_localizer.common import file_hash, read_json, write_json


class ReviewProbeClockReuseTests(unittest.TestCase):
    def test_new_candidate_reuses_source_clock_but_decodes_changed_movie(self):
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=project/'work/test-tmp') as temporary:
            run = Path(temporary)/'runs/clock-fixture'
            run.mkdir(parents=True)
            for name, color in [('source.mp4', 'blue'), ('after.mp4', 'yellow')]:
                media.ffmpeg(['-f', 'lavfi', '-i', f'color=c={color}:s=80x96:r=24:d=1',
                              '-c:v', 'libx264', '-pix_fmt', 'yuv420p', run/name])
            write_json(run/'run.json', {'source':'source.mp4','source_sha256':file_hash(run/'source.mp4')})
            write_json(run/'analysis/inventory.json', {'text_instances':[], 'shots':[]})
            candidate = {'path':'after.mp4','sha256':file_hash(run/'after.mp4'),'plan_id':'first'}
            first = review_probes.generate(run, candidate)
            media.ffmpeg(['-f', 'lavfi', '-i', 'color=c=red:s=80x96:r=24:d=1',
                          '-c:v', 'libx264', '-pix_fmt', 'yuv420p', run/'after.mp4'])
            candidate.update(sha256=file_hash(run/'after.mp4'), plan_id='second')
            with patch.object(visual_audit, '_timestamps', wraps=visual_audit._timestamps) as decode:
                second = review_probes.generate(run, candidate)
            self.assertEqual([call.args[0] for call in decode.call_args_list], [run/'after.mp4'])
            self.assertNotEqual(first['manifest'], second['manifest'])
            self.assertFalse(second['automatic_pass'])
            self.assertFalse(second['reused'])
            self.assertEqual(read_json(run/second['manifest'])['binding']['video_sha256'], candidate['sha256'])
