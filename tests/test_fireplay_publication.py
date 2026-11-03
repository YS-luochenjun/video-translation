import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import test_fireplay as fixtures
from video_localizer import bundles, fireplay, fireplay_publication as publication
from video_localizer.common import WorkflowError, file_hash, read_json, write_json


class PublicationTests(unittest.TestCase):
    setUp = fixtures.FireplayTests.setUp
    register = fixtures.FireplayTests.register
    record = fixtures.FireplayTests.record
    save = fixtures.FireplayTests.save
    downloaded = fixtures.FireplayTests.downloaded
    returned_setup = fixtures.FireplayTests.returned_setup

    def complete_output(self, severity='minor', many=False, speech_mode='dubbed'):
        spec = self.returned_setup()
        (self.root/'state/fireplay'/fixtures.CODE/'return-1.json').unlink()
        for item in spec['packages']:
            lang = item['locale']
            movie = self.root/f'work/{lang}.mp4'
            completion = self.root/f'work/{lang}-complete.json'
            request = self.root/f'work/{lang}-request.json'
            inventory = self.root/f'work/{lang}-inventory.json'
            quality = self.root/f'work/{lang}-revise.json'
            source = self.record()['videos'][0]['source']['sha256']
            write_json(completion, {'video_sha256':file_hash(movie),'source_sha256':source,'decode_passed':True,
                                   'speech_mode':speech_mode,'completed_at':'2026-10-27T09:00:00Z'})
            write_json(request, {'require_target_audio':True})
            write_json(inventory, {'speech_segments':[{'id':'s1'}],'audio':{'has_speech':True}})
            write_json(quality, {'decision':'revise','video_sha256':file_hash(movie),'scope':'synthetic unit fixture'})
            folder = self.root/item['package']
            folder = folder.with_name(folder.name+'-with-issues')
            bundles.create(folder,'delivery',file_hash(movie),{'final.mp4':movie,'payload/outputs/completion.json':completion,
                'payload/inputs/request.json':request,'payload/analysis/inventory.json':inventory,
                'payload/outputs/quality.json':quality},{'status':'delivered_with_issues','technical_decision':'revise',
                'source_sha256':source,'target_language':lang,'video_sha256':file_hash(movie)})
            item['package'] = str(folder.relative_to(self.root))
        assessment = {'reviewer':'Codex synthetic test fixture','reason':'Offline publication severity contract fixture',
                      'translation_complete':True,'required_audio_complete':True,'watchable':True,'too_many_issues':many,
                      'defects':[{'severity':severity,'description':'Synthetic observed defect'}],'evidence':['final.mp4']}
        return spec, assessment

    def output_with_restoration_review(self, row, *, same_video=True, defects=None):
        spec, assessment = self.complete_output()
        original = self.root/spec['packages'][0]['package']
        manifest = bundles.verify(original)
        review = self.root/'work/cover-review.json'
        write_json(review, {'video_sha256': manifest['metadata']['video_sha256'] if same_video else '0'*64,
                            'text_restoration_review': [row], 'visual_finish': {'defects': defects or []}})
        sources = {a['path']: original/a['path'] for a in manifest['files']}
        sources['payload/review/fast-review.json'] = review
        folder = original.with_name(original.name+'-observations')
        bundles.create(folder, manifest['kind'], manifest['identity'], sources, manifest['metadata'])
        return str(folder.relative_to(self.root)), assessment

    def test_observed_cover_cannot_be_relabelled_as_ordinary_minor(self):
        folder, assessment = self.output_with_restoration_review({'id':'t001', 'visible_coverup':True})
        value = publication.review(fixtures.CODE, {'package':folder,'assessment':assessment}, self.root)
        self.assertEqual(value['decision'], 'blocked_major_or_incomplete')
        self.assertEqual(value['observed_visual_findings'][0]['id'], 't001')

    def test_bounded_best_available_submits_ordinary_repair_artifacts(self):
        folder, assessment = self.output_with_restoration_review({'id':'t001', 'visible_coverup':True})
        write_json(self.root/'config/fireplay-publication.json', {'mode':'bounded_best_available'})
        assessment['best_available'] = {'stop_condition':'budget_limit','reason':'Actual bounded stop', 'evidence':['final.mp4']}
        value = publication.review(fixtures.CODE, {'package':folder,'assessment':assessment}, self.root)
        self.assertEqual(value['decision'], 'bounded_best_available_acceptable')
        self.assertTrue(value['internal_quality_unchanged'])

    def test_residual_letters_are_not_automatically_semantic_incompleteness(self):
        folder, assessment = self.output_with_restoration_review({'id':'t001', 'visible_coverup':False,
                'source_text_removed':False, 'observation':'Old letters still show through the repair'})
        value = publication.review(fixtures.CODE, {'package':folder,'assessment':assessment}, self.root)
        self.assertEqual(value['decision'], 'blocked_major_or_incomplete')
        self.assertEqual(value['observed_visual_findings'][0]['kind'], 'residual_source_lettering')
        self.assertTrue(value['assessment']['translation_complete'])

    def test_real_missing_translation_still_blocks_at_bounded_stop(self):
        folder, assessment = self.output_with_restoration_review({'id':'t001', 'visible_coverup':True})
        write_json(self.root/'config/fireplay-publication.json', {'mode':'bounded_best_available'})
        assessment['best_available'] = {'stop_condition':'budget_limit','reason':'Actual bounded stop', 'evidence':['final.mp4']}
        assessment['translation_complete'] = False
        value = publication.review(fixtures.CODE, {'package':folder,'assessment':assessment}, self.root)
        self.assertEqual(value['decision'], 'blocked_major_or_incomplete')

    def test_current_severe_observation_cannot_be_hidden_in_an_ordinary_assessment(self):
        folder, assessment = self.output_with_restoration_review({'id':'t001', 'visible_coverup':False},
                defects=[{'kind':'large_area_tearing', 'severity':'major', 'publication_impact':'severe'}])
        write_json(self.root/'config/fireplay-publication.json', {'mode':'bounded_best_available'})
        assessment['best_available'] = {'stop_condition':'budget_limit','reason':'Actual bounded stop', 'evidence':['final.mp4']}
        value = publication.review(fixtures.CODE, {'package':folder,'assessment':assessment}, self.root)
        self.assertEqual(value['decision'], 'blocked_major_or_incomplete')

    def test_cosmetic_residue_submits_at_bound_without_rewriting_initial_review(self):
        folder, assessment = self.output_with_restoration_review({'id':'t001', 'visible_coverup':False,
                'source_text_removed':False, 'observation':'Faint old outline remains, target copy is complete'})
        write_json(self.root/'config/fireplay-publication.json', {'mode':'bounded_best_available'})
        assessment['best_available'] = {'stop_condition':'retry_limit','reason':'Two bounded repair rounds ended', 'evidence':['final.mp4']}
        value = publication.review(fixtures.CODE, {'package':folder,'assessment':assessment}, self.root)
        self.assertEqual(value['decision'], 'bounded_best_available_acceptable')
        self.assertTrue(value['internal_quality_unchanged'])

    def test_old_video_observation_does_not_reject_a_different_repaired_video(self):
        folder, assessment = self.output_with_restoration_review({'id':'t001', 'visible_coverup':True}, same_video=False)
        value = publication.review(fixtures.CODE, {'package':folder,'assessment':assessment}, self.root)
        self.assertEqual(value['decision'], 'minor_issues_acceptable')

    def test_technical_matte_or_pending_review_is_not_itself_a_visible_cover(self):
        folder, assessment = self.output_with_restoration_review({'id':'t001', 'visible_coverup':None,
                'technical_matte_used': True})
        value = publication.review(fixtures.CODE, {'package':folder,'assessment':assessment}, self.root)
        self.assertEqual(value['decision'], 'minor_issues_acceptable')
        self.assertNotIn('observed_visual_findings', value)

    def test_minor_issues_publish_without_rewriting_quality(self):
        spec, assessment = self.complete_output()
        for item in spec['packages']:
            publication.review(fixtures.CODE,{'package':item['package'],'assessment':assessment},self.root)
        outbox = fireplay.prepare_return(fixtures.CODE,spec,self.root)
        self.assertEqual(outbox['state'],'ready')
        self.assertTrue(all(p['publication_acceptance']['quality_passed'] is False for p in outbox['packages']))
        for p in outbox['packages']:
            self.assertEqual(read_json(self.root/p['package']/'manifest.json')['metadata']['technical_decision'],'revise')

    def test_major_or_many_issues_block_instead_of_changing_to_pass(self):
        spec, assessment = self.complete_output('major')
        for item in spec['packages']:
            r = publication.review(fixtures.CODE,{'package':item['package'],'assessment':assessment},self.root)
            self.assertEqual(r['decision'],'blocked_major_or_incomplete')
        with self.assertRaisesRegex(WorkflowError,'Major/many'):
            fireplay.prepare_return(fixtures.CODE,spec,self.root)

    def test_too_many_minor_issues_also_block(self):
        spec, assessment = self.complete_output(many=True)
        item=spec['packages'][0]
        self.assertEqual(publication.review(fixtures.CODE,{'package':item['package'],'assessment':assessment},self.root)['decision'],
                         'blocked_major_or_incomplete')
        with self.assertRaisesRegex(WorkflowError,'Major/many'):
            fireplay.prepare_return(fixtures.CODE,spec,self.root)

    def test_completion_missing_audio_or_real_review_cannot_publish(self):
        spec, assessment = self.complete_output()
        with self.assertRaisesRegex(WorkflowError,'actual minor/major'):
            fireplay.prepare_return(fixtures.CODE,spec,self.root)
        item=spec['packages'][0]
        assessment['translation_complete']=False
        self.assertEqual(publication.review(fixtures.CODE,{'package':item['package'],'assessment':assessment},self.root)['decision'],
                         'blocked_major_or_incomplete')

    def test_subtitles_do_not_satisfy_required_audio(self):
        spec, assessment = self.complete_output(speech_mode='subtitled')
        with self.assertRaisesRegex(WorkflowError,'target audio'):
            publication.review(fixtures.CODE,{'package':spec['packages'][0]['package'],'assessment':assessment},self.root)

    def test_exact_user_acceptance_preserves_major_review_and_internal_quality(self):
        spec, assessment = self.complete_output('major', many=True)
        for item in spec['packages']:
            prior = publication.review(fixtures.CODE, {'package': item['package'], 'assessment': assessment}, self.root)
            before = read_json(self.root / 'state/fireplay' / fixtures.CODE / 'publication-reviews' / (prior['video_sha256'] + '.json'))
            approval = {'authority': 'user', 'accepted': True, 'authorization_ref': 'actual-user-message',
                        'source_quote': 'I accept these repair imperfections; upload these versions',
                        'video_sha256': prior['video_sha256']}
            publication.review(fixtures.CODE, {'package': item['package'], 'user_acceptance': approval}, self.root)
            self.assertEqual(read_json(self.root / 'state/fireplay' / fixtures.CODE / 'publication-reviews' /
                                      (prior['video_sha256'] + '.json')), before)
        box = fireplay.prepare_return(fixtures.CODE, spec, self.root)
        self.assertTrue(all(x['publication_acceptance']['mode'] == 'exact_version_user_acceptance' for x in box['packages']))
        self.assertTrue(all(x['publication_acceptance']['quality_passed'] is False for x in box['packages']))

    def test_user_visual_acceptance_rejects_wrong_hash_or_missing_translation(self):
        spec, assessment = self.complete_output('major')
        item = spec['packages'][0]
        prior = publication.review(fixtures.CODE, {'package': item['package'], 'assessment': assessment}, self.root)
        approval = {'authority': 'user', 'accepted': True, 'authorization_ref': 'user-message',
                    'source_quote': 'Accept', 'video_sha256': '0' * 64}
        with self.assertRaisesRegex(WorkflowError, 'exact video hash'):
            publication.review(fixtures.CODE, {'package': item['package'], 'user_acceptance': approval}, self.root)
        approval['video_sha256'] = prior['video_sha256']
        prior_path = self.root / 'state/fireplay' / fixtures.CODE / 'publication-reviews' / (prior['video_sha256'] + '.json')
        stored = read_json(prior_path)
        stored['assessment']['translation_complete'] = False
        write_json(prior_path, stored)
        with self.assertRaisesRegex(WorkflowError, 'cannot waive incomplete'):
            publication.review(fixtures.CODE, {'package': item['package'], 'user_acceptance': approval}, self.root)


if __name__ == '__main__':
    unittest.main()
