import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from video_localizer import local_tts
from video_localizer.common import WorkflowError, file_hash, object_hash, read_json, write_json


class LocalTtsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.run = self.root / 'runs/fixture'
        (self.run / 'inputs').mkdir(parents=True)
        (self.run / 'inputs/source.bin').write_bytes(b'source')
        write_json(self.run / 'run.json', {'source': 'inputs/source.bin',
                   'source_sha256': file_hash(self.run / 'inputs/source.bin')})
        write_json(self.run / 'inputs/request.json', {'target_language': 'es'})
        self.inventory = {'speech_segments': [{'id': 'sp1', 'target_text': 'Hola'},
                                              {'id': 'sp2', 'target_text': 'Adios'}]}
        write_json(self.run / 'analysis/inventory.json', self.inventory)
        self.directory = self.root / '.runtime/models/tts/fixture'
        (self.directory / 'espeak-ng-data').mkdir(parents=True)
        for name in ['model.onnx', 'tokens.txt', 'espeak-ng-data/voice']:
            (self.directory / name).write_bytes(name.encode())
        self.voice = {'directory': '.runtime/models/tts/fixture', 'locales': ['es'],
                      'model': 'model.onnx', 'tokens': 'tokens.txt', 'data': 'espeak-ng-data',
                      'files': {p.relative_to(self.directory).as_posix(): file_hash(p)
                                for p in self.directory.rglob('*') if p.is_file()},
                      'license_note': 'Synthetic test fixture'}
        write_json(self.root / 'config/local-voices.json', {'voices': {'fixture': self.voice}})
        self.spec = {'voice': 'fixture', 'speed': 1.0, 'speaker_id': 0}
        write_json(self.run / 'inputs/voice.json', self.spec)
        self.calls = []

    def synthesize(self, text, output, voice, speed, speaker):
        self.calls.append(text)
        with wave.open(str(output), 'wb') as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(16000)
            f.writeframes(b'\x01\x00' * 1600)

    def seed_legacy(self):
        for speech in self.inventory['speech_segments']:
            signature = {'source_sha256': file_hash(self.run / 'inputs/source.bin'),
                         'target_language': 'es', 'voice': 'fixture', 'assets': self.voice['files'],
                         'engine': 'fixture-v1', 'model': 'model.onnx', 'tokens': 'tokens.txt',
                         'data': 'espeak-ng-data', 'implementation': 'historical-code-hash',
                         'text': speech['target_text'], 'speed': 1.0, 'speaker_id': 0}
            directory = self.run / 'outputs/local-tts' / object_hash(signature)
            directory.mkdir(parents=True)
            output = directory / 'voice.wav'
            self.synthesize(speech['target_text'], output, None, 1, 0)
            write_json(directory / 'provenance.json', {'signature': signature,
                       'output': {'path': output.relative_to(self.run).as_posix(), 'sha256': file_hash(output)}})
        self.calls.clear()

    def generate(self):
        with patch.object(local_tts, '_engine_version', return_value='fixture-v1'):
            return local_tts.generate(self.run, 'inputs/voice.json', code_root=self.root)

    def test_existing_takes_reuse_but_new_or_changed_copy_requires_gemini(self):
        with self.assertRaisesRegex(WorkflowError, 'Gemini TTS'):
            self.generate()
        self.seed_legacy()
        result = self.generate()
        self.assertTrue(all(row['reused'] for row in result['lines']))
        self.assertFalse(result['approved_for_reuse'])
        self.inventory['speech_segments'][0]['target_text'] = 'Hola de nuevo'
        write_json(self.run / 'analysis/inventory.json', self.inventory)
        with self.assertRaisesRegex(WorkflowError, 'Gemini TTS'):
            self.generate()
        self.assertEqual(self.calls, [])

    def test_speed_and_model_changes_cannot_reuse_old_takes(self):
        self.seed_legacy()
        self.spec['speed'] = 1.08
        write_json(self.run / 'inputs/voice.json', self.spec)
        with self.assertRaisesRegex(WorkflowError, 'Gemini TTS'):
            self.generate()
        (self.directory / 'model.onnx').write_bytes(b'tampered model')
        with self.assertRaisesRegex(WorkflowError, 'Voice asset changed'):
            self.generate()

    def test_tampered_or_missing_output_cannot_reuse_or_regenerate(self):
        self.seed_legacy()
        first = self.generate()
        output = self.run / first['lines'][0]['voice']['path']
        output.write_bytes(b'bad')
        with self.assertRaisesRegex(WorkflowError, 'Voice checkpoint changed'):
            self.generate()
        output.unlink()
        with self.assertRaisesRegex(WorkflowError, 'Gemini TTS'):
            self.generate()

    def test_partial_wav_without_receipt_cannot_reuse_or_regenerate(self):
        self.seed_legacy()
        first = self.generate()
        (self.run / first['lines'][0]['voice']['path']).with_name('provenance.json').unlink()
        with self.assertRaisesRegex(WorkflowError, 'Gemini TTS'):
            self.generate()

    def test_language_speed_and_selection_are_validated(self):
        for changes in [{'speed': 0}, {'speed': True}, {'speech_ids': ['missing']}, {'speaker_id': -1}]:
            write_json(self.run / 'inputs/voice.json', {**self.spec, **changes})
            with self.assertRaises(WorkflowError):
                self.generate()
        write_json(self.run / 'inputs/voice.json', self.spec)
        write_json(self.run / 'inputs/request.json', {'target_language': 'ja'})
        with self.assertRaisesRegex(WorkflowError, 'locale'):
            self.generate()

    def test_missing_legacy_voice_assets_do_not_trigger_installation(self):
        self.seed_legacy()
        token = self.directory / 'tokens.txt'
        token.unlink()
        with self.assertRaisesRegex(WorkflowError, 'Voice asset changed or missing'):
            self.generate()
        self.assertFalse(token.exists())

    def test_engine_and_phoneme_changes_invalidate_or_reject(self):
        self.seed_legacy()
        with patch.object(local_tts, '_engine_version', return_value='fixture-v2'):
            with self.assertRaisesRegex(WorkflowError, 'Gemini TTS'):
                local_tts.generate(self.run, 'inputs/voice.json', code_root=self.root)
        (self.directory/'espeak-ng-data/voice').write_bytes(b'changed')
        with self.assertRaisesRegex(WorkflowError, 'Voice asset changed'):
            self.generate()
