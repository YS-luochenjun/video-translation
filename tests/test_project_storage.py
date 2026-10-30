import copy
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from video_localizer import delivery_layout, project_storage
from video_localizer.common import CODE_ROOT, WorkflowError, file_hash, read_json, write_json


class ProjectStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('delivery-policy.json', 'storage-policy.json', 'maintenance.json'):
            dest=self.root/'config'/name;dest.parent.mkdir(exist_ok=True);shutil.copyfile(CODE_ROOT/'config'/name,dest)
        write_json(self.root/'config/storage-authorization.local.json', {
            'workspace':str(self.root),'automatic_cleanup':True,'reset_existing_data':True,'source_quote':'Explicit synthetic fixture owner request'})
        write_json(self.root/'knowledge/index.json', {'entries':[]})
        write_json(self.root/'knowledge/cases/index.json', {'entries':[]})
        self.now=datetime(2026,10,30,tzinfo=timezone.utc)

    def file(self, name, data=b'fixture'):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);return p

    def package(self, version, days, keep=False):
        path=f'outputs/.packages/REQ/ja/source-1/{version}'
        video=self.file(path+'/final.mp4',version.encode())
        write_json(self.root/path/'manifest.json',{'fixture':True})
        row={'requirement_name':'REQ','task_name':'source-1','target_language':'ja',
             'source_sha256':'a'*64,'video_sha256':file_hash(video),'package':path,
             'archived_at':(self.now-timedelta(days=days)).isoformat(),'keep_multiple_versions':keep,'origin_run_id':version}
        return row

    def test_reset_preserves_knowledge_runtime_unknown_costs_and_original_records(self):
        for area in project_storage.AREAS:self.file(area+'/old/blob.mp4',b'old media')
        write_json(self.root/'runs/old/jobs/unknown.json', {'id':'a'*64,'state':'ambiguous','estimated_credits':32,'task_id':'real-unknown-fixture'})
        ledger=self.file('state/accounting/unknown.json',b'{"reserved":32,"actual":null}')
        knowledge=self.file('knowledge/actual-proof.md',b'permanent learned evidence')
        runtime=self.file('.runtime/tool',b'installed')
        with tempfile.TemporaryDirectory() as external:
            target=Path(external)/'keep';target.write_bytes(b'outside')
            (self.root/'work/link').symlink_to(target)
            plan=project_storage.preview(self.root,reset=True)
            result=project_storage.execute(self.root,plan['fingerprint'],reset=True)
            self.assertEqual(target.read_bytes(),b'outside')
        for area in project_storage.AREAS:self.assertEqual(list((self.root/area).iterdir()),[])
        self.assertEqual(ledger.read_bytes(),b'{"reserved":32,"actual":null}')
        self.assertEqual(knowledge.read_bytes(),b'permanent learned evidence')
        self.assertEqual(runtime.read_bytes(),b'installed')
        saved=self.root/result['preserved_records']/'runs/old/jobs/unknown.json'
        self.assertEqual(read_json(saved)['estimated_credits'],32)
        self.assertFalse(read_json(self.root/'config/storage-authorization.local.json')['reset_existing_data'])
        with self.assertRaisesRegex(WorkflowError,'authorization'):
            project_storage.preview(self.root,reset=True)

    def test_changed_preview_or_live_lock_cannot_delete(self):
        path=self.file('runs/old/data.txt',b'before')
        plan=project_storage.preview(self.root,reset=True)
        path.write_bytes(b'new changed data')
        with self.assertRaisesRegex(WorkflowError,'preview changed'):
            project_storage.execute(self.root,plan['fingerprint'],reset=True)
        self.assertTrue(path.exists())
        self.file('runs/.locks/active.lock')
        with self.assertRaisesRegex(WorkflowError,'Active'):
            project_storage.preview(self.root,reset=True)

    def test_managed_close_does_not_create_permanent_video_backups(self):
        from video_localizer import maintenance, retention
        run=self.root/'runs/closed'
        source=self.file('runs/closed/inputs/source.mp4',b'original source')
        video=self.file('runs/closed/outputs/final.mp4',b'translated result')
        write_json(run/'run.json',{'source':'inputs/source.mp4','source_name':'ad.mp4','source_sha256':file_hash(source)})
        write_json(run/'inputs/request.json',{'target_language':'ja'})
        write_json(run/'outputs/delivery.json',{'video':'outputs/final.mp4','sha256':file_hash(video)})
        write_json(run/'jobs/unknown.json',{'state':'ambiguous','estimated_credits':32})
        with patch.object(retention,'preserve',side_effect=AssertionError('No permanent full-video backup')):
            result=maintenance.maintain(run,close=True)
        self.assertEqual(result['state'],'closed_pending_lifecycle')
        self.assertFalse((self.root/'state/run-recovery').exists())
        self.assertTrue((self.root/result['package']['package']/'manifest.json').exists())
        plan=project_storage.preview(self.root,now=self.now)
        self.assertIn('runs/closed',[row['path'] for row in plan['selected']])
        project_storage.execute(self.root,plan['fingerprint'],now=self.now)
        self.assertFalse(run.exists())
        self.assertTrue((self.root/result['package']['package']/'final.mp4').exists())

    def test_latest_only_and_expiry_keep_history_but_not_media(self):
        old=self.package('old',3);new=self.package('new',1)
        write_json(self.root/'state/delivery-index.json',{'entries':[old,new]})
        plan=project_storage.preview(self.root,now=self.now)
        self.assertEqual([r['path'] for r in plan['selected']],[old['package']])
        project_storage.execute(self.root,plan['fingerprint'],now=self.now)
        self.assertFalse((self.root/old['package']).exists());self.assertTrue((self.root/new['package']).exists())
        later=self.now+timedelta(days=14)
        plan=project_storage.preview(self.root,now=later)
        self.assertEqual([r['path'] for r in plan['selected']],[new['package']])
        project_storage.execute(self.root,plan['fingerprint'],now=later)
        self.assertTrue(all(e.get('expired_at') for e in read_json(self.root/'state/delivery-index.json')['entries']))

    def test_explicit_multiple_versions_still_expires_at14days(self):
        old=self.package('old',3);new=self.package('new',1,keep=True)
        write_json(self.root/'state/delivery-index.json',{'entries':[old,new]})
        self.assertEqual(project_storage.preview(self.root,now=self.now)['selected'],[])
        self.assertEqual(len(project_storage.preview(self.root,now=self.now+timedelta(days=20))['selected']),2)

    def test_human_view_uses_requirement_language_and_source_task_without_version_hash(self):
        run=self.root/'runs/MOG-20261030-001-2-01'
        write_json(run/'run.json',{'source':'inputs/source.mp4','source_sha256':'a'*64})
        write_json(run/'inputs/request.json',{'target_language':'ja'})
        ident=delivery_layout.identity(run)
        self.assertEqual((ident['requirement_name'],ident['task_name']),('MOG-20261030-001','原片-2'))
        first=self.file('outputs/.packages/one/final.mp4',b'one')
        entry={**ident,'video_sha256':file_hash(first)}
        view=delivery_layout.present(self.root,entry,first)
        self.assertEqual(view,'outputs/MOG-20261030-001/ja/原片-2/final.mp4')
        self.assertTrue((self.root/view).samefile(first))
        delivery_layout.present(self.root,entry,first)
        self.assertEqual(list((self.root/view).parent.iterdir()),[self.root/view])
        with patch.object(delivery_layout.os,'link',side_effect=OSError('No hardlinks on this filesystem')):
            delivery_layout.present(self.root,entry,first)
        self.assertFalse((self.root/view).samefile(first))
        self.assertEqual(file_hash(self.root/view),entry['video_sha256'])
        second=self.file('outputs/.packages/two/final.mp4',b'two')
        delivery_layout.present(self.root,{**entry,'video_sha256':file_hash(second)},second)
        self.assertEqual((self.root/view).read_bytes(),b'two')
        self.assertEqual(first.read_bytes(),b'one')
        # A new render/run ID must not create another visible task/version folder.
        stable=[]
        for suffix in ('v1','v2'):
            generic=self.root/'runs'/f'ad-{suffix}'
            write_json(generic/'run.json',{'source':'inputs/source.mp4','source_name':'advert.mp4','source_sha256':'b'*64})
            write_json(generic/'inputs/request.json',{'target_language':'de'})
            stable.append(delivery_layout.identity(generic))
        self.assertEqual(stable[0],stable[1])
