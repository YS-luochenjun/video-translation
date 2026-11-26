import unittest
from pathlib import Path

from video_localizer.stage_focus import focus


class StageFocusTests(unittest.TestCase):
    def test_outlined_cta_routes_to_edge_case_before_language_expansion(self):
        root = Path(__file__).resolve().parents[1]
        instance = dict(id='cta', start=3, end=4, bbox=[5, 8, 60, 12],
                        source_style_id='cta', display={'outline_layers': [{'width': 3}]})
        inventory = {'text_instances': [instance, dict(instance, id='brand', action='preserve')]}
        neutral = focus('neutral', inventory, root)
        self.assertEqual([i['id'] for i in neutral['inspect_intervals']], ['cta'])
        self.assertIn('key010-de-fade-envelope-v1', [c['id'] for c in neutral['similar_cases']])
        delivery = focus('delivery', inventory, root)
        self.assertEqual(delivery['inspect_intervals'], [])
        self.assertNotEqual(neutral['method'], delivery['method'])

    def test_audio_contracts_are_selected_for_speech_stages(self):
        root = Path(__file__).resolve().parents[1]
        inventory = {'speech_segments': [{'id': 'a001'}]}
        self.assertEqual(focus('translation', inventory, root)['audio_contracts'], [
            'agent/contracts/audio-voice-selection.md', 'agent/contracts/audio-mixing.md'])
        self.assertEqual(focus('neutral', inventory, root)['audio_contracts'], [])
        self.assertEqual(focus('review', {}, root)['audio_contracts'], [])
        self.assertIn('docs/source-typography-layout.md', focus('translation', inventory, root)['stage_contracts'])
        self.assertNotIn('agent/contracts/storage-execution.md', focus('translation', inventory, root)['stage_contracts'])
        for stage in ('source', 'translation', 'neutral', 'render', 'review', 'delivery'):
            for path in focus(stage, inventory, root)['stage_contracts']:
                self.assertTrue((root / path).is_file(), path)
