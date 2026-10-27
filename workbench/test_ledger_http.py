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
        self.assertTrue(any(e['kind']=='block' for e in detail['events']))

    def test_filters_metrics_and_static_files(self):
        server,client=self.server()
        client.request('GET','/api/ledger?q=absent')
        response=client.getresponse();result=json.loads(response.read())
        self.assertEqual(result['requirements'],[])
        self.assertEqual(result['metrics']['requirements'],0)
        self.assertEqual(result['metrics']['eta_ontime_rate'],None)
        for url in ['/ledger.js','/ledger.css']:
            client.request('GET',url);response=client.getresponse()
            self.assertEqual(response.status,200);self.assertTrue(response.read())
        client.request('GET','/api/media?path=state/ledger/ledger.sqlite3')
        response=client.getresponse();self.assertEqual(response.status,400);response.read()


if __name__=='__main__':
    unittest.main(verbosity=2)
