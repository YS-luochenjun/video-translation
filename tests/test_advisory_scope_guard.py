import unittest
from unittest.mock import patch
from video_localizer.knowledge_advisories import retrieve


class AdvisoryScopeGuardTests(unittest.TestCase):
    def test_unstructured_observation_scope_does_not_break_production_recall(self):
        rows = [{'record': {'scope': 'Exact previously rejected bytes only'},
                 'decision': None, 'scope': 'Exact previously rejected bytes only'}]
        with patch('video_localizer.knowledge_advisories.queue', return_value=rows):
            self.assertEqual(retrieve({'workflow': 'video-localization'}), [])
