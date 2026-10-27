import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from video_localizer import budgets, fast_delivery, knowledge, knowledge_usage, library, routing, work_packet
from video_localizer.common import ROOT, WorkflowError, file_hash, read_json, write_json


def choice(domain, method):
    return {'domain':domain, 'method_id':method, 'reason':'Observed synthetic source conditions support this method',
            'alternative':'A scoped alternative after inspecting the actual failure',
            'switch_when':'An observed mismatch contradicts this method condition',
            'stop_when':'Actual checks pass or bounded repair/credit/capability limit is reached'}


class ContentRoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT/'work/test-tmp')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.run = self.root/'runs/example'
        self.run.mkdir(parents=True)
        (self.run/'evidence.txt').write_text('Synthetic source observation; no real-video quality claim')
        self.speech = {'id':'a001','character_id':'narrator','speech_role':'narration'}
        self.text = {'id':'t001','action':'model_edit','text_role':'scene_text'}
        self.inv = {'audio':{'has_speech':True},'speech_segments':[self.speech], 'text_instances':[self.text]}
        self.entries = [{'id':'speech-fixture'},{'id':'visual-fixture'}]

    def assessment(self, kind='mixed'):
        return {'version':1,'primary_type':kind,'reason':'Synthetic primary carrier judgment, not a count threshold',
                'evidence':['evidence.txt'],'method_choices':[choice('speech','speech-fixture'),choice('visual','visual-fixture')]}

    def validate(self):
        return routing.validate(self.inv,{'routing_contract_version':1},self.run,self.entries,2)

    def test_three_classes_keep_narration_and_dialogue_in_scope(self):
        for kind in ('audio_led','onscreen_text_led','mixed'):
            for role in ('narration','dialogue'):
                with self.subTest(kind=kind,role=role):
                    self.inv['routing_assessment']=self.assessment(kind)
                    self.speech['speech_role']=role
                    self.assertEqual(self.validate()['primary_type'],kind)

    def test_missing_type_domain_reasons_or_ineligible_choice_block_new_request(self):
        with self.assertRaisesRegex(WorkflowError,'assessment is required'):self.validate()
        baseline=self.assessment()
        for field in ('reason','alternative','switch_when','stop_when'):
            self.inv['routing_assessment']=copy.deepcopy(baseline)
            self.inv['routing_assessment']['method_choices'][0][field]=' '
            with self.subTest(field=field),self.assertRaisesRegex(WorkflowError,field):self.validate()
        self.inv['routing_assessment']=copy.deepcopy(baseline)
        self.inv['routing_assessment']['method_choices'].pop(0)
        with self.assertRaisesRegex(WorkflowError,'every translation domain'):self.validate()
        self.inv['routing_assessment']=copy.deepcopy(baseline)
        self.inv['routing_assessment']['method_choices'][0]['method_id']='not-retrieved'
        with self.assertRaisesRegex(WorkflowError,'outside eligible'):self.validate()

    def test_caption_density_music_or_unknown_speech_cannot_fake_a_type(self):
        self.inv['routing_assessment']=self.assessment()
        self.text['text_role']='speech_caption'
        with self.assertRaisesRegex(WorkflowError,'independent onscreen'):self.validate()
        self.inv['speech_segments']=[]
        self.inv['audio']['has_speech']=False
        self.inv['routing_assessment']=self.assessment('audio_led')
        with self.assertRaisesRegex(WorkflowError,'actual speech'):self.validate()
        self.inv['text_instances']=[]
        self.inv['audio']['has_speech']=None
        self.inv['routing_assessment']=self.assessment('preserve_only')
        with self.assertRaisesRegex(WorkflowError,'Unknown speech'):self.validate()

    def test_fact_inference_prevents_role_tag_omission_without_guessing_genre(self):
        self.inv['speech_segments']=[self.speech,{'id':'a002','character_id':'doctor','speech_role':'dialogue'}]
        ctx=knowledge.context_for({'target_language':'ja'},self.inv,ROOT)
        self.assertIn('multi_character_dialogue',ctx['features'])
        self.assertIn('onscreen_text',ctx['features'])
        self.assertNotIn('short_drama',ctx['features'])
        ids={e['id'] for e in knowledge.retrieve(ctx,root=ROOT)}
        self.assertIn('short-drama-audio-scenes-v2',ids)
        self.assertIn('short-drama-character-voices-v2',ids)
        self.inv['speech_segments']=[self.speech,{'character_id':'unknown'},{'character_id':'narrator'}]
        ctx=knowledge.context_for({'target_language':'ja'},self.inv,ROOT)
        self.assertNotIn('multi_character_dialogue',ctx['features'])

    def test_complex_scene_keeps_required_methods_even_with_zero_optional_slots(self):
        self.inv['content_features']=['multi_character_dialogue','short_drama','animated_text','foreground_occlusion','moving_watermark']
        ctx=knowledge.context_for({'target_language':'ja'},self.inv,ROOT)
        entries=knowledge.retrieve(ctx,limit=0,root=ROOT)
        ids={e['id'] for e in entries}
        # Follow the independent index lineage instead of pinning today's version.
        # A successor must remain required and retrieved even with no optional slots;
        # missing methods, broken/cyclic lineages and stale retrieval still fail.
        index={e['id']:e for e in read_json(ROOT/'knowledge/index.json')['entries']}
        expected=set()
        for original in ('text-instance-timing-v1','method-spoken-caption-verification-v4',
                         'short-drama-audio-scenes-v2','method-animated-text-occlusion-v6',
                         'moving-watermark-removal-v1','route-selection-v3'):
            current=original
            visited=set()
            while index[current].get('superseded_by'):
                self.assertNotIn(current,visited,'Cyclic knowledge replacement')
                visited.add(current)
                current=index[current]['superseded_by']
            self.assertEqual(index[current]['status'],'active')
            expected.add(current)
            self.assertTrue(visited.isdisjoint(ids),'Superseded knowledge was retrieved')
        self.assertTrue(expected.issubset(ids),f'Missing required methods: {expected-ids}')
        self.assertTrue(any(i.startswith('method-source-neutral-preparation-') for i in ids))
        self.assertTrue(all(e.get('knowledge_type')=='project_policy' or e.get('retrieval_role')=='required' for e in entries))
        self.inv['content_features']=[]
        self.inv['text_instances']=[]
        ids={e['id'] for e in knowledge.retrieve(knowledge.context_for({'target_language':'ja'},self.inv,ROOT),root=ROOT)}
        self.assertFalse(any(i.startswith('method-source-neutral-preparation-') for i in ids))

    def test_legacy_request_retains_absent_assessment_instead_of_fabricating_history(self):
        self.assertIsNone(routing.validate(self.inv,{},self.run,self.entries))


class FastKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'work/test-tmp')
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.run=self.root/'runs/fast-case'
        self.run.mkdir(parents=True)
        for name,content in [('inputs/source.mp4',b'synthetic source'),('outputs/candidate.mp4',b'synthetic candidate'),
                             ('outputs/mix.wav',b'synthetic target narration'),('analysis/frame.txt',b'synthetic evidence')]:
            p=self.run/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(content)
        source=self.run/'inputs/source.mp4'
        write_json(self.run/'run.json',{'source':'inputs/source.mp4','source_sha256':file_hash(source)})
        write_json(self.run/'inputs/request.json',{'target_language':'ja','delivery_mode':'fast','routing_contract_version':1})
        (self.root/'config').mkdir()
        shutil.copyfile(ROOT/'config/fast-delivery.json',self.root/'config/fast-delivery.json')
        (self.root/'knowledge').mkdir()
        (self.root/'knowledge/fixture.md').write_text('Synthetic frozen method fixture')
        write_json(self.root/'knowledge/index.json',{'entries':[{'id':i,'status':'active','path':'knowledge/fixture.md',
            'scope':{'workflow':'video-localization'},'retrieval_role':'required'} for i in ('speech-fixture','visual-fixture')]})
        self.inv={'schema_version':1,'source_sha256':file_hash(source),'coverage':{kind:{'status':'reviewed','method':'Synthetic fixture only',
            'evidence':['analysis/frame.txt']} for kind in ('visual','speech','timeline')},
            'shots':[{'id':'s001','start':0,'end':2,'description':'Synthetic fixed scene','keyframe':'analysis/frame.txt'}],
            'text_instances':[{'id':'t001','source_text':'Buy','target_text':'購入','text_role':'scene_text','action':'model_edit',
                'start':0,'end':2,'bbox':[0,0,80,20],'reason':'Synthetic copy','evidence':['analysis/frame.txt']}],
            'speech_segments':[{'id':'a001','start':0,'end':2,'source_text':'Try','target_text':'試して','character_id':'narrator',
                'speech_role':'narration','caption_policy':'none','caption_reason':'No captions in fixture','evidence':['analysis/frame.txt']}],
            'audio':{'has_speech':True,'strategy':'replace','replacement_path':'outputs/mix.wav','reason':'Synthetic translation'},
            'routing_assessment':{'version':1,'primary_type':'mixed','reason':'Both synthetic language carriers are essential',
                'evidence':['analysis/frame.txt'],'method_choices':[choice('speech','speech-fixture'),choice('visual','visual-fixture')]}}
        write_json(self.run/'analysis/inventory.json',self.inv)
        write_json(self.run/'analysis/media.json',{'duration':2,'width':100,'height':100,'fps':30,'has_audio':True})
        write_json(self.run/'recipe.json',{'source_sha256':file_hash(source),'native_frame_mapping':True,
            'output':{'path':'outputs/candidate.mp4','sha256':file_hash(self.run/'outputs/candidate.mp4')},'assets':[]})

    def register(self):
        return fast_delivery.register(self.run,'recipe.json')

    def test_new_fast_request_needs_assessment_and_freezes_snapshot_used_by_followup(self):
        inv=copy.deepcopy(self.inv);inv.pop('routing_assessment')
        write_json(self.run/'analysis/inventory.json',inv)
        with self.assertRaisesRegex(WorkflowError,'assessment is required'):self.register()
        write_json(self.run/'analysis/inventory.json',self.inv)
        self.register()
        plan=read_json(self.run/'plan.json')
        self.assertEqual(read_json(self.run/'plans'/plan['id']/'plan.json'),plan)
        budgets.open_request({'authority':'user','authorization_ref':'synthetic-event','user_request':'fixture',
            'mode':'first','source':str(self.run/'inputs/source.mp4')},self.root)
        packet=work_packet.build(self.run)
        self.assertEqual(packet['knowledge'],plan['knowledge'])
        self.assertEqual(packet['knowledge_record_state'],'frozen')
        self.assertEqual(packet['routing_assessment']['primary_type'],'mixed')
        self.assertTrue(packet['knowledge_followup']['remaining'])
        # Exact-source guidance remains an Agent option; an unrelated case does not.
        (self.root/'knowledge/cases').mkdir()
        (self.root/'knowledge/cases/fixture.md').write_text('Synthetic exact-source repair reference')
        reference={'id':'source-recipe','status':'active','path':'knowledge/cases/fixture.md',
                   'scope':{'workflow':'video-localization','target_language':'ja','source_sha256':plan['source_sha256']}}
        write_json(self.root/'knowledge/cases/index.json',{'entries':[reference]})
        self.inv['routing_assessment']['method_choices'][1]['method_id']='source-recipe'
        write_json(self.run/'analysis/inventory.json',self.inv)
        self.register()
        selected=read_json(self.run/'plan.json')
        self.assertEqual(selected['source_references'][0]['id'],'source-recipe')
        reference['scope']['source_sha256']='unrelated-source'
        write_json(self.root/'knowledge/cases/index.json',{'entries':[reference]})
        with self.assertRaisesRegex(WorkflowError,'outside eligible'):self.register()

    def test_fast_feedback_and_archive_survive_outside_the_original_plan_location(self):
        self.register();plan=read_json(self.run/'plan.json')
        candidate=read_json(self.run/'outputs/candidate.json')
        use={'plan_id':plan['id'],'video_sha256':candidate['sha256'],'reviewed_by':'synthetic fixture',
            'review_type':'same_agent','uses':[{'path':e['path'],'sha256':e['sha256'],'outcome':'not_used',
            'observation':'Synthetic non-use report; no video judgment'} for e in plan['knowledge'][:1]]}
        # Duplicate fixture bodies share identity; report that identity once.
        self.assertEqual(knowledge_usage.record(self.run,use,self.root)['state'],'recorded_non_use')
        archived=library.export(self.run,root=self.root,video_sha256=candidate['sha256'])
        package=self.root/archived['package']
        self.assertEqual(read_json(package/'payload/plans'/plan['id']/'plan.json'),plan)
        self.assertTrue((package/'payload/plans'/plan['id']/'knowledge/01.md').is_file())

    def test_tampered_frozen_body_is_rejected_and_current_catalog_is_not_retroactive(self):
        self.register();plan=read_json(self.run/'plan.json')
        (self.root/'knowledge/fixture.md').write_text('New live catalog body')
        fast_delivery.validate_plan(self.run,plan)
        (self.run/'plans'/plan['id']/'knowledge/01.md').write_text('Tampered frozen body')
        with self.assertRaisesRegex(WorkflowError,'Frozen knowledge changed'):
            fast_delivery.validate_plan(self.run,plan)
