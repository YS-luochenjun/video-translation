import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_localizer import render_cache, workflow, work_packet
from video_localizer.common import WorkflowError, file_hash, read_json, write_json

PROJECT = Path(__file__).resolve().parents[1]


class WorkflowOptimizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=PROJECT / 'work/test-tmp')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.run = self.root / 'runs/fixture'
        self.run.mkdir(parents=True)

    def test_all_masters_are_gated_before_rendering_first_segment(self):
        write_json(self.run / 'analysis/inventory.json', {'text_instances': []})
        write_json(self.run / 'analysis/media.json', {})
        plan = {'source_sha256': 'a'*64, 'segments': [
            {'id': 'one', 'route': 'local_overlay', 'instance_ids': []},
            {'id': 'two', 'route': 'prepared_video', 'instance_ids': [], 'prepared_video': {}}]}
        plan['segments'][1]['prepared_video'] = {'sha256': 'unapproved'}
        with patch.object(workflow, 'current_plan', return_value=plan), \
             patch('video_localizer.batches.gate'), \
             patch('video_localizer.prepared.verify_for_production', side_effect=WorkflowError('unapproved master')), \
             patch.object(workflow.media, 'render_local') as render:
            with self.assertRaisesRegex(WorkflowError, 'unapproved master'):
                workflow.render(self.run)
            render.assert_not_called()

    def test_segment_cache_reuses_visuals_across_audio_change_but_not_text_change(self):
        segment = {'id': 's1', 'route': 'local_overlay', 'start': 0, 'end': 1, 'instance_ids': ['t1']}
        items = {'text_instances': [{'id': 't1', 'start': 0, 'end': 1, 'target_text': 'hola'}]}
        plan = {'id': 'old', 'source_sha256': 'a'*64, 'audio_assets': [{'sha256': 'old audio'}]}
        meta = {'width': 160, 'height': 96, 'fps': 30, 'duration': 2}
        first = render_cache.signature(self.run, plan, segment, items, meta)
        self.assertIsNotNone(first)
        plan.update(id='new', audio_assets=[{'sha256': 'new audio'}])
        self.assertEqual(first, render_cache.signature(self.run, plan, segment, items, meta))
        later = copy.deepcopy(items)
        later['text_instances'].append({'id': 'other', 'start': 1.2, 'end': 2, 'target_text': 'elsewhere'})
        self.assertEqual(first, render_cache.signature(self.run, plan, segment, later, meta))
        # A retimed caption may cross this segment even if its source interval and
        # original shot assignment were elsewhere. The renderer sees actual time.
        later['text_instances'].append({'id': 'retimed', 'start': .8, 'end': 1.2,
                                       'source_interval': [1.2, 1.8], 'target_text': 'caption'})
        self.assertNotEqual(first, render_cache.signature(self.run, plan, segment, later, meta))
        items['text_instances'][0]['target_text'] = 'adios'
        self.assertNotEqual(first, render_cache.signature(self.run, plan, segment, items, meta))
        output = self.run / 'segment.mp4'; output.write_bytes(b'silent rendered fixture')
        render_cache.save(self.run, first, output)
        self.assertEqual(render_cache.restore(self.run, first), output)
        output.write_bytes(b'tampered')
        with self.assertRaisesRegex(WorkflowError, 'cache bytes changed'):
            render_cache.restore(self.run, first)

    def test_work_packet_preserves_ambiguous_jobs_and_does_not_approve(self):
        from video_localizer import cli
        source = self.run / 'source.mp4'; source.write_bytes(b'source')
        write_json(self.run / 'run.json', {'source': 'source.mp4', 'source_sha256': file_hash(source)})
        write_json(self.run / 'inputs/request.json', {'target_language': 'es'})
        write_json(self.run / 'analysis/inventory.json', {'coverage': {'visual': {'status': 'reviewed'}}})
        summary = {'state': 'planned', 'jobs': [{'id': 'job1', 'state': 'ambiguous', 'task_id': 'provider-task'}]}
        with patch.object(cli, 'status', return_value=summary):
            result = work_packet.build(self.run, 'translation')
        self.assertFalse(result['automatic_pass'])
        self.assertEqual(result['jobs'][0]['task_id'], 'provider-task')
        self.assertTrue(result['blockers'])
        self.assertEqual(result['pending_source_coverage'], ['speech', 'timeline'])
        self.assertFalse((self.run / 'review/review.json').exists())
