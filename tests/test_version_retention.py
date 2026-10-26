import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_localizer import bundles, retention
from video_localizer.common import WorkflowError, file_hash, read_json, write_json

PROJECT = Path(__file__).resolve().parents[1]


class VersionRetentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=PROJECT/'work/test-tmp')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.run = self.root/'runs/fixture'
        self.run.mkdir(parents=True)
        write_json(self.run/'run.json', {'source_sha256':'a'*64})
        self.old = self.run/'outputs/old/master.mkv'
        self.old.parent.mkdir(parents=True); self.old.write_bytes(b'old pixels')
        (self.old.parent/'failure.png').write_bytes(b'actual evidence')
        write_json(self.old.parent/'recipe.json', {'method':'old method'})
        self.spec = {'versions':[{'path':'outputs/old/master.mkv','sha256':file_hash(self.old),
            'decision':'failed','reason':'Visible artifact at the title entry',
            'evidence':['outputs/old/failure.png'], 'records':['outputs/old/recipe.json'],
            'evidence_scope':'The selected image records the observed static defect; not full video recovery.'}]}
        write_json(self.run/'prune.json', self.spec)
        self.inspect = patch.object(retention,'inspect',return_value={
            'decision':'ready','blockers':[],'fingerprint':'preserved'})
        self.inspect.start(); self.addCleanup(self.inspect.stop)

    def test_preview_then_delete_retains_independent_failure_evidence(self):
        preview=retention.prune_versions(self.run,'prune.json',self.root)
        self.assertTrue(self.old.exists())
        with self.assertRaisesRegex(WorkflowError,'fingerprint'):
            retention.prune_versions(self.run,'prune.json',self.root,True,'wrong')
        result=retention.prune_versions(self.run,'prune.json',self.root,True,preview['fingerprint'])
        self.assertFalse(self.old.exists())
        self.assertTrue((self.old.parent/'recipe.json').exists())
        case=self.root/result['evidence_bundle']
        self.assertEqual(bundles.verify(case)['kind'],'retired-versions')
        self.assertEqual((case/'evidence/outputs/old/failure.png').read_bytes(),b'actual evidence')

    def test_current_dependency_and_another_run_hash_are_protected(self):
        write_json(self.run/'analysis/inventory.json',{'prepared_video':{
            'path':'outputs/old/master.mkv','sha256':file_hash(self.old)}})
        with self.assertRaisesRegex(WorkflowError,'referenced'):
            retention.prune_versions(self.run,'prune.json',self.root)
        (self.run/'analysis/inventory.json').unlink()
        write_json(self.root/'runs/other/plan.json',{'base_sha256':file_hash(self.old)})
        with self.assertRaisesRegex(WorkflowError,'referenced'):
            retention.prune_versions(self.run,'prune.json',self.root)

    def test_missing_evidence_changed_preview_and_unsettled_block(self):
        preview=retention.prune_versions(self.run,'prune.json',self.root)
        (self.old.parent/'failure.png').write_bytes(b'changed')
        with self.assertRaisesRegex(WorkflowError,'fingerprint'):
            retention.prune_versions(self.run,'prune.json',self.root,True,preview['fingerprint'])
        (self.old.parent/'failure.png').unlink()
        with self.assertRaisesRegex(WorkflowError,'evidence'):
            retention.prune_versions(self.run,'prune.json',self.root)
        self.inspect.stop()
        with patch.object(retention,'inspect',return_value={'decision':'blocked','blockers':['Unsettled billing']}):
            with self.assertRaisesRegex(WorkflowError,'Unsettled billing'):
                retention.prune_versions(self.run,'prune.json',self.root)

    def test_no_automatic_failure_inference_or_empty_evidence(self):
        self.spec['versions'][0]['decision']='old'
        write_json(self.run/'prune.json',self.spec)
        with self.assertRaises(WorkflowError):
            retention.prune_versions(self.run,'prune.json',self.root)

    def test_failed_request_without_task_id_still_has_unknown_cost(self):
        job={'state':'failed','estimated_credits':22,'error':'request timeout'}
        write_json(self.run/'jobs/request.json',job)
        self.assertTrue(any('Missing settled task cost' in b for b in retention.blockers(self.run)))
        job['credits_consumed']=0
        write_json(self.run/'jobs/request.json',job)
        self.assertEqual(retention.blockers(self.run),[])

    def test_request_reservation_without_job_file_is_not_lost(self):
        path=self.root/'state/budgets/request.json'
        write_json(path,{'reservations':{'r':{'run':'fixture','job':'lost','state':'failed','actual_credits':None}}})
        self.assertTrue(any('Unsettled request reservation' in b for b in retention.blockers(self.run)))
        write_json(path,{'reservations':{'r':{'run':'fixture','job':'settled','state':'failed','actual_credits':0}}})
        self.assertEqual(retention.blockers(self.run),[])

    def test_active_heavy_work_and_missing_archive_block_deletion(self):
        lock=self.root/'state/resources/heavy-0.lock'
        lock.parent.mkdir(parents=True); lock.write_text('123')
        with self.assertRaisesRegex(WorkflowError,'Heavy work'):
            retention.prune_versions(self.run,'prune.json',self.root)
        lock.unlink()
        preview=retention.prune_versions(self.run,'prune.json',self.root)
        with patch.object(bundles,'verify',side_effect=WorkflowError('Evidence archive changed')):
            with self.assertRaisesRegex(WorkflowError,'Evidence archive changed'):
                retention.prune_versions(self.run,'prune.json',self.root,True,preview['fingerprint'])
        self.assertTrue(self.old.exists())

    def test_reference_scan_keeps_cross_run_audio_and_nested_provenance(self):
        audio=self.run/'outputs/voice.wav';audio.write_bytes(b'voice')
        other=self.root/'runs/consumer'
        write_json(other/'plan.json',{'record':'inputs/dependencies.json'})
        write_json(other/'inputs/dependencies.json',{'audio':'../fixture/outputs/voice.wav',
                   'video':'../fixture/outputs/old/master.mkv', 'irrelevant':'review/local.png'})
        _,paths=retention._live_references(self.root,exclude_run=self.run)
        self.assertIn(audio,paths)
        self.assertIn(self.old,paths)

    def test_local_comparison_page_ids_do_not_trigger_filesystem_resolution(self):
        other=self.root/'runs/consumer'
        write_json(other/'plan.json',{'pages':[{'id':f'review/compare-{n}.png'} for n in range(1000)]})
        original=Path.resolve
        with patch.object(Path,'resolve',autospec=True,side_effect=original) as resolve:
            retention._live_references(self.root,exclude_run=self.run)
        self.assertLess(resolve.call_count,10)
