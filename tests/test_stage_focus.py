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
