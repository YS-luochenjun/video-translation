import unittest
from video_localizer.audio import explicit_review_scope
from video_localizer.common import WorkflowError


class AudioScopeTests(unittest.TestCase):
    def test_default_still_requires_all_speech(self):
        self.assertEqual(explicit_review_scope({}, {}), '')

    def test_narrowed_review_keeps_real_checks_and_requires_explicit_authority(self):
        request = {'production_scope': {'speech': 'advertising_narration_only'}}
        with self.assertRaises(WorkflowError):
            explicit_review_scope(request, {})
        request['scope_revision_authority'] = 'actual-user-event'
        request['production_scope']['authority_ref'] = 'actual-user-event'
        inv = {'scope_evidence': {'authority_ref': 'actual-user-event'},
               'speech_segments': [{'id': 'n', 'start': 0, 'end': 2}],
               'preserved_speech_segments': [{'id': 'g', 'start': 3, 'end': 4}]}
        prompt = explicit_review_scope(request, inv)
        self.assertIn('"id": "n"', prompt)
        self.assertIn('"id": "g"', prompt)
        self.assertIn('missing or clipped translated words still fail', prompt)
        self.assertIn('report actual uncertainty', prompt)
        inv['preserved_speech_segments'][0]['id'] = 'n'
        with self.assertRaises(WorkflowError):
            explicit_review_scope(request, inv)
