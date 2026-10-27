"""Demand grain, evidence, recovery, ETA cohorts and concurrent ownership."""
import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'workbench'))
from collector import Collector
from store import Store
from video_localizer.ledger import Ledger, Conflict


def sha(value):
    return hashlib.sha256(value).hexdigest()


class LedgerTests(unittest.TestCase):
    def setUp(self):
        folder = Path(__file__).resolve().parents[1] / 'work/test-tmp'
        folder.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='ledger-', dir=folder)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root)
        self.collector = Collector(self.root, self.store)
        self.ledger = self.collector.ledger
        self.put('AGENTS.md', b'fixture')
        self.entries = []

    def put(self, path, data):
        path = self.root/path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data,bytes) else json.dumps(data).encode())

    def fixture(self):
        videos = []
        for index in [1,2]:
            source = sha(('source'+str(index)).encode())
            members = [f'ACM-20261027-001-{index}-{i:02}' for i in [1,2,3]]
            for name,locale in zip(members,['es','fr','ja']):
                base='runs/'+name
                self.put(base+'/run.json', {'id':name,'source_sha256':source,'created_at':'2026-10-27T08:01:00Z'})
                self.put(base+'/inputs/request.json', {'target_language':locale})
            batch={'id':f'ACM-20261027-001-{index}','source_sha256':source,'request_budget':'budget','members':members,'targets':['es','fr','ja']}
            self.put('state/batches/'+batch['id']+'.json',batch)
            videos.append({'index':index,'title':batch['id'],'source':{'sha256':source},'targets':['es','fr','ja'],'members':members})
        self.put('state/budgets/budget.json', {'id':'budget','created_at':'2026-10-27T08:00:00Z','authorization_ref':'human-uuid','runs':{n:v['source']['sha256'] for v in videos for n in v['members']}})
        self.fireplay={'code':'ACM-20261027-001','requirement_id':'req1','content_version':'v1','targets':['es','fr','ja'],
                       'created_at':'2026-10-27T07:59:00Z','budget':'budget','videos':videos,'blockers':[],
                       'snapshot':{'row':{'createdAt':'2026-10-27T07:00:00Z'},'brief':{}}}
        self.put('state/fireplay/ACM-20261027-001/request.json', self.fireplay)

    def delivery(self, index, locale, status='delivered_with_issues', audio=None):
        v=self.fireplay['videos'][index-1]
        n=v['members'][['es','fr','ja'].index(locale)]
        folder=f'outputs/test/{n}'
        video=b'encoded '+n.encode()
        metadata={'origin_run_id':n,'source_sha256':v['source']['sha256'],'target_language':locale,
                  'video_sha256':sha(video),'status':status,'technical_decision':'pass' if status=='delivered' else 'revise'}
        self.put(folder+'/final.mp4',video)
        self.put(folder+'/manifest.json',{'kind':'delivery','metadata':metadata})
        self.put(folder+'/payload/inputs/request.json',{'target_language':locale,'require_target_audio':bool(audio)})
        self.put(folder+'/payload/analysis/inventory.json',{'audio':{'has_speech':bool(audio)}})
        self.put(folder+'/payload/outputs/completion.json',{'speech_mode':audio or 'none','completed_at':'2026-10-27T09:00:00Z'})
        self.entries.append({**metadata,'package':folder,'manifest_sha256':self.store.sha(folder+'/manifest.json'),'archived_at':'2026-10-27T09:01:00Z'})
        self.put('outputs/index.json', {'entries':self.entries})

    def req(self):
        return next(r for r in self.ledger.view()['requirements'] if r['id']=='fireplay:req1')

    def action(self,action,**kwargs):
        return self.ledger.action(action,{'requirement_id':'fireplay:req1',**kwargs},'op-'+__import__('uuid').uuid4().hex)

    def test_multivideo_scope_dedup_partial_outputs_and_restart(self):
        self.fixture()
        for video,locale in [(1,'es'),(1,'fr'),(1,'ja'),(2,'es')]: self.delivery(video,locale)
        self.collector.sync()
        req=self.req()
        self.assertEqual((req['video_count'],req['task_count'],req['output_count']),(2,6,4))
        self.assertIsNone(req['complete_at'])
        self.assertEqual(len(self.ledger.view()['requirements']),1)
        self.assertEqual(req['quality_count'],0)
        with self.ledger.connection() as db: before=db.execute('SELECT COUNT(*) FROM events').fetchone()[0]
        self.collector.sync()
        self.assertEqual(self.req()['first_seen_at'], req['first_seen_at'])
        with self.ledger.connection() as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0],before)
        self.assertEqual(Ledger(self.root).detail('fireplay:req1')['requirement']['output_count'],4)

    def test_all_output_quality_hold_and_required_audio(self):
        self.fixture()
        for i in [1,2]:
            for locale in ['es','fr','ja']: self.delivery(i,locale)
        self.collector.sync()
        self.assertEqual(self.req()['state'],'complete')
        entry=self.entries[0]
        self.put('knowledge/local/quality-holds/'+entry['source_sha256']+'/'+entry['video_sha256']+'/index.json',{'entries':[]})
        self.collector.sync()
        self.assertEqual(self.req()['output_count'],6)
        self.assertTrue(any(t['quality']=='hold' for t in self.ledger.detail('fireplay:req1')['tasks']))
        self.put(entry['package']+'/payload/inputs/request.json',{'require_target_audio':True})
        self.put(entry['package']+'/payload/analysis/inventory.json',{'audio':{'has_speech':True}})
        self.put(entry['package']+'/payload/outputs/completion.json',{'speech_mode':'subtitled','completed_at':'2026-10-27T09:00:00Z'})
        self.collector.sync()
        self.assertEqual(self.req()['output_count'],5)

    def test_hash_tampering_does_not_count_output(self):
        self.fixture();self.delivery(1,'es')
        self.put(self.entries[0]['package']+'/final.mp4',b'changed')
        self.collector.sync()
        self.assertEqual(self.req()['output_count'],0)

    def test_scope_revision_keeps_old_estimate_and_completion(self):
        self.fixture()
        for i in [1,2]:
            for locale in ['es','fr','ja']: self.delivery(i,locale)
        self.collector.sync();old=self.req()
        self.action('eta',lower_at='2030-01-01T08:00:00Z',upper_at='2030-01-01T09:00:00Z',reason='rule estimate')
        self.fireplay['videos'][0]['targets'].append('de')
        self.fireplay['content_version']='v2'
        self.put('state/fireplay/ACM-20261027-001/request.json',self.fireplay)
        self.collector.sync();new=self.req()
        self.assertNotEqual(new['scope_id'],old['scope_id'])
        self.assertIsNone(new['first_eta'])
        self.assertIsNone(new['complete_at'])
        detail=self.ledger.detail('fireplay:req1')
        self.assertEqual(len(detail['estimates']),1)
        self.assertEqual(len(detail['scopes']),2)

    def test_claim_atomicity_per_video_idempotency_and_expiry(self):
        self.fixture();self.collector.sync()
        def claim(i):
            try: return self.action('claim',video_id='video:1',owner='agent',session=str(i))
            except Conflict: return None
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(claim,[1,2]))
        self.assertEqual(sum(bool(r) for r in results),1)
        self.action('claim',video_id='video:2',owner='other',session='other')
        self.assertEqual(len(self.req()['claims']),2)
        spec={'requirement_id':'fireplay:req1','reason':'waiting for model','kind':'model'}
        first=self.ledger.action('block',spec,'stable-operation')
        self.assertEqual(self.ledger.action('block',spec,'stable-operation'),first)
        with self.assertRaises(Conflict):self.ledger.action('block',{**spec,'reason':'changed'},'stable-operation')
        stale=self.ledger.view('2030-01-01T00:00:00Z')['requirements'][0]
        self.assertEqual(stale['agent_health'],'unconfirmed')
        self.collector.sync()
        self.assertEqual(self.req()['state'],'blocked')

    def test_eta_matured_cohort_includes_unfinished_and_coverage(self):
        self.fixture();self.collector.sync()
        with patch('video_localizer.ledger.now', return_value='2026-10-27T08:00:00+00:00'):
            self.action('eta',lower_at='2026-10-27T09:00:00Z',upper_at='2026-10-27T10:00:00Z',reason='first')
            self.action('eta',lower_at='2026-10-27T11:00:00Z',upper_at='2026-10-27T12:00:00Z',reason='queue changed')
        view=self.ledger.view('2026-10-27T11:00:00Z');r=view['requirements'][0]
        self.assertFalse(r['overdue'])
        m=self.ledger.metrics(view['requirements'],at='2026-10-27T11:00:00Z')
        self.assertEqual((m['eta_due'],m['eta_ontime'],m['eta_covered']),(1,0,1))
        self.assertEqual(r['first_eta']['data']['reason'],'first')
        self.assertEqual(r['latest_eta']['data']['reason'],'queue changed')
        self.assertIsNone(m['cycle_median_seconds'])

    def test_corrupt_input_is_partial_without_erasing_history(self):
        self.fixture();self.collector.sync()
        self.put('state/fireplay/ACM-20261027-001/request.json',b'{')
        self.collector.sync()
        self.assertFalse(self.ledger.view()['sync']['complete'])
        self.assertTrue(any(r['id']=='fireplay:req1' for r in self.ledger.view()['requirements']))

    def test_incremental_timing_and_backup_restore(self):
        self.fixture()
        name=self.fireplay['videos'][0]['members'][0]
        self.put('state/timing/'+name+'/event.json',{'id':'timing1','run':name,'stage':'render','parent_id':None,
                  'started_at':'2026-10-27T08:00:00Z','ended_at':'2026-10-27T08:01:00Z','seconds':60,'status':'completed'})
        self.collector.sync();self.collector.sync()
        events=self.ledger.detail('fireplay:req1')['events']
        self.assertEqual(sum(e['kind']=='stage_recorded' for e in events),1)
        self.action('eta',lower_at='2030-01-01T08:00:00Z',upper_at='2030-01-01T09:00:00Z',reason='restore evidence')
        destination=self.root/'state/ledger/backups/backup.sqlite3'
        self.ledger.backup(destination)
        with sqlite3.connect(destination) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM requirements').fetchone()[0],1)
        restored=self.root/'restore-check'
        target=restored/'state/ledger/ledger.sqlite3'
        target.parent.mkdir(parents=True)
        import shutil
        shutil.copyfile(destination,target)
        recovered=Ledger(restored).detail('fireplay:req1')
        self.assertEqual(recovered['requirement']['first_eta']['data']['reason'],'restore evidence')
        self.assertEqual(len(recovered['tasks']),6)
        self.assertTrue(any(e['kind']=='stage_recorded' for e in recovered['events']))
        with self.assertRaises(ValueError):self.ledger.backup(self.root/'outside.sqlite3')

    def test_unrelated_same_source_stays_unlinked(self):
        self.fixture()
        self.put('runs/unrelated/run.json',{'id':'unrelated','source_sha256':self.fireplay['videos'][0]['source']['sha256']})
        self.put('runs/unrelated/inputs/request.json',{'target_language':'es'})
        self.collector.sync()
        rows=self.ledger.view()['requirements']
        self.assertEqual(len(rows),2)
        self.assertFalse(next(r for r in rows if r['id']=='unlinked:unrelated')['countable'])
        self.assertEqual(self.ledger.metrics(rows)['requirements'],1)

    def test_rule_eta_updates_only_on_new_evidence_and_respects_manual_eta(self):
        self.fixture()
        self.put('config/ledger.json',{'auto_eta':True,'eta_rule_version':'test-v1',
                  'queue_allowance_minutes':[0,0],'shared_source_minutes':[1,2],'per_locale_minutes':[1,2]})
        self.collector.sync()
        first=self.req()['first_eta']['id']
        self.assertTrue(all(v['latest_eta'] for v in self.req()['videos']))
        self.collector.sync()
        self.assertEqual(len(self.ledger.detail('fireplay:req1')['estimates']),3)
        name=self.fireplay['videos'][0]['members'][0]
        self.put('runs/'+name+'/analysis/inventory.json',{'coverage':{'visual':{'status':'pending'}}})
        self.collector.sync()
        self.assertEqual(self.req()['first_eta']['id'],first)
        self.assertEqual(self.req()['eta_changes'],1)
        self.action('eta',lower_at='2030-01-01T08:00:00Z',upper_at='2030-01-01T09:00:00Z',reason='agent actual assessment',basis='agent_estimate')
        manual=self.req()['latest_eta']['id']
        self.put('runs/'+name+'/plan.json',{'id':'plan'})
        self.collector.sync()
        self.assertEqual(self.req()['latest_eta']['id'],manual)

    def test_manual_registration_does_not_create_production_or_budget(self):
        spec={'code':'MANUAL-001','reason':'real user request','videos':[{'source_sha256':sha(b'actual source'),'targets':['es','fr']}]}
        result=self.ledger.action('register',spec,'register-operation')
        self.assertEqual(self.ledger.action('register',spec,'register-operation'),result)
        self.collector.sync()
        req=self.ledger.view()['requirements'][0]
        self.assertEqual((req['task_count'],req['run_count']),(2,0))
        self.assertFalse((self.root/'runs').exists())
        self.assertFalse((self.root/'state/budgets').exists())

    def test_executor_activity_is_distinct_from_agent_heartbeat(self):
        from video_localizer.timing import measure
        self.fixture()
        name=self.fireplay['videos'][0]['members'][0]
        with measure(self.root/'runs'/name,'fixture.stage'):
            pass
        self.collector.sync()
        req=self.req()
        self.assertEqual(req['agent_health'],'unrecorded')
        self.assertEqual(req['executors'][0]['health'],'finished')
        self.assertEqual(req['claims'],[])

    def test_collector_does_not_rewrite_source_records(self):
        self.fixture()
        def source_hashes():
            return {p.relative_to(self.root).as_posix():sha(p.read_bytes()) for p in self.root.rglob('*') if p.is_file() and 'state/ledger/' not in p.as_posix()}
        before=source_hashes()
        self.collector.sync()
        self.collector.sync()
        self.assertEqual(before,source_hashes())

    def test_completion_discovered_after_forecast_cannot_inflate_accuracy(self):
        self.fixture();self.collector.sync()
        with patch('video_localizer.ledger.now',return_value='2026-10-27T10:00:00+00:00'):
            self.action('eta',lower_at='2030-01-01T08:00:00Z',upper_at='2030-01-01T09:00:00Z',reason='output was not linked yet')
        for i in [1,2]:
            for locale in ['es','fr','ja']:self.delivery(i,locale)
        self.collector.sync()
        rows=self.ledger.view('2031-01-01T00:00:00Z')['requirements']
        m=self.ledger.metrics(rows,at='2031-01-01T00:00:00Z')
        self.assertEqual(m['eta_due'],0)
        self.assertEqual(m['eta_covered'],0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
