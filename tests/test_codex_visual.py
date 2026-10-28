import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from video_localizer.common import WorkflowError, file_hash, read_json, write_json


class CodexVisualTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / 'runs/fixture'
        self.run.mkdir(parents=True)
        (self.run / 'source.mp4').write_bytes(b'fixture source, never decoded')
        Image.new('RGB', (80, 40), 'white').save(self.run / 'frame.png')
        write_json(self.run / 'run.json', {'source': 'source.mp4', 'source_sha256': file_hash(self.run / 'source.mp4')})
        write_json(self.run / 'inputs/request.json', {'target_language': 'es-ES', 'brief': 'Translate the ad'})
        write_json(self.run / 'analysis/inventory.json', {'source_sha256': file_hash(self.run / 'source.mp4'),
                   'shots': [{'id': 's001', 'keyframe': 'frame.png'}], 'text_instances': []})
        for name in ('AGENTS.md', 'agent/contracts/workflow.md', 'agent/contracts/quality.md', 'agent/contracts/model-routing.md',
                     'agent/workflows/video-localization.md'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('Project constraint: preserve product identity.', encoding='utf-8')

    def make_packet(self, stage='recognize'):
        from video_localizer import codex_visual
        with patch.object(codex_visual, 'retrieve', return_value=[]), \
                patch.object(codex_visual, 'source_references', return_value=[]):
            return codex_visual.packet(self.run, stage, root=self.root)

    def report(self, packet, **changes):
        frozen = read_json(self.run / packet['packet'])
        data = {'actor': 'Codex', 'method': 'Viewed the actual source image',
                'knowledge_read': [item['path'] for item in frozen['context']],
                'observations': [{'image': 'frame.png', 'observation': 'White fixture with no text.'}],
                'outputs': [], 'limitations': ['Fixture only; no real ad acceptance.']}
        data.update(changes)
        write_json(self.run / 'inputs/codex-report.json', data)
        return 'inputs/codex-report.json'

    def test_packet_requires_codex_observation_not_ocr_or_automatic_pass(self):
        result = self.make_packet()
        frozen = read_json(self.run / result['packet'])
        self.assertEqual(frozen['executor'], 'codex')
        self.assertEqual(frozen['stage'], 'recognize')
        self.assertEqual(frozen['images'][0]['sha256'], file_hash(self.run / 'frame.png'))
        self.assertTrue(frozen['context'])
        self.assertFalse(result['automatic_pass'])

    def test_result_binds_real_output_and_never_approves_inventory(self):
        from video_localizer import codex_visual
        packet = self.make_packet('image')
        instructions = read_json(self.run / packet['packet'])['execution']
        self.assertIn('ImageGen first', instructions)
        self.assertIn('record the concrete reason', instructions)
        Image.new('RGB', (80, 40), 'blue').save(self.run / 'edited.png')
        before = file_hash(self.run / 'analysis/inventory.json')
        report = self.report(packet, outputs=['edited.png'])
        result = codex_visual.record(self.run, packet['packet'], report, root=self.root)
        self.assertEqual(result['state'], 'needs_review')
        self.assertEqual(result['outputs'][0]['sha256'], file_hash(self.run / 'edited.png'))
        self.assertEqual(before, file_hash(self.run / 'analysis/inventory.json'))
        codex_visual.verify(self.run, result['record'], result['sha256'], root=self.root)
        from video_localizer.library import _asset_closure
        saved = _asset_closure(self.run, [(self.run / result['path'], result['sha256'])])
        self.assertTrue({'source.mp4', 'frame.png', 'edited.png', packet['packet'],
                         result['path'], 'inputs/request.json'} <= set(saved))
        Image.new('RGB', (80, 40), 'red').save(self.run / 'edited.png')
        with self.assertRaisesRegex(WorkflowError, 'changed'):
            codex_visual.verify(self.run, result['record'], result['sha256'], root=self.root)

    def test_missing_knowledge_or_changed_inputs_are_rejected(self):
        from video_localizer import codex_visual
        packet = self.make_packet()
        with self.assertRaisesRegex(WorkflowError, 'knowledge'):
            codex_visual.record(self.run, packet['packet'], self.report(packet, knowledge_read=[]), root=self.root)
        report = self.report(packet)
        (self.root / 'agent/contracts/quality.md').write_text('Changed constraints', encoding='utf-8')
        with self.assertRaisesRegex(WorkflowError, 'changed'):
            codex_visual.record(self.run, packet['packet'], report, root=self.root)

    def test_image_task_rejects_missing_output_and_input_overwrite(self):
        from video_localizer import codex_visual
        packet = self.make_packet('image')
        with self.assertRaisesRegex(WorkflowError, 'output'):
            codex_visual.record(self.run, packet['packet'], self.report(packet), root=self.root)
        with self.assertRaisesRegex(WorkflowError, 'input'):
            codex_visual.record(self.run, packet['packet'], self.report(packet, outputs=['frame.png']), root=self.root)


if __name__ == '__main__':
    unittest.main()
