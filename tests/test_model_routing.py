import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from video_localizer.common import WorkflowError
from video_localizer.kie import KieClient


class ModelRoutingTests(unittest.TestCase):
    def test_new_plan_and_demo_reject_retired_generation_route_at_argument_parsing(self):
        entry = Path(__file__).resolve().parents[1] / 'bin/va.py'
        commands = [
            ['plan', '../retired-entry-probe', '--experiment', 'regenerate'],
            ['demo', '--id', '../retired-entry-probe', '--route', 'regenerate'],
        ]
        for arguments in commands:
            with self.subTest(command=arguments[0]):
                result = subprocess.run([sys.executable, str(entry), *arguments],
                                        capture_output=True, text=True, encoding='utf-8')
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn('invalid choice', result.stderr)

    def test_retired_video_models_are_rejected_before_network(self):
        client = KieClient(key='fixture-key')
        for model in ('veo-3-1', 'kling-3.0-omni/transformation', 'wan/2-6-flash-video-to-video',
                      'bytedance/seedance-2-fast', 'elevenlabs/text-to-speech-multilingual-v2',
                      'ai-music-api/separate-vocals'):
            with self.subTest(model=model), patch.object(client, '_request') as request:
                with self.assertRaises(WorkflowError):
                    client.create({'model': model, 'input': {}})
                request.assert_not_called()

    def test_single_video_and_tts_models_are_accepted(self):
        client = KieClient(key='fixture-key')
        for model in ('wan/2-7-videoedit', 'google/gemini-2-5-pro-tts'):
            with patch.object(client, '_request', return_value={'taskId': 'fixture-task'}):
                self.assertEqual(client.create({'model': model, 'input': {}}), 'fixture-task')

    def test_audio_default_is_flash_and_pro_does_not_silently_fallback(self):
        client = KieClient(key='fixture-key')
        with patch.object(client, '_request', return_value={'choices': [{}]}) as request:
            client.analyze_audio('https://example.invalid/source.wav', 'inspect')
            self.assertIn('/gemini-3-8-flash-openai/', request.call_args.args[0])
        with patch.object(client, '_request') as request:
            with self.assertRaises(WorkflowError):
                client.analyze_audio('https://example.invalid/source.wav', 'inspect', 'gemini-3-pro')
            request.assert_not_called()

    def test_retired_task_polling_remains_available(self):
        client = KieClient(key='fixture-key')
        with patch.object(client, '_request', return_value={'state': 'success'}) as request:
            client.status('old-task')
            self.assertIn('recordInfo', request.call_args.args[0])

    def test_retired_asr_size_is_blocked_before_download_or_inference(self):
        import tempfile
        from pathlib import Path
        from video_localizer import asr
        with tempfile.TemporaryDirectory() as tmp, patch.object(asr.model_cache, 'ensure') as install:
            with self.assertRaises(WorkflowError):
                asr.transcribe(Path(tmp), size='base', download=True)
            install.assert_not_called()
