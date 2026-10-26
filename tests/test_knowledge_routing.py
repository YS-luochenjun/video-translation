import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from video_localizer import knowledge, learning
from video_localizer.common import WorkflowError, read_json, write_json

TEMP = PROJECT / "work/test-tmp"
TEMP.mkdir(parents=True, exist_ok=True)


class KnowledgeRoutingTests(unittest.TestCase):
    def test_observed_feature_aliases_reach_conditional_methods_without_changing_inventory(self):
        inventory = {"content_features": ["moving_text", "artistic_text", "music_with_singing",
                                          "custom_scene", "camera_motion"]}
        before = list(inventory["content_features"])
        context = knowledge.context_for({"target_language": "es"}, inventory, PROJECT)
        self.assertIn("animated_text", context["features"])
        self.assertIn("artistic_typography", context["features"])
        self.assertIn("sung_background_music", context["features"])
        self.assertIn("custom_scene", context["features"])
        self.assertEqual(inventory["content_features"], before)
        camera_only = knowledge.context_for({"target_language": "es"},
                                            {"content_features": ["camera_motion"]}, PROJECT)
        self.assertNotIn("animated_text", camera_only["features"])

    def test_required_policies_survive_method_limit_and_scope_still_applies(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as temporary:
            root = Path(temporary)
            (root / "knowledge").mkdir()
            (root / "knowledge/rule.md").write_text("fixture rule", encoding="utf-8")
            base = {"status": "active", "path": "knowledge/rule.md",
                    "scope": {"workflow": "video-localization"}}
            entries = [{**base, "id": f"method-{i}", "tags": ["speech", "text"]}
                       for i in range(9)]
            entries += [
                {**base, "id": "budget", "knowledge_type": "project_policy", "tags": ["cost"]},
                {**base, "id": "old-budget", "knowledge_type": "project_policy", "status": "superseded"},
                {**base, "id": "input", "knowledge_type": "project_policy",
                 "scope": {"phase": "language_resolution"}},
                {**base, "id": "conditional", "requires_features": ["animated_text"]},
            ]
            write_json(root / "knowledge/index.json", {"entries": entries})
            context = {"workflow": "video-localization", "tags": ["speech", "text"], "features": ["speech"]}
            result = knowledge.retrieve(context, root=root)
            self.assertEqual(len(result), 7)
            self.assertEqual(result[0]["id"], "budget")
            self.assertFalse({"old-budget", "input", "conditional"} & {e["id"] for e in result})
            self.assertEqual([e["id"] for e in knowledge.retrieve(context, limit=0, root=root)], ["budget"])

    def test_alias_cycles_are_rejected(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as temporary:
            root = Path(temporary)
            write_json(root / "config/content-features.json", {"aliases": {"a": "b", "b": "a"}})
            with self.assertRaisesRegex(WorkflowError, "without chains"):
                knowledge.context_for({"target_language": "es"}, {"content_features": ["a"]}, root)

    def test_promoted_any_feature_method_keeps_and_conditions_and_supersedes(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as temporary:
            root = Path(temporary)
            (root / "knowledge/rules").mkdir(parents=True)
            (root / "knowledge/rules/method.md").write_text("Reviewed fixture", encoding="utf-8")
            write_json(root / "observation.json", {"review": "test fixture"})
            write_json(root / "knowledge/index.json", {"entries": [{
                "id": "old", "status": "active", "path": "knowledge/rules/method.md", "retrieval_role": "required"}]})
            spec = {"id": "new", "path": "knowledge/rules/method.md", "tags": [],
                    "scope": {"workflow": "video-localization"}, "origin": "fixture",
                    "reviewed_by": "fixture", "approval_type": "developer_review",
                    "evidence_review": "sanitized_project_evidence", "company_preference": False,
                    "evidence_files": ["observation.json"], "supersedes": "old",
                    "requires_features": ["text"],
                    "delivery_modes": ["fast", "strict"], "language_match": "exact",
                    "requires_any_features": ["animated_text", "artistic_typography", "filmed_phone_ui"]}
            write_json(root / "spec.json", spec)
            learning.promote(root / "spec.json", root)
            for features, expected in [(["text", "artistic_typography"], True),
                                       (["text", "filmed_phone_ui"], True),
                                       (["text", "animated_text"], True),
                                       (["text", "camera_motion"], False),
                                       (["artistic_typography"], False), ([], False)]:
                with self.subTest(features=features):
                    context = {"workflow": "video-localization", "features": features}
                    self.assertEqual([e["id"] for e in knowledge.retrieve(context, root=root)],
                                     ["new"] if expected else [])
            entry = read_json(root / "knowledge/index.json")["entries"][-1]
            self.assertEqual(entry["requires_any_features"], spec["requires_any_features"])
            self.assertEqual(entry["delivery_modes"], spec["delivery_modes"])
            self.assertEqual(entry["language_match"], "exact")
            self.assertEqual(entry['retrieval_role'], 'required')
            self.assertEqual(learning.audit(root)["decision"], "pass")

    def test_malformed_feature_conditions_fail_closed(self):
        for key in ("requires_features", "requires_any_features"):
            for invalid in ("speech", None, [3], ["bad-feature"], ["speech"] * 33):
                with self.subTest(key=key, invalid=invalid):
                    with self.assertRaisesRegex(WorkflowError, key):
                        knowledge.validate_feature_requirements({key: invalid})

    def test_speaker_synonym_selects_detailed_method_without_inventing_a_scene(self):
        context = knowledge.context_for({'target_language':'es','delivery_mode':'fast'},
            {'content_features':['multi_speaker','hospital'], 'audio':{'has_speech':True}},PROJECT)
        self.assertIn('multi_character_dialogue',context['features'])
        self.assertNotIn('short_drama',context['features'])
        ids = {entry['id'] for entry in knowledge.retrieve(context,root=PROJECT)}
        self.assertIn('short-drama-character-voices-v2',ids)
        self.assertIn('short-drama-audio-scenes-v2',ids)
        self.assertIn('agent-method-selection-v2',ids)
        self.assertNotIn('natural-removal-blur-last-resort-20261023',ids)

    def test_delivery_modes_and_exact_vs_reviewed_base_locale(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as temp:
            root = Path(temp)
            (root/'knowledge').mkdir()
            (root/'knowledge/rule.md').write_text('fixture',encoding='utf-8')
            common = {'status':'active','path':'knowledge/rule.md','scope':{'target_language':'ja'}}
            write_json(root/'knowledge/index.json',{'entries':[
                {**common,'id':'exact'}, {**common,'id':'base','language_match':'base'},
                {**common,'id':'strict','delivery_modes':['strict'],'language_match':'base'}]})
            ctx = {'target_language':'JA-jp','delivery_mode':'fast'}
            self.assertEqual([e['id'] for e in knowledge.retrieve(ctx,root=root)],['base'])
            ctx['delivery_mode']='strict'
            self.assertEqual([e['id'] for e in knowledge.retrieve(ctx,root=root)],['base','strict'])
            ctx['target_language']='ja'
            self.assertEqual({e['id'] for e in knowledge.retrieve(ctx,root=root)},{'base','strict','exact'})
        for entry in ({'language_match':'base','scope':{'target_language':'ja-JP'}},
                      {'language_match':'silent_expand'},{'delivery_modes':['unknown']}):
            with self.assertRaises(WorkflowError): knowledge.validate_feature_requirements(entry)

    def test_related_locale_is_discovery_only_and_does_not_cross_sources(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as temp:
            root = Path(temp)
            (root/'knowledge/cases').mkdir(parents=True)
            (root/'knowledge/cases/rule.md').write_text('fixture',encoding='utf-8')
            entry = {'id':'japan','status':'active','path':'knowledge/cases/rule.md',
                     'scope':{'source_sha256':'source-a','target_language':'ja-JP'}}
            write_json(root/'knowledge/cases/index.json',{'entries':[entry]})
            ctx = {'source_sha256':'source-a','target_language':'ja'}
            self.assertEqual(knowledge.source_references(ctx,root=root),[])
            hint = knowledge.related_source_references(ctx,root=root)[0]
            self.assertTrue(hint['requires_language_review'])
            self.assertEqual(hint['authority'],'discovery_only_not_approved_for_requested_locale')
            self.assertEqual(knowledge.related_source_references({**ctx,'source_sha256':'source-b'},root=root),[])
            self.assertEqual(len(knowledge.source_references({**ctx,'target_language':'JA-jp'},root=root)),1)
            self.assertEqual(knowledge.related_source_references({**ctx,'target_language':'JA-jp'},root=root),[])
