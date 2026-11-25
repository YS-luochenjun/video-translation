"""Loopback write boundary and refresh/restart behavior in disposable state."""
import http.client
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

    def server(self):
        self.fixture()
        server=WorkbenchServer(('127.0.0.1',0),self.root)
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
