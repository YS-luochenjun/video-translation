import copy
from pathlib import Path
import tempfile
import unittest
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))

from video_localizer.common import CODE_ROOT,write_json,read_json,file_hash,WorkflowError
from video_localizer import candidate_index,knowledge_advisories,knowledge_review,knowledge_overview,empty_reflections,curation


class KnowledgeHousekeepingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=CODE_ROOT/'work/test-tmp');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.source='a'*64
        self.scope={'workflow':'video-localization','source_sha256':self.source,'target_language':'de'}
        self.value={'id':'generated','status':'candidate','scope':self.scope,'outcome':'revise',
                    'hypothesis':'Needs an evidence-backed lesson','limitations':[],'company_preference':False,
                    'promotion':empty_reflections.PROMOTION,
                    'evidence':{'run':'fixture','video_sha256':'b'*64,'quality_sha256':'c'*64}}
        for name in ['knowledge/index.json','knowledge/cases/index.json']:write_json(self.root/name,{'entries':[]})
        self.public='knowledge/candidates/generated.json';self.private='knowledge/local/candidates/generated.json'
        write_json(self.root/self.public,self.value)
        write_json(self.root/self.private,{**self.value,'case':'knowledge/local/examples/fixture'})
        write_json(self.root/'knowledge/local/inbox/generated.json',{'id':'generated','case':'knowledge/local/examples/fixture'})
        write_json(self.root/'knowledge/local/examples/fixture/evidence.json',{'quality_passed':False})
        write_json(self.root/'state/budget.json',{'unknown_reserved':2})
        candidate_index.refresh(self.root)

    def test_placeholders_do_not_reach_advisory_but_remain_visible_for_review(self):
        context={**self.scope,'features':[]}
        self.assertEqual(knowledge_advisories.retrieve(context,self.root),[])
        rows=knowledge_review.queue(self.root)
        self.assertTrue(all(r['reflection_state']=='needs_lesson' for r in rows))
        before=(self.root/self.public).read_bytes()
        knowledge_overview.build(self.root)
        self.assertEqual(before,(self.root/self.public).read_bytes())

    def test_raw_asr_and_nested_case_payloads_are_not_repeated_learning_events(self):
        base=self.root/'knowledge/local/feedback/event'
        write_json(base/'feedback.json',{'quote':'Observed text remains on screen'})
        write_json(base/'actual-asr.json',{'segments':[],'engine':'fixture-asr','audio_sha256':'e'*64})
        write_json(base/'repair-case/manifest.json',{'kind':'knowledge-case','files':[]})
        write_json(base/'repair-case/feedback.json',{'quote':'Observed text remains on screen'})
        paths={x['path'] for x in knowledge_review.queue(self.root)}
        self.assertIn('knowledge/local/feedback/event/feedback.json',paths)
        self.assertNotIn('knowledge/local/feedback/event/actual-asr.json',paths)
        self.assertNotIn('knowledge/local/feedback/event/repair-case/feedback.json',paths)
        self.assertNotIn('knowledge/local/feedback/event/repair-case/manifest.json',paths)
        self.assertTrue((base/'actual-asr.json').exists())

    def test_public_candidate_inbox_closes_by_exact_reviewed_pointer_only(self):
        pointer=self.root/'knowledge/local/inbox/public-pointer.json'
        write_json(pointer,{'id':'generated','candidate':self.public,'candidate_sha256':file_hash(self.root/self.public)})
        knowledge_review.review({'source':{'path':self.public,'sha256':file_hash(self.root/self.public)},
            'review_type':'developer_review','reviewed_by':'fixture','origin':'Synthetic closed placeholder review',
            'resolution':'rejected','reason':'No substantive hypothesis','targets':[],'adopted_parts':[],
            'retained_parts':['Immutable original and all quality limits retained'],
            'all_material_accounted':True,'remaining_disposition':'historical_only','next_action':'historical_record_only'},self.root)
        key=(pointer.relative_to(self.root).as_posix(),file_hash(pointer))
        self.assertIn(key,knowledge_review.closed_sources(self.root))
        write_json(pointer,{'id':'generated','candidate':self.public,'candidate_sha256':'0'*64})
        self.assertNotIn((key[0],file_hash(pointer)),knowledge_review.closed_sources(self.root))

    def test_retained_case_pointer_is_not_an_actionable_advisory(self):
        value=copy.deepcopy(self.value)
        value['hypothesis']='Preserved source observations, decisions and failure records await distillation.'
        write_json(self.root/self.public,value);write_json(self.root/self.private,value)
        self.assertEqual(knowledge_advisories.retrieve(self.scope,self.root),[])
        self.assertTrue(all(r['reflection_state']=='needs_lesson' for r in knowledge_review.queue(self.root)))
        # Its rich case needs actual review, not the exact-empty bulk archive.
        self.assertEqual(empty_reflections.preview(self.root,{self.source})['count'],0)

    def test_verified_review_can_supply_a_real_advisory_for_legacy_placeholder(self):
        knowledge_review.review({'source':{'path':self.public,'sha256':file_hash(self.root/self.public)},
            'review_type':'developer_review','reviewed_by':'fixture','origin':'Synthetic explicit review',
            'resolution':'pending','reason':'Actual scoped finding supplied separately','targets':[],
            'adopted_parts':[],'retained_parts':['Original placeholder remains immutable'],
            'next_action':'Inspect the final tail frame','advisory':{'summary':'The CTA must retain the observed tail duration',
            'limitations':['Synthetic fixture'],'next_check':'Inspect actual source and final tail'}},self.root)
        self.assertEqual(knowledge_advisories.retrieve({**self.scope,'features':[]},self.root)[0]['summary'],
                         'The CTA must retain the observed tail duration')
        self.assertEqual(empty_reflections.preview(self.root,{self.source})['count'],1) # Reviewed public record excluded.

    def test_archive_preserves_original_scope_outcome_evidence_and_unsettled_budget(self):
        original=(self.root/self.public).read_bytes();private=(self.root/self.private).read_bytes()
        case=file_hash(self.root/'knowledge/local/examples/fixture/evidence.json');budget=file_hash(self.root/'state/budget.json')
        preview=empty_reflections.preview(self.root,{self.source});self.assertEqual(preview['count'],2)
        result=empty_reflections.execute(self.root,{self.source},preview['fingerprint'],'Fixture structural reviewer','Synthetic housekeeping test')
        self.assertEqual(result['reviewed'],2);self.assertEqual(result['archived_public'],1)
        self.assertFalse((self.root/self.public).exists())
        archived=self.root/result['results'][0]['archive']['archived']
        self.assertEqual(archived.read_bytes(),original)
        self.assertEqual((self.root/self.private).read_bytes(),private)
        self.assertEqual(file_hash(self.root/'knowledge/local/examples/fixture/evidence.json'),case)
        self.assertEqual(file_hash(self.root/'state/budget.json'),budget)
        self.assertEqual(knowledge_review.queue(self.root),[])
        self.assertNotIn(self.root/'knowledge/local/inbox/generated.json',curation.source_files(self.root))
        entry=next(e for e in candidate_index.build(self.root)['entries'] if e['path']==self.public)
        self.assertTrue(entry['current_review']['closed']);self.assertEqual(entry['historical_outcome'],'revise')

    def test_stale_preview_custom_observations_and_new_digests_cannot_be_bulk_closed(self):
        preview=empty_reflections.preview(self.root,{self.source})
        value=copy.deepcopy(self.value);value['limitations']=['Actual partial result needs review'];write_json(self.root/self.public,value)
        with self.assertRaises(WorkflowError):empty_reflections.execute(self.root,{self.source},preview['fingerprint'],'reviewer','fixture')
        self.assertTrue((self.root/self.public).exists())
        value=copy.deepcopy(self.value);value['evidence_digest']={'failure_codes':['residual_text']};write_json(self.root/self.private,value)
        self.assertEqual(empty_reflections.preview(self.root,{self.source})['count'],0)

    def test_navigation_groups_languages_without_merging_member_scope_or_sources(self):
        value=copy.deepcopy(self.value);value['scope']['target_language']='fr'
        write_json(self.root/'knowledge/candidates/fr.json',value)
        other=copy.deepcopy(value);other['scope']['source_sha256']='d'*64
        write_json(self.root/'knowledge/candidates/other-source.json',other)
        report=knowledge_overview.build(self.root)
        family=next(f for f in report['families'] if f['source_sha256']==self.source)
        self.assertEqual(family['languages'],['de','fr']);self.assertEqual(family['records'],3)
        self.assertEqual(len(report['families']),2)
        self.assertEqual({m['scope']['target_language'] for m in family['members']},{'de','fr'})


if __name__=='__main__':unittest.main()
