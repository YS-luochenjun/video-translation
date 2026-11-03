import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from video_localizer.knowledge_review import sources


class ReceiptArrayDiscoveryTests(unittest.TestCase):
    def test_raw_receipt_array_does_not_break_or_become_a_feedback_event(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            feedback = root / 'knowledge/local/feedback/rework'
            feedback.mkdir(parents=True)
            (feedback / 'uploaded-byte-verification.json').write_text(
                json.dumps([{'video_sha256': 'actual-video', 'verified': True}]))
            event = feedback / 'feedback.json'
            event.write_text(json.dumps({'user_quote': 'Please fix the missing captions',
                                         'scope': {'target_language': 'ja'}}))
            found = sources(root)
            self.assertEqual(found, {event.relative_to(root).as_posix(): event})


if __name__ == '__main__':
    unittest.main()
