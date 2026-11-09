import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import test_fireplay_publication as publication_fixtures
import test_fireplay as fixtures
from video_localizer import bundles, fireplay_publication as publication
from video_localizer.common import WorkflowError, file_hash, read_json, write_json


class AudioEvidenceReassessmentTests(unittest.TestCase):
    setUp = publication_fixtures.PublicationTests.setUp
    register = publication_fixtures.PublicationTests.register
    record = publication_fixtures.PublicationTests.record
    save = publication_fixtures.PublicationTests.save
    downloaded = publication_fixtures.PublicationTests.downloaded
    returned_setup = publication_fixtures.PublicationTests.returned_setup
    complete_output = publication_fixtures.PublicationTests.complete_output

    def new_evidence(self):
        spec, assessment = self.complete_output()
        old = self.root / spec['packages'][0]['package']
        rejected = copy.deepcopy(assessment)
        rejected.update(required_audio_complete=False, defects=[{
            'severity': 'major', 'kind': 'required_audio_unverified',
            'publication_impact': 'severe', 'description': 'Review API timed out; actual audio exists.'}])
        prior = publication.review(fixtures.CODE, {'package': str(old.relative_to(self.root)),
                                                  'assessment': rejected}, self.root)
        manifest = bundles.verify(old); digest = manifest['metadata']['video_sha256']
        report_path = f'payload/review/{digest[:12]}/audio-model-review.json'
        response_path = f'payload/review/{digest[:12]}/audio-model-response.json'
        report = self.root/'work/new-audio.json'; response = self.root/'work/provider-response.json'
        write_json(report, {'source_sha256':manifest['metadata']['source_sha256'],
                            'video_sha256':digest, 'response_id':'actual-response'})
        write_json(response, {'id':'actual-response'})
        quality = self.root/'work/new-quality.json'
        write_json(quality, {'video_sha256':digest, 'decision':'revise',
                            'audio_model_check':{'decision':'pass','review_sha256':file_hash(report)}})
        sources = {a['path']:old/a['path'] for a in manifest['files']}
        sources.update({report_path:report, response_path:response, 'payload/outputs/quality.json':quality})
        new = old.with_name(old.name+'-verified-audio')
        bundles.create(new,manifest['kind'],manifest['identity'],sources,manifest['metadata'])
        return old, new, assessment, prior

    def test_new_evidence_keeps_old_rejection_and_allows_same_video(self):
        old, new, assessment, prior = self.new_evidence()
        digest = bundles.verify(new)['metadata']['video_sha256']
        original = publication._path(self.root,fixtures.CODE,digest); original_hash=file_hash(original)
        revised = publication.review(fixtures.CODE, {'package':str(new.relative_to(self.root)),
            'assessment':assessment,'reassess_with_new_audio_evidence':True},self.root)
        self.assertEqual(revised['decision'],'minor_issues_acceptable')
        self.assertEqual(file_hash(original),original_hash)
        self.assertFalse(revised['evidence_reassessment']['quality_passed'])
        self.assertEqual(publication.eligible(fixtures.CODE,new,bundles.verify(new),self.root)['mode'],
                         'minor_issues_accepted_for_publication')

    def test_actual_defects_and_unchanged_reports_cannot_be_waived(self):
        old,new,assessment,prior=self.new_evidence();manifest=bundles.verify(new)
        bad=copy.deepcopy(prior);bad['assessment']['defects'][0]['kind']='missing_required_audio'
        with self.assertRaises(WorkflowError):
            publication._new_audio_evidence(bad,new,manifest,self.root)
        changed=copy.deepcopy(manifest);changed['metadata']['source_sha256']='0'*64
        with self.assertRaises(WorkflowError):
            publication._new_audio_evidence(prior,new,changed,self.root)
        stale=copy.deepcopy(manifest)
        with patch('video_localizer.bundles.verify',return_value=stale):
            # Matching old manifest hash still prevents a fabricated replacement.
            with self.assertRaises(WorkflowError):
                publication._new_audio_evidence(prior,new,stale,self.root)


if __name__ == '__main__':
    unittest.main()
