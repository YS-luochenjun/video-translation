import tempfile
import unittest
from pathlib import Path

from video_localizer.common import WorkflowError, file_hash, write_json
from video_localizer.model_tasks import packet


class GeminiTtsSpeakerLimitTests(unittest.TestCase):
    def test_pro_tts_rejects_three_roles_before_dispatch_or_inventory_processing(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / 'runs/fixture'
            source = run / 'inputs/source.mp4'
            source.parent.mkdir(parents=True)
            source.write_bytes(b'fixture source')
            digest = file_hash(source)
            write_json(run / 'run.json', {'source': 'inputs/source.mp4', 'source_sha256': digest})
            write_json(run / 'inputs/tts.json', {
                'source_sha256': digest, 'purpose': 'Observed two-speaker provider limit',
                'estimated_credits': 1, 'speech_ids': ['a001'],
                'payload': {'model': 'google/gemini-2-5-pro-tts', 'input': {
                    'speakers': [{'speaker_id': f'Speaker {i}', 'voice_name': name}
                                 for i, name in enumerate(['Aoede', 'Puck', 'Kore'], 1)],
                    'dialogue_turns': [{'speaker_id': 'Speaker 1', 'text': 'Hello.'}]}}})
            with self.assertRaisesRegex(WorkflowError, 'one or two speakers'):
                packet(run, 'inputs/tts.json')
            self.assertFalse((run / 'jobs').exists())


if __name__ == '__main__':
    unittest.main()
