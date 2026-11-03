"""Regressions for wrong scene-event windows and overlapping short captions.

Fixtures test diagnostics and bindings, not real speech or video acceptance.
"""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from video_localizer import cli, text_timing
from video_localizer.common import file_hash, object_hash, write_json


def caption(identity, start, end, box=None):
    return {'id': identity, 'source_text': 'source', 'target_text': identity,
            'start': 0, 'end': 10, 'source_interval': [0, 10],
            'text_role': 'speech_caption', 'action': 'translate',
            'bbox': box or [0, 0, 200, 60],
            'display': {'timed_fragments': [[start, end, identity]]}}


def kinds(report):
    return {r['kind'] for r in report['risks']}


class TimingDesignTests(unittest.TestCase):
    def test_source_erase_windows_do_not_create_false_caption_overlap(self):
        report = text_timing.design({'text_instances': [caption('a', 0, 1), caption('b', 1, 2)]})
        self.assertNotIn('simultaneous_text_regions_need_review', kinds(report))
        self.assertEqual(report['instances'][0]['clock'], 'actual_target_speech')

    def test_two_distinct_captions_collide_on_same_active_region(self):
        report = text_timing.design({'text_instances': [caption('a', 4.9, 5.8), caption('b', 5.1, 6.5)]})
        risk = next(x for x in report['risks'] if x['kind'] == 'simultaneous_text_regions_need_review')
        self.assertEqual(risk['ids'], ['a', 'b'])
        self.assertEqual(risk['intervals'], [[5.1, 5.8]])
        self.assertFalse(report['automatic_pass'])
        self.assertIn('not a proven visual collision', risk['scope'])

    def test_simultaneous_different_lanes_are_not_collisions(self):
        report = text_timing.design({'text_instances': [caption('a', 0, 1), caption('b', 0, 1, [0, 70, 200, 60])]})
        self.assertNotIn('simultaneous_text_regions_need_review', kinds(report))

    def test_target_display_box_used_instead_of_source_erase_box(self):
        items = [caption('a', 0, 1), caption('b', 0, 1)]
        items[1]['display']['bbox'] = [0, 70, 200, 60]
        self.assertNotIn('simultaneous_text_regions_need_review', kinds(text_timing.design({'text_instances': items})))

    def test_frozen_source_event_catches_early_cta_even_if_inventory_was_retimed(self):
        item = caption('cta', 0, 1)
        item.update(text_role='scene_text', start=12, end=15, source_interval=[12, 15], display={})
        report = text_timing.design({'text_instances': [item]}, {'cta': {'interval': [14, 15]}})
        self.assertIn('scene_event_timing_changed_without_reason', kinds(report))
        self.assertEqual(report['instances'][0]['source_interval'], [14, 15])
        self.assertEqual(report['instances'][0]['clock'], 'source_scene_event')

    def test_attributed_scene_timing_adaptation_is_not_forbidden(self):
        item = caption('cta', 0, 1)
        item.update(text_role='scene_text', start=12, end=15, display={},
                    style_treatment={'adaptations': {'timing': 'Source CTA is adapted to a longer target reading window; review actual cut.'}})
        report = text_timing.design({'text_instances': [item]}, {'cta': {'interval': [14, 15]}})
        self.assertNotIn('scene_event_timing_changed_without_reason', kinds(report))
        self.assertFalse(report['automatic_pass'])

    def test_missing_source_event_evidence_is_explicit(self):
        item = caption('title', 0, 1)
        item.update(text_role='scene_text', display={})
        item.pop('source_interval')
        self.assertIn('scene_source_timing_unfrozen', kinds(text_timing.design({'text_instances': [item]})))

    def test_motion_treatment_and_explicit_downgrade_remain_distinct(self):
        item = caption('a', 0, 1)
        item.update(source_style_id='s1', style_treatment={'route': 'typeset', 'adaptations': {}})
        styles = {'s1': {'motion': {'kind': 'complex', 'observation': 'Words bounce in and out'}}}
        self.assertIn('source_motion_has_no_target_treatment', kinds(text_timing.design({'text_instances': [item]}, source_styles=styles)))
        item['style_treatment']['adaptations']['motion'] = 'Bounded static fallback after actual renderer failure; disclose lost bounce.'
        self.assertNotIn('source_motion_has_no_target_treatment', kinds(text_timing.design({'text_instances': [item]}, source_styles=styles)))

    def test_static_source_does_not_force_new_animation(self):
        item = caption('a', 0, 1)
        item['source_style_id'] = 's1'
        report = text_timing.design({'text_instances': [item]}, source_styles={'s1': {'motion': {'kind': 'static'}}})
        self.assertNotIn('source_motion_has_no_target_treatment', kinds(report))

    def test_internal_unordered_fragments_and_invalid_intervals_are_reported(self):
        item = caption('a', 0, 1)
        item['display']['timed_fragments'] = [[1, 2, 'a'], [0, 1.5, 'b'], [3, float('nan'), 'c']]
        report = text_timing.design({'text_instances': [item]})
        self.assertIn('spoken_fragments_overlap_or_unordered', kinds(report))
        self.assertIn('invalid_target_interval', kinds(report))

    def test_unfinished_fragment_data_does_not_break_work_packet(self):
        item = caption('a', 0, 1)
        item['display']['timed_fragments'] = [[0]]
        self.assertIn('invalid_target_units', kinds(text_timing.design({'text_instances': [item]})))

    def test_preserved_text_and_removal_only_marks_do_not_create_false_collisions(self):
        a, b = caption('a', 0, 1), caption('b', 0, 1)
        a['action'] = 'preserve'
        b['target_text'] = ''
        self.assertEqual(text_timing.design({'text_instances': [a, b]})['instances'], [])


class TimingBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)/'runs/test'
        self.run.mkdir(parents=True)
        (self.run/'mix.wav').write_bytes(b'synthetic hashed audio only')
        self.inventory = {'source_sha256': 'source', 'text_instances': [caption('a', 0, 1)],
            'audio': {'has_speech': True, 'strategy': 'replace', 'replacement_path': 'mix.wav'},
            'speech_segments': [{'id': 's1', 'target_text': 'a', 'caption_policy': 'verbatim', 'caption_ids': ['a']}]}
        self.inventory['text_instances'][0]['speech_id'] = 's1'
        self.alignment = {'schema_version': 1, 'source_sha256': 'source', 'target_language': 'ja',
            'status': 'reviewed', 'reviewer': 'Synthetic fixture, not real listening', 'method': 'asr_reviewed',
            'timeline': 'final_mix_seconds', 'audio': {'path': 'mix.wav', 'sha256': file_hash(self.run/'mix.wav')},
            'segments': [{'speech_id': 's1', 'units': [{'text': 'a', 'start': 0, 'end': 1}]}]}
        write_json(self.run/'inputs/request.json', {'target_language': 'ja'})
        write_json(self.run/'analysis/media.json', {'duration': 10})
        write_json(self.run/'analysis/alignment.json', self.alignment)
        self.inventory['caption_alignment'] = {'path': 'analysis/alignment.json', 'sha256': file_hash(self.run/'analysis/alignment.json')}
        write_json(self.run/'analysis/inventory.json', self.inventory)

    def test_valid_alignment_is_bound_without_claiming_actual_quality(self):
        report = text_timing.diagnose(self.run)
        self.assertNotIn('actual_target_audio_alignment_unverified', kinds(report))
        self.assertFalse(report['automatic_pass'])
        self.assertEqual(report['paid_calls'], 0)

    def test_changed_mixed_audio_invalidates_alignment_even_with_same_filename(self):
        (self.run/'mix.wav').write_bytes(b'changed mix')
        self.assertIn('actual_target_audio_alignment_unverified', kinds(text_timing.diagnose(self.run)))

    def test_stale_caption_fragments_are_exposed(self):
        self.inventory['text_instances'][0]['display']['timed_fragments'][0][1] = 3
        report = text_timing.diagnose(self.run, self.inventory)
        self.assertIn('target_timing_differs_from_reviewed_alignment', kinds(report))

    def test_missing_actual_alignment_is_not_satisfied_by_planned_units(self):
        self.inventory.pop('caption_alignment')
        self.assertIn('actual_target_audio_alignment_unverified', kinds(text_timing.diagnose(self.run, self.inventory)))

    def test_foreign_or_tampered_source_snapshot_is_reported(self):
        basis = {'source_sha256': 'other-source', 'source_bindings': {}, 'styles': []}
        p = self.run/'analysis/source-styles'/object_hash(basis)/'snapshot.json'
        write_json(p, {'basis': basis})
        self.inventory['source_style_snapshot'] = {'path': p.relative_to(self.run).as_posix(), 'sha256': file_hash(p)}
        self.assertIn('source_timing_snapshot_unverified', kinds(text_timing.diagnose(self.run, self.inventory)))

    def test_bound_original_scene_interval_survives_target_inventory_edits(self):
        item = self.inventory['text_instances'][0]
        item.update(text_role='scene_text', display={}, start=0, end=5, source_interval=[0, 5])
        basis = {'source_sha256': 'source', 'source_bindings': {'a': {'interval': [3, 5]}}, 'styles': []}
        p = self.run/'analysis/source-styles'/object_hash(basis)/'snapshot.json'
        write_json(p, {'basis': basis})
        self.inventory['source_style_snapshot'] = {'path': p.relative_to(self.run).as_posix(), 'sha256': file_hash(p)}
        self.assertIn('scene_event_timing_changed_without_reason', kinds(text_timing.diagnose(self.run, self.inventory)))

    def test_cli_is_read_only_and_dispatches_real_diagnostics(self):
        before = {p.relative_to(self.run).as_posix(): file_hash(p) for p in self.run.rglob('*') if p.is_file()}
        with patch.object(cli, 'get_run', return_value=self.run), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(['text-timing', 'test']), 0)
        report = json.loads(output.getvalue())
        self.assertFalse(report['automatic_pass'])
        self.assertEqual(report['run'], 'test')
        after = {p.relative_to(self.run).as_posix(): file_hash(p) for p in self.run.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
