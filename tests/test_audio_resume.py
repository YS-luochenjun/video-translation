import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from video_localizer import asr, local_audio, media, model_tasks
from video_localizer.common import WorkflowError, file_hash, read_json, write_json

PROJECT = Path(__file__).resolve().parents[1]


class AudioResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=PROJECT / 'work/test-tmp')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.run = self.root / 'runs/fixture'
        (self.run / 'inputs').mkdir(parents=True)
        (self.run / 'inputs/source.wav').write_bytes(b'synthetic source')
        write_json(self.run / 'run.json', {'source': 'inputs/source.wav',
                   'source_sha256': file_hash(self.run / 'inputs/source.wav')})

    def test_source_audio_reused_across_same_requirement_only(self):
        def make_run(name, requirement):
            run = self.root / 'runs' / name
            source = run / 'inputs/source.wav'
            source.parent.mkdir(parents=True)
            source.write_bytes(b'synthetic source')
            write_json(run / 'run.json', {'source': 'inputs/source.wav', 'source_sha256': file_hash(source)})
            write_json(run / 'inputs/fireplay.json', {'requirement_id': requirement})
            return run

        first, second, third = (make_run(name, requirement) for name, requirement in
                                [('first', 'A'), ('second', 'A'), ('third', 'B')])
        with patch.object(media, 'command', return_value=SimpleNamespace(stdout='fixture ffmpeg')), \
             patch.object(media, 'ffmpeg', side_effect=lambda args: Path(args[-1]).write_bytes(b'decoded audio')) as decode:
            original = local_audio.source_track(first)
            copied = local_audio.source_track(second)
            self.assertEqual(decode.call_count, 1)
            self.assertEqual(original.read_bytes(), copied.read_bytes())
            original.unlink()
            self.assertEqual(local_audio.source_track(second).read_bytes(), b'decoded audio')
            local_audio.source_track(third)
            self.assertEqual(decode.call_count, 2)

    def test_separation_cache_copies_verified_stems(self):
        from importlib.util import spec_from_file_location, module_from_spec
        spec = spec_from_file_location('separation_fixture', PROJECT / 'bin/separate_local_audio.py')
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        origin = self.run
        output = origin / 'outputs/stems'
        output.mkdir(parents=True)
        stems = []
        for name in ('accompaniment', 'vocals'):
            path = output / (name + '.wav')
            path.write_bytes(name.encode())
            stems.append({'stem': name, 'path': path.relative_to(origin).as_posix(), 'sha256': file_hash(path)})
        signature = {'source_sha256': 'fixture'}
        receipt = output / 'provenance.json'
        write_json(receipt, {'signature': signature, 'stems': stems})
        index = self.root / 'state/cache.json'
        module.publish_index(origin, receipt, index)
        target = self.root / 'runs/second'
        destination = target / 'outputs/stems'
        destination.mkdir(parents=True)
        saved = module.reuse_stems(target, destination, signature, index, {'kind': 'local'})
        self.assertEqual(saved['reuse_origin']['run'], origin.name)
        self.assertEqual((destination / 'vocals.wav').read_bytes(), b'vocals')
        (output / 'vocals.wav').write_bytes(b'changed')
        self.assertIsNone(module.reuse_stems(target, destination, signature, index, {'kind': 'local'}))
        self.assertIsNone(module.reuse_stems(target, destination, signature, index,
                                            {'kind': 'fireplay', 'requirement_id': 'B'}))

    def test_separation_cache_checked_before_and_after_heavy_slot(self):
        from importlib.util import spec_from_file_location, module_from_spec
        from contextlib import contextmanager
        spec = spec_from_file_location('separation_fixture', PROJECT / 'bin/separate_local_audio.py')
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        model = self.root / '.runtime/models/separation/UVR-MDX-NET-Inst_HQ_3.onnx'
        model.parent.mkdir(parents=True)
        model.write_bytes(b'fixture model')
        source = self.run / 'inputs/source.wav'
        args = SimpleNamespace(output='outputs/local-separation')
        engine = SimpleNamespace(__version__='fixture')
        saved = {'stems': []}
        for delayed in (False, True):
            with self.subTest(delayed=delayed):
                slot = Mock()

                @contextmanager
                def heavy(*args):
                    slot()
                    yield

                with patch.object(module, 'ROOT', self.root), \
                     patch.object(local_audio, 'source_track', return_value=source), \
                     patch('video_localizer.model_routing.require_current'), \
                     patch.object(module, 'reuse_stems', side_effect=[None, saved] if delayed else [saved]) as reuse, \
                     patch('video_localizer.resources.heavy', heavy), \
                     patch.object(module, 'infer_stems') as infer:
                    args.output = 'outputs/delayed' if delayed else 'outputs/immediate'
                    module.execute(args, self.run, engine)
                    self.assertEqual(slot.call_count, int(delayed))
                    self.assertEqual(reuse.call_count, 2 if delayed else 1)
                    infer.assert_not_called()

    def test_asr_reuses_exact_audio_but_invalidates_audio_and_settings(self):
        path = self.run / 'inputs/audio.wav'; path.write_bytes(b'actual waveform fixture')
        engine = Mock()
        engine.transcribe.side_effect = lambda *a, **k: (iter([SimpleNamespace(start=0, end=1,
            text='hola', avg_logprob=-.1, no_speech_prob=0, words=[SimpleNamespace(word='hola',
            start=0, end=1, probability=.9)])]), SimpleNamespace(language='es', language_probability=.9))
        with patch.object(asr.model_cache, 'ensure', return_value=(self.root, {'model.bin': 'm'*64})), \
             patch.object(asr.importlib.metadata, 'version', return_value='fixture'), \
             patch.object(media, 'command', return_value=SimpleNamespace(stdout='fixture ffmpeg')), \
             patch.object(asr.audio, 'decode', return_value=[100, 200]), \
             patch.dict(sys.modules, {'faster_whisper': SimpleNamespace(WhisperModel=Mock(return_value=engine))}):
            first = asr.transcribe(self.run, 'inputs/audio.wav')
            second = asr.transcribe(self.run, 'inputs/audio.wav')
            self.assertFalse(first['reused']); self.assertTrue(second['reused'])
            self.assertEqual(engine.transcribe.call_count, 1)
            path.write_bytes(b'new waveform')
            self.assertFalse(asr.transcribe(self.run, 'inputs/audio.wav')['reused'])
            self.assertFalse(asr.transcribe(self.run, 'inputs/audio.wav', language='es')['reused'])
            self.assertEqual(engine.transcribe.call_count, 3)
            self.assertTrue((self.run / first['path']).exists())
            self.assertEqual(second['state'], 'needs_review')
            record = read_json(self.run / first['path']); record['segments'][0]['text'] = 'forged'
            write_json(self.run / first['path'], record)
            path.write_bytes(b'actual waveform fixture')
            with self.assertRaisesRegex(WorkflowError, 'evidence changed'):
                asr.transcribe(self.run, 'inputs/audio.wav')

    def test_tts_unknown_accent_is_rejected_before_provider_submission(self):
        packet = {'source_sha256': file_hash(self.run / 'inputs/source.wav'), 'purpose': 'fixture',
                  'estimated_credits': 1, 'payload': {'model': 'google/gemini-2-5-pro-tts',
                  'input': {'accent': 'guessed', 'speakers': [{'speaker_id': 'Speaker 1', 'voice_name': 'Kore'}],
                            'dialogue_turns': [{'speaker_id': 'Speaker 1', 'text': 'hola'}]}}}
        write_json(self.run / 'inputs/tts.json', packet)
        client = Mock()
        with self.assertRaisesRegex(WorkflowError, 'Unsupported Gemini'):
            model_tasks.submit(self.run, 'inputs/tts.json', client=client)
        self.assertEqual(client.mock_calls, [])

    def test_tts_keeps_documented_voice_delivery_controls(self):
        write_json(self.run / 'analysis/inventory.json', {
            'speech_segments': [{'id': 'sp1', 'target_text': 'hola'}]})
        packet = {'source_sha256': file_hash(self.run / 'inputs/source.wav'), 'purpose': 'fixture',
                  'estimated_credits': 1, 'speech_ids': ['sp1'],
                  'payload': {'model': 'google/gemini-2-5-pro-tts', 'input': {
                      'temperature': 1, 'sample_context': 'Conversational advertisement',
                      'speakers': [{'speaker_id': 'Speaker 1', 'voice_name': 'Kore',
                                    'audio_profile': 'Clear conversational voice',
                                    'style': 'Empathetic', 'pace': 'Natural'}],
                      'dialogue_turns': [{'speaker_id': 'Speaker 1', 'text': 'hola'}]}}}
        write_json(self.run / 'inputs/tts.json', packet)
        self.assertEqual(model_tasks.packet(self.run, 'inputs/tts.json'), packet)

    def test_real_mixer_reuses_and_preserves_prior_mix_after_revision(self):
        import numpy as np
        samples = np.zeros((44100 * 2, 2), dtype=np.float32)
        local_audio.save(self.run / 'inputs/source.wav', samples, 44100)
        write_json(self.run / 'run.json', {'source': 'inputs/source.wav',
                   'source_sha256': file_hash(self.run / 'inputs/source.wav')})
        voice = np.repeat((.1 * np.sin(np.arange(11025) * 2*np.pi*220/44100))[:, None], 2, axis=1)
        local_audio.save(self.run / 'inputs/voice.wav', voice, 44100)
        local_audio.save(self.run / 'inputs/background.wav', samples, 44100)
        write_json(self.run / 'analysis/inventory.json', {'speech_segments': [{'id': 'sp1', 'target_text': 'hola'}]})
        plan = {'source_sha256': file_hash(self.run / 'inputs/source.wav'),
                'background': {'path': 'inputs/background.wav', 'sha256': file_hash(self.run / 'inputs/background.wav')},
                'lines': [{'id': 'sp1', 'target_text': 'hola', 'start': .5, 'end': 1.5,
                           'voice': {'path': 'inputs/voice.wav', 'sha256': file_hash(self.run / 'inputs/voice.wav')}}]}
        write_json(self.run / 'inputs/narration-plan.json', plan)
        first = local_audio.mix(self.run)
        with patch.object(media, 'ffmpeg', side_effect=AssertionError('Repeated mixing')):
            self.assertTrue(local_audio.mix(self.run)['reused'])
        plan['lines'][0]['voice_gain_db'] = 1
        write_json(self.run / 'inputs/narration-plan.json', plan)
        second = local_audio.mix(self.run)
        self.assertNotEqual(first['path'], second['path'])
        self.assertEqual(file_hash(self.run / first['path']), first['sha256'])
        from video_localizer.library import _asset_closure
        recipe = (self.run / second['path']).parent / 'provenance.json'
        closure = _asset_closure(self.run, [(recipe, file_hash(recipe))])
        self.assertIn('inputs/voice.wav', closure)
        self.assertIn('inputs/background.wav', closure)
        self.assertIn(read_json(recipe)['source_audio']['path'], closure)
        (self.run / second['path']).write_bytes(b'tampered')
        with self.assertRaisesRegex(WorkflowError, 'checkpoint output changed'):
            local_audio.mix(self.run)
