import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_localizer import finalization, library, delivery_index
from video_localizer.common import WorkflowError, file_hash, read_json, write_json


class FinalizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.run = self.root / 'runs/example'
        self.run.mkdir(parents=True)
        write_json(self.root / 'config/workspace.json', {'output_policy': 'best_available_required'})
        for name, data in [('inputs/source.mp4', b'source fixture'), ('outputs/best.mp4', b'translated fixture'),
                           ('review/evidence.txt', b'observed fixture')]:
            path = self.run / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
        self.source_hash = file_hash(self.run / 'inputs/source.mp4')
        write_json(self.run / 'run.json', {'source': 'inputs/source.mp4', 'source_sha256': self.source_hash})
        write_json(self.run / 'inputs/request.json', {'target_language': 'ar'})
        write_json(self.run / 'analysis/inventory.json', {'text_instances': [{'id': 't', 'action': 'replace'},
                   {'id': 'brand', 'action': 'preserve'}], 'speech_segments': [{'id': 'speech'}], 'shots': []})
        def asset(name): return {'path': name, 'sha256': file_hash(self.run / name)}
        self.spec = {'source_sha256': self.source_hash, 'inventory_sha256': file_hash(self.run / 'analysis/inventory.json'),
            'request_sha256': file_hash(self.run / 'inputs/request.json'),
            'video': asset('outputs/best.mp4'), 'reviewer': 'fixture', 'reason': 'Retries ended',
            'text_ids': ['t'], 'speech_ids': ['speech'], 'speech_mode': 'subtitled',
            'evidence': [asset('review/evidence.txt')], 'assets': [], 'limitations': ['Original voice retained; translated captions supplied']}

    def test_missing_translation_and_changed_evidence_are_rejected(self):
        finalization.validate_completion(self.run, self.spec)
        self.spec['speech_ids'] = []
        with self.assertRaises(WorkflowError): finalization.validate_completion(self.run, self.spec)
        self.spec['speech_ids'] = ['speech']
        (self.run / 'review/evidence.txt').write_text('changed')
        with self.assertRaises(WorkflowError): finalization.validate_completion(self.run, self.spec)

    def test_subtitled_result_delivered_without_relabeling_quality_or_reuse(self):
        write_json(self.run / 'review/finalization.json', self.spec)
        old_quality = {'decision': 'revise', 'video_sha256': self.spec['video']['sha256'], 'failures': ['visible_seam']}
        write_json(self.run / 'outputs/quality.json', old_quality)
        meta = {'duration': 4, 'width': 320, 'height': 480, 'fps': 30, 'has_audio': True}
        with patch.object(finalization.media, 'probe', return_value=meta), patch.object(finalization.media, 'command'):
            result = finalization.finish(self.run)
        self.assertEqual(result['state'], 'delivered_with_issues')
        self.assertFalse(result['quality_passed'])
        self.assertEqual(read_json(self.run / 'outputs/quality.json'), old_quality)
        entries = library.find(self.source_hash, root=self.root)
        self.assertEqual(entries[0]['status'], 'delivered_with_issues')
        self.assertFalse(entries[0]['production_eligible'])
        self.assertEqual(delivery_index.refresh(self.root)['counts']['with_issues'], 1)
        self.assertTrue(finalization.finish(self.run)['reused'])

    def test_unplayable_output_is_not_published(self):
        write_json(self.run / 'review/finalization.json', self.spec)
        with patch.object(finalization.media, 'probe', side_effect=WorkflowError('decode failed')):
            with self.assertRaises(WorkflowError): finalization.finish(self.run)
        self.assertFalse((self.run / 'outputs/final.mp4').exists())

    def test_identical_hardlinked_candidate_and_final_can_be_archived(self):
        target = self.run / 'outputs/final.mp4'
        try:
            os.link(self.run / self.spec['video']['path'], target)
        except OSError:
            self.skipTest('Filesystem does not permit hard links')
        write_json(self.run / 'review/finalization.json', self.spec)
        meta = {'duration': 4, 'width': 320, 'height': 480, 'fps': 30, 'has_audio': True}
        with patch.object(finalization.media, 'probe', return_value=meta), patch.object(finalization.media, 'command'):
            result = finalization.finish(self.run)
        self.assertEqual(result['state'], 'delivered_with_issues')
        self.assertEqual(file_hash(target), self.spec['video']['sha256'])

    def test_new_request_finalization_keeps_selection_without_claiming_quality(self):
        write_json(self.run/'inputs/request.json', {'target_language':'ar','routing_contract_version':1,'require_target_audio':True})
        self.spec['request_sha256']=file_hash(self.run/'inputs/request.json')
        self.spec['speech_mode']='dubbed'
        inv=read_json(self.run/'analysis/inventory.json')
        inv['audio']={'has_speech':True}
        inv['speech_segments'][0].update(character_id='narrator',speech_role='narration')
        with self.assertRaisesRegex(WorkflowError,'assessment is required'):
            write_json(self.run/'analysis/inventory.json',inv)
            self.spec['inventory_sha256']=file_hash(self.run/'analysis/inventory.json')
            finalization.validate_completion(self.run,self.spec)
        (self.root/'knowledge').mkdir()
        (self.root/'knowledge/fixture.md').write_text('Synthetic method review')
        write_json(self.root/'knowledge/index.json',{'entries':[{'id':'method-fixture','status':'active',
            'path':'knowledge/fixture.md','scope':{'workflow':'video-localization'}}]})
        inv['routing_assessment']={'version':1,'primary_type':'mixed','reason':'Synthetic independent copy and narration',
            'evidence':['review/evidence.txt'],'method_choices':[{'domain':domain,'method_id':'method-fixture',
                'reason':'Synthetic observed condition','alternative':'Local scoped repair','switch_when':'Observed failure',
                'stop_when':'Bounded checks or capability limit'} for domain in ('speech','visual')]}
        write_json(self.run/'analysis/inventory.json',inv)
        self.spec['inventory_sha256']=file_hash(self.run/'analysis/inventory.json')
        write_json(self.run/'review/finalization.json',self.spec)
        meta={'duration':4,'width':320,'height':480,'fps':30,'has_audio':True}
        with patch.object(finalization.media,'probe',return_value=meta),patch.object(finalization.media,'command'):
            result=finalization.finish(self.run)
        completion=read_json(self.run/'outputs/completion.json')
        selected=self.run/completion['knowledge_selection']['path']
        snapshot=read_json(selected)
        self.assertEqual(snapshot['scope'],'finalization_selection_only')
        self.assertEqual(snapshot['routing_assessment']['primary_type'],'mixed')
        self.assertFalse(result['quality_passed'])
        package=self.root/result['package']['package']
        self.assertEqual(read_json(package/'payload'/completion['knowledge_selection']['path']),snapshot)

    def test_required_audio_blocks_subtitle_fallback_but_allows_actual_dubbing_review(self):
        write_json(self.run / 'inputs/request.json', {'target_language': 'ar', 'require_target_audio': True})
        self.spec['request_sha256'] = file_hash(self.run / 'inputs/request.json')
        with self.assertRaisesRegex(WorkflowError, 'Target audio is required'):
            finalization.validate_completion(self.run, self.spec)
        self.spec['speech_mode'] = 'dubbed'
        finalization.validate_completion(self.run, self.spec)
        # A declaration still cannot publish a file lacking an actual soundtrack.
        write_json(self.run / 'review/finalization.json', self.spec)
        meta = {'duration': 4, 'width': 320, 'height': 480, 'fps': 30, 'has_audio': False}
        with patch.object(finalization.media, 'probe', return_value=meta):
            with self.assertRaisesRegex(WorkflowError, 'actual audio stream'):
                finalization.finish(self.run)
        self.assertFalse((self.run / 'outputs/final.mp4').exists())


if __name__ == '__main__': unittest.main()
