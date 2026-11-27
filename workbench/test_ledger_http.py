"""Loopback write boundary and refresh/restart behavior in disposable state."""
import http.client
import ipaddress
import json
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
import test_ledger as ledger_fixtures
from server import WorkbenchServer
from source_capacity import project_capacity
from unittest.mock import patch


class LedgerHTTPTests(unittest.TestCase):
    setUp=ledger_fixtures.LedgerTests.setUp
    put=ledger_fixtures.LedgerTests.put
    fixture=ledger_fixtures.LedgerTests.fixture

    def server(self, **options):
        self.fixture()
        server=WorkbenchServer(('127.0.0.1',0),self.root,**options)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        server.collector.sync()
        client=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=10)
        self.addCleanup(client.close)
        return server,client

    def test_write_requires_origin_token_and_revision_then_deduplicates(self):
        server,client=self.server()
        client.request('GET','/api/ledger')
        response=client.getresponse();self.assertEqual(response.status,200)
        view=json.loads(response.read());token=view['csrf_token']
        r=view['requirements'][0]
        self.assertEqual(r['progress_state'], 'active')
        body=json.dumps({'action':'block','operation_id':'stable-http-operation','expected_revision':r['revision'],
                         'data':{'requirement_id':r['id'],'kind':'model','reason':'existing task pending'}})
        def post(headers):
            client.request('POST','/api/ledger/action',body=body,headers=headers)
            response=client.getresponse();status=response.status;data=json.loads(response.read());return status,data
        headers={'Content-Type':'application/json','Origin':f'http://127.0.0.1:{server.server_port}','X-Ledger-Token':token}
        self.assertEqual(post({})[0],403)
        self.assertEqual(post({**headers,'Origin':'https://example.com'})[0],403)
        status,result=post(headers);self.assertEqual(status,200)
        self.assertEqual(post(headers),(status,result))
        client.request('GET','/api/ledger/detail?id='+r['id'])
        response=client.getresponse();detail=json.loads(response.read())
        self.assertEqual(detail['requirement']['state'],'blocked')
        self.assertEqual(detail['requirement']['progress_state'], 'blocked')
        self.assertTrue(any(e['kind']=='block' for e in detail['events']))
        for progress, expected in [('blocked', [r['id']]), ('active', [])]:
            client.request('GET', '/api/ledger?view=list&progress='+progress)
            response = client.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual([row['id'] for row in json.loads(response.read())['requirements']], expected)
        self.put('state/fireplay/monitor/state.json', {'requirements': {'req1': {
            'row': {'id': 'req1', 'code': self.fireplay['code'], 'status': 'completed'},
            'last_seen_at': '2026-11-24T01:00:00Z',
        }}})
        client.request('GET', '/api/ledger?view=list&progress=done')
        result = json.loads(client.getresponse().read())
        self.assertEqual([row['id'] for row in result['requirements']], [r['id']])
        self.assertEqual(result['metrics']['blocked'], 0)
        self.assertIsNone(result['requirements'][0]['platform']['verified'])
        client.request('GET', '/api/ledger?view=list&progress=blocked')
        self.assertEqual(json.loads(client.getresponse().read())['requirements'], [])

    def test_filters_metrics_and_static_files(self):
        server,client=self.server()
        client.request('GET','/api/ledger?q=absent')
        response=client.getresponse();result=json.loads(response.read())
        self.assertEqual(result['requirements'],[])
        self.assertEqual(result['metrics']['requirements'],0)
        self.assertTrue(result['benchmark']['enabled'])
        self.assertEqual(result['benchmark']['samples'], [])
        self.assertEqual(result['benchmark']['baseline_excluded'], 1)
        self.assertEqual(result['metrics']['eta_ontime_rate'],None)
        for url in ['/ledger.js','/ledger.css']:
            client.request('GET',url);response=client.getresponse()
            self.assertEqual(response.status,200);self.assertTrue(response.read())
        client.request('GET','/api/media?path=state/ledger/ledger.sqlite3')
        response=client.getresponse();self.assertEqual(response.status,400);response.read()

    def test_lan_access_without_login_is_read_only(self):
        server, client = self.server(lan_interface=ipaddress.ip_interface('127.0.0.2/32'),
                                     lan_allow=[ipaddress.ip_network('127.0.0.1/32')])
        host = f'127.0.0.2:{server.server_port}'
        headers = {'Host': host}
        client.request('GET', '/', headers=headers)
        response = client.getresponse()
        self.assertEqual(response.status, 200)
        self.assertIsNone(response.getheader('WWW-Authenticate'))
        self.assertIn(b'data-access="lan"', response.read())
        for path in ('/api/ledger?view=list', '/api/console/config'):
            client.request('GET', path, headers=headers)
            response = client.getresponse()
            self.assertEqual(response.status, 200)
            self.assertNotIn('csrf_token', json.loads(response.read()))
        client.request('POST', '/api/ledger/action', body='{}', headers=headers)
        response = client.getresponse()
        self.assertEqual(response.status, 403)
        response.read()
        server.lan_networks = (server.lan_interface.network,)
        client.request('GET', '/', headers={**headers, 'X-Forwarded-For': '127.0.0.2'})
        response = client.getresponse()
        self.assertEqual(response.status, 403)
        response.read()

    def test_list_reads_skip_benchmark(self):
        server, client = self.server()
        client.request('GET', '/api/ledger?view=list')
        response = client.getresponse()
        result = json.loads(response.read())
        self.assertEqual(response.status, 200)
        self.assertNotIn('benchmark', result)
        self.assertEqual(result['metrics']['requirements'], 1)
        self.assertIn('csrf_token', result)
        client.request('GET', '/api/ledger?view=efficiency')
        response = client.getresponse()
        self.assertTrue(json.loads(response.read())['benchmark']['enabled'])

    def test_list_and_detail_show_only_current_platform_verified_reuses(self):
        _, client = self.server()
        folder = 'state/fireplay/' + self.fireplay['code']
        request_hash = ledger_fixtures.sha((self.root / folder / 'request.json').read_bytes())
        video_hash = ledger_fixtures.sha(b'reviewed historical video')
        material_id = '00000000-0000-0000-0000-000000000001'
        self.put(folder + '/completion-check.json', {
            'requirement_id': 'req1', 'code': self.fireplay['code'], 'content_version': 'v1',
            'request_sha256': request_hash, 'expected_count': 6, 'verified_count': 1,
            'verified': [{'video_index': 1, 'locale': 'es', 'sha256': video_hash, 'material_id': material_id}],
        })
        package = {'locale': 'es', 'video_index': 1, 'sha256': video_hash,
                   'historical_reuse': {'mode': 'fireplay_translation_reuse', 'old_requirement_code': 'ACM-20261025-001'}}
        outbox = {'requirement_id': 'req1', 'content_version': 'v1', 'video_index': 1, 'packages': [package],
                  'operations': {'import-1': {'state': 'verified', 'result': {'material_id': material_id}}}}
        path = folder + '/return-1.json'
        self.put(path, outbox)
        for url in ('/api/ledger?view=list', '/api/ledger/detail?id=fireplay:req1'):
            client.request('GET', url)
            response = client.getresponse()
            self.assertEqual(response.status, 200)
            data = json.loads(response.read())
            row = data['requirement'] if 'requirement' in data else data['requirements'][0]
            self.assertEqual(row['reuses'], [
                {'locale': 'es', 'video_id': 'video:1', 'source_requirement_code': 'ACM-20261025-001'},
            ])
            self.assertEqual(row['output_count'], 0)
            self.assertEqual(row['upload_count'], 1)
            self.assertEqual(row['platform']['verified'], 1)
        for replacement in (
            {**outbox, 'content_version': 'old'},
            {**outbox, 'packages': [{**package, 'sha256': 'a' * 64}]},
            {**outbox, 'operations': {'import-1': {'state': 'verified', 'result': {'material_id': 'other'}}}},
            {**outbox, 'deferred_uploads': {'es': {}}},
        ):
            self.put(path, replacement)
            client.request('GET', '/api/ledger?view=list')
            self.assertEqual(json.loads(client.getresponse().read())['requirements'][0]['reuses'], [])

    def test_partial_uploads_survive_batch_extension_without_marking_whole_demand_done(self):
        server, client = self.server()
        folder = 'state/fireplay/' + self.fireplay['code']
        video_hash = ledger_fixtures.sha(b'first verified video')
        material_id = '00000000-0000-0000-0000-000000000001'
        new_id = '00000000-0000-0000-0000-000000000002'
        binding = {'state': 'verified', 'result': {'material_ids': [material_id]}}
        outbox = {'requirement_id': 'req1', 'content_version': 'v1', 'video_index': 1, 'state': 'ready',
                  'packages': [{'locale': 'es', 'video_index': 1, 'sha256': video_hash},
                               {'locale': 'fr', 'video_index': 1, 'sha256': 'a' * 64}],
                  'operations': {'bind': {'state': 'unknown'},
                                 'import-1': {'state': 'verified', 'result': {'material_id': material_id}},
                                 'verify-1': {'state': 'verified'},
                                 'import-2': {'state': 'verified', 'result': {'material_id': new_id}},
                                 'verify-2': {'state': 'verified'}},
                  'binding_history': [binding]}
        path = folder + '/return-1.json'
        self.put(path, outbox)
        client.request('GET', '/api/ledger?view=list')
        row = json.loads(client.getresponse().read())['requirements'][0]
        self.assertEqual(row['upload_count'], 1)
        self.assertNotEqual(row['progress_state'], 'done')
        self.assertEqual(row['platform']['state'], 'unrecorded')
        self.assertIsNone(row.get('delivery_at'))
        client.request('GET', '/api/ledger/detail?id=fireplay:req1')
        tasks = json.loads(client.getresponse().read())['tasks']
        self.assertEqual([(task['video_id'], task['locale'], task['uploaded_sha256'])
                          for task in tasks if 'uploaded_sha256' in task], [('video:1', 'es', video_hash)])
        video = self.fireplay['videos'][0]
        task = {'state': 'delivered', 'current_video_sha256': video_hash, 'source_sha256': video['source']['sha256']}
        self.assertTrue(server.console.run_publication([self.fireplay], video['members'][0], 'es', task))
        self.assertIsNone(server.console.run_publication([self.fireplay], video['members'][1], 'fr',
                                                         {**task, 'current_video_sha256': 'a' * 64}))
        self.put(path, {**outbox, 'content_version': 'old'})
        client.request('GET', '/api/ledger?view=list')
        self.assertIsNone(json.loads(client.getresponse().read())['requirements'][0]['upload_count'])

    def test_legacy_benchmark_is_fixed_and_history_only(self):
        snapshot = json.loads(Path(__file__).with_name('legacy-benchmark.json').read_text(encoding='utf-8'))
        self.put('workbench/legacy-benchmark.json', snapshot)
        server, client = self.server()
        for query in ['days=7', 'days=90&q=absent']:
            client.request('GET', '/api/ledger?view=history&'+query)
            response = client.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read())['legacy_benchmark'], snapshot)
        client.request('GET', '/api/ledger?view=list')
        self.assertNotIn('legacy_benchmark', json.loads(client.getresponse().read()))
        (self.root / 'workbench/legacy-benchmark.json').unlink()
        client.request('GET', '/api/ledger?view=history')
        response = client.getresponse()
        self.assertEqual(response.status, 200)
        self.assertIsNone(json.loads(response.read())['legacy_benchmark'])

    def test_capacity_counts_originals_and_distinguishes_queue_from_preparation(self):
        self.put('config/fireplay-parallel.json', {'enabled': True, 'max_active_sources_global': 10,
                                                  'max_active_sources_per_requirement': None})
        self.put('state/fireplay/monitor/state.json', {'requirements': {}})
        originals = [
            {'video_index': 1, 'state': 'reserved', 'source_registered': True},
            {'video_index': 2, 'state': 'unclaimed', 'source_registered': True},
            {'video_index': 3, 'state': 'unclaimed', 'source_registered': True},
            {'video_index': 4, 'state': 'unclaimed', 'source_registered': False},
        ]
        active = {('fixture', index) for index in range(5, 13)} | {('fixture', 1)}
        with patch('source_capacity.active_sources', return_value=active), patch(
                'source_capacity.dispatch_queue', return_value=[
                    {'id': 'fixture', 'code': 'APC-20261124-001', 'sources': originals}]):
            snapshot = project_capacity(self.root)
        self.assertEqual(snapshot['active_source_count'], 9)
        self.assertEqual(snapshot['available_source_slots'], 1)
        queue = snapshot['queue']
        self.assertEqual((queue['ready'], queue['waiting'], queue['preparing']), (1, 1, 1))
        self.assertEqual([entry['video_index'] for entry in queue['sources']], [2, 3, 4])

if __name__=='__main__':
    unittest.main(verbosity=2)
