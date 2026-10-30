"""The requested approach is a default; the approved result remains source/locale bound."""
import tempfile
import unittest
from pathlib import Path

from video_localizer import knowledge
from video_localizer.common import CODE_ROOT
from workspace_fixture import copy_project_knowledge

POLICY = 'source-led-visual-localization-v1'
CASE = 'mog056-ja-style-v3-user-accepted-20261030'
SOURCE = '0dec4247dea0050f2ddd6eb36e0b3f7f34f0b5891e72181471169d13b4c70259'


def context(source, language, mode='fast'):
    return {'workflow': 'video-localization', 'source_sha256': source, 'target_language': language,
            'delivery_mode': mode, 'features': ['onscreen_text'], 'tags': ['text', 'visual', 'typography']}


class SourceVisualPolicyTests(unittest.TestCase):
    def test_default_policy_reaches_new_languages_but_does_not_inherit_japanese_acceptance(self):
        for language, mode in [('ja', 'fast'), ('de', 'fast'), ('ar', 'strict'), ('pt-BR', 'strict')]:
            with self.subTest(language=language, mode=mode):
                ctx = context('f'*64, language, mode)
                self.assertIn(POLICY, {e['id'] for e in knowledge.retrieve(ctx, root=CODE_ROOT)})
                self.assertNotIn(CASE, {e['id'] for e in knowledge.source_references(ctx, root=CODE_ROOT)})

    def test_approved_case_survives_without_runs_outputs_or_local_data_and_stays_exact_locale(self):
        with tempfile.TemporaryDirectory(dir=CODE_ROOT / 'work/test-tmp') as tmp:
            root = Path(tmp)
            copy_project_knowledge(CODE_ROOT, root)
            self.assertFalse((root / 'runs').exists())
            self.assertFalse((root / 'outputs').exists())
            self.assertFalse((root / 'knowledge/local').exists())
            self.assertIn(CASE, {e['id'] for e in knowledge.source_references(context(SOURCE, 'ja'), root=root)})
            self.assertNotIn(CASE, {e['id'] for e in knowledge.source_references(context(SOURCE, 'de'), root=root)})
