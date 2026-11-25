"""Console authorization, project boundaries, artifact identity and durable dispatch."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
import http.client
import threading
import sys
from pathlib import Path

from console_data import ConsoleData
from console_dispatch import prepare, acknowledge
from console_timeline import chains
from console_panel import handoff, notified, read_api
from console_events import EventHub
from material_launch import plan as plan_launch, record as record_launch
from video_localizer.ledger import now


class ConsoleTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parents[1]/'work/test-tmp'
        parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)/'project';self.root.mkdir()
        self.home = Path(self.tmp.name)/'codex';self.home.mkdir()
        with sqlite3.connect(self.home/'state_5.sqlite') as db:
            db.execute('CREATE TABLE threads(id,name,title,cwd,archived,updated_at,created_at,rollout_path,source)')
            for n in range(17):
                db.execute('INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?)',
                           (f'thread-{n}', f'会话 {n}', f'原题 {n}', str(self.root), 0, n, 0, '', 'vscode'))
            db.execute('INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?)', ('outside', '其他项目', '', '/another', 0, 999, 0, '', 'vscode'))
        self.data = ConsoleData(self.root, codex_home=self.home)

    def put(self, path, value):
        p = self.root/path;p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(value, ensure_ascii=False));return p

    def fixture_artifact(self):
        self.put('state/fireplay/ABC-20261102-001/request.json', {'code': 'ABC-20261102-001',
                 'chat': {'threadId': 'thread-1'}, 'videos': [{'members': ['run-1']}]})
        p = self.root/'runs/run-1/assets/clean-base.jpg';p.parent.mkdir(parents=True);p.write_bytes(b'original image')
        return p

    def test_eight_per_page_search_all_and_project_isolation(self):
        self.assertEqual(len(self.data.overview()['sessions']), 8)
        self.assertEqual(self.data.overview()['total'], 17)
        self.assertEqual(len(self.data.overview(page=3)['sessions']), 1)
        self.assertEqual(self.data.overview(query='会话 0')['total'], 1)
        self.assertEqual(self.data.overview(page=900)['page'], 3)
        with self.assertRaises(ValueError):self.data.thread('outside')

    def test_missing_runtime_observation_is_never_idle(self):
        self.assertEqual(self.data.overview()['sessions'][0]['status'], 'unobserved')
        self.assertFalse(self.data.overview()['sessions'][0]['status_fresh'])

    def test_order_uses_user_input_not_execution_or_heartbeat(self):
        logs = {}
        for number in (1, 2):
            path = self.home/f'sessions/thread-{number}.jsonl'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch();logs[number] = path
            with sqlite3.connect(self.home/'state_5.sqlite') as db:
                db.execute('UPDATE threads SET rollout_path=? WHERE id=?', (str(path), f'thread-{number}'))

        def append(number, minute, role, text):
            with logs[number].open('a') as stream:
                stream.write(json.dumps({'timestamp': f'2026-11-03T00:{minute}:00Z', 'type': 'response_item',
                    'payload': {'type': 'message', 'role': role, 'content': [{'type': 'input_text' if role == 'user' else 'output_text', 'text': text}]}})+'\n')

        append(1, '01', 'user', '第一个问题')
        append(2, '02', 'user', '第二个问题')
        self.assertEqual([r['id'] for r in self.data.overview()['sessions'][:2]], ['thread-2', 'thread-1'])
        append(1, '03', 'assistant', '仍在执行')
        append(1, '04', 'user', '<heartbeat>自动检查</heartbeat>')
        append(1, '05', 'user', '# AGENTS.md instructions')
        append(1, '06', 'user', '<external_codex_apps_open_page>{"page_id":null}</external_codex_apps_open_page>')
        with sqlite3.connect(self.home/'state_5.sqlite') as db:
            db.execute('UPDATE threads SET updated_at=9999999999 WHERE id=?', ('thread-1',))
        self.data.cache.clear()
        self.assertEqual([r['id'] for r in self.data.overview()['sessions'][:2]], ['thread-2', 'thread-1'])
        append(1, '07', 'user', '新的用户问题')
        self.assertEqual([r['id'] for r in self.data.overview()['sessions'][:2]], ['thread-1', 'thread-2'])
        self.assertEqual(self.data.overview()['sessions'][0]['last_user_message_at'], 1793664420)
        append(2, '08', 'assistant', 'x'*(2*1024*1024))
        fresh = ConsoleData(self.root, codex_home=self.home)
        self.assertEqual([r['id'] for r in fresh.overview()['sessions'][:2]], ['thread-1', 'thread-2'])
        next_input = json.dumps({'timestamp': '2026-11-03T00:09:00Z', 'type': 'event_msg',
                                'payload': {'type': 'user_message', 'message': '新的实际提问'}})
        with logs[2].open('a') as stream: stream.write(next_input)
        self.assertEqual(fresh.overview()['sessions'][0]['id'], 'thread-1')
        with logs[2].open('a') as stream: stream.write('\n')
        self.assertEqual(fresh.overview()['sessions'][0]['id'], 'thread-2')

    def test_signed_queue_deduplicates_and_rejects_id_reuse(self):
        p = {'command_id': 'stable-command-0001', 'action': 'message', 'thread_id': 'thread-1', 'text': '继续当前任务'}
        first = self.data.enqueue(p)
        self.assertEqual(first, self.data.enqueue(p))
        with self.assertRaises(ValueError):self.data.enqueue({**p, 'text': '更改输入'})
        task = prepare(self.data)['commands'][0]
        self.assertEqual(task['args']['threadId'], 'thread-1')
        self.assertIn('stable-command-0001', task['args']['prompt'])
        self.assertEqual(task['tool'], 'send_message_to_thread')

    def test_unknown_is_not_automatically_redispatched(self):
        self.data.enqueue({'command_id': 'stable-command-0002', 'action': 'message', 'thread_id': 'thread-2', 'text': '检查'})
        self.assertEqual(len(prepare(self.data)['commands']), 1)
        second = prepare(self.data)
        self.assertEqual(second['commands'], [])
        self.assertEqual(second['unknown_do_not_resend'][0]['id'], 'stable-command-0002')
        acknowledge(self.data, 'stable-command-0002', {'native_receipt': 'verified'}, 'accepted')
        self.assertEqual(self.data.commands()[0]['status'], 'accepted')

    def test_tampered_queue_does_not_gain_user_authority(self):
        self.data.enqueue({'command_id': 'stable-command-0003', 'action': 'message', 'thread_id': 'thread-1', 'text': '原输入'})
        with self.data._db() as db:
            db.execute('UPDATE commands SET payload=?', (json.dumps({'action': 'message', 'thread_id': 'thread-1', 'text': '篡改'}),))
        self.assertEqual(prepare(self.data)['commands'], [])
        self.assertEqual(self.data.commands()[0]['status'], 'rejected')

    def test_artifact_node_ownership_hash_and_changed_version(self):
        p = self.fixture_artifact()
        rows = self.data.artifacts('run-1', [])
        self.assertEqual(rows[0]['node'], 'base')
        a = self.data.artifact('thread-1', 'run-1', rows[0]['id'])
        self.assertEqual(a['sha256'], hashlib.sha256(p.read_bytes()).hexdigest())
        with self.assertRaises(ValueError):self.data.artifact('thread-2', 'run-1', rows[0]['id'])
        p.write_bytes(b'changed image')
        with self.assertRaises(ValueError):
            self.data.enqueue({'command_id': 'stable-command-0004', 'action': 'message', 'thread_id': 'thread-1', 'text': '沿用这份',
                               'artifact': {'run_id': 'run-1', 'id': a['id'], 'sha256': a['sha256']}})

    def test_only_project_automations_are_exposed(self):
        folder = self.home/'automations/test';folder.mkdir(parents=True)
        p = folder/'automation.toml'
        p.write_text('id="test"\nname="本项目任务"\nstatus="ACTIVE"\ntarget_thread_id="thread-1"')
        self.assertEqual(len(self.data.automations()['automations']), 1)
        self.assertIsNone(self.data.automations()['knowledge_owner_id'])
        p.write_text('id="test"\nname="项目经验总结"\nstatus="ACTIVE"\ntarget_thread_id="thread-1"')
        self.assertEqual(self.data.automations()['knowledge_owner_id'], 'test')
        p.write_text('id="test"\nname="别的项目"\nstatus="ACTIVE"\ntarget_thread_id="outside"')
        self.assertEqual(self.data.automations()['automations'], [])

    def test_catalog_separates_active_history_and_private_review_placeholders(self):
        self.put('knowledge/index.json', {'entries': [
            {'id': 'new', 'path': 'knowledge/rules/new.md', 'status': 'active'},
            {'id': 'old', 'path': 'knowledge/rules/old.md', 'status': 'active', 'superseded_by': 'new'}]})
        self.put('knowledge/cases/index.json', {'entries': [
            {'id': 'case', 'path': 'knowledge/cases/case.md', 'status': 'active'}]})
        private_path = 'knowledge/local/candidates/private-title.json'
        self.put(private_path, {'hypothesis': 'Needs an evidence-backed lesson', 'private_text': 'private detail'})
        result = read_api(self.data, '/api/knowledge')
        self.assertEqual(result['view_counts'], {'method': 1, 'reference': 1, 'history': 1, 'candidate': 1})
        self.assertEqual(result['review_counts'], {'needs_lesson': 1})
        self.assertNotIn('private-title', json.dumps(result))
        self.assertNotIn('private detail', json.dumps(result))
        with self.assertRaises(ValueError):
            read_api(self.data, '/api/document?path='+private_path)

    def test_same_source_review_groups_preserve_locale_and_privacy(self):
        source = 'a' * 64
        hypothesis = 'Inspect the label through the shared transition.'
        for folder, locale, origin in [
            ('knowledge/candidates', 'de', source),
            ('knowledge/candidates', 'fr', source),
            ('knowledge/candidates', 'en', 'b' * 64),
            ('knowledge/local/candidates', 'es', source),
        ]:
            self.put(f'{folder}/{locale}.json', {'hypothesis': hypothesis, 'scope': {
                'source_sha256': origin, 'workflow': 'video-localization', 'target_language': locale}})
        entries = {entry['scope']['target_language']: entry for entry in read_api(self.data, '/api/knowledge')['entries']}
        self.assertEqual(entries['de']['review_group'], entries['fr']['review_group'])
        self.assertNotEqual(entries['de']['review_group'], entries['en']['review_group'])
        self.assertNotEqual(entries['de']['review_group'], entries['es']['review_group'])
        self.assertNotIn('summary', entries['es'])
        self.assertNotIn('path', {key: value for key, value in entries['es'].items() if value is not None})

    def test_knowledge_versions_claims_and_run_isolation(self):
        self.fixture_artifact()
        self.put('runs/run-1/run.json', {})
        text = '# 当时规则\n只用于此范围。'
        sha = hashlib.sha256(text.encode()).hexdigest()
        ref = {'path': 'knowledge/rules/one.md', 'sha256': sha}
        self.put('runs/run-1/plan.json', {'id': 'p1', 'knowledge_snapshot_version': 1, 'knowledge': [ref]})
        p = self.root/'runs/run-1/plans/p1/knowledge/01.md';p.parent.mkdir(parents=True);p.write_text(text)
        current = self.root/ref['path'];current.parent.mkdir(parents=True);current.write_text('# 已改版')
        packet = self.put('runs/run-1/analysis/codex/packets/a.json', {'stage': 'recognize', 'context': [{**ref, 'text': text}, {'path': '.env', 'text': 'private'}]})
        self.put('runs/run-1/analysis/codex/results/a.json', {'stage': 'recognize',
                 'packet': {'path': 'analysis/codex/packets/a.json', 'sha256': hashlib.sha256(packet.read_bytes()).hexdigest()},
                 'report': {'knowledge_read': [ref['path'], '.env']}})
        feedback = self.put('knowledge/local/feedback/knowledge-use/u1/feedback.json', {'plan_id': 'p1',
                            'uses': [{**ref, 'outcome': 'not_used', 'observation': '只是检索命中'}]})
        self.put('runs/run-1/review/knowledge-use/u1.json', {'path': str(feedback.relative_to(self.root)), 'sha256': hashlib.sha256(feedback.read_bytes()).hexdigest()})
        self.put('runs/other/plan.json', {'knowledge': [{'path': 'knowledge/other.md'}]})
        self.put('knowledge/candidates/run-1-lesson.json', {'id': 'run-1-lesson', 'hypothesis': '边界要核对',
                 'evidence': {'run': 'run-1'}, 'limitations': ['单源观察']})
        self.put('knowledge/candidates/run-1-wrong.json', {'evidence': {'run': 'other'}})
        d = self.data.detail('thread-1', 'run-1')
        rows = d['knowledge']
        self.assertEqual({r['state'] for r in rows}, {'frozen', 'provided', 'declared_read', 'usage', 'learned_candidate'})
        self.assertTrue(all(r['path'] in {ref['path'], 'knowledge/candidates/run-1-lesson.json'} for r in rows))
        self.assertTrue(all('_body_text' not in r for r in rows))
        frozen = next(r for r in rows if r['state'] == 'frozen')
        doc = self.data.knowledge_detail('thread-1', 'run-1', frozen['id'])
        self.assertEqual(doc['text'], text);self.assertEqual(doc['integrity'], 'matched')
        read = next(r for r in rows if r['state'] == 'declared_read')
        self.assertEqual(self.data.knowledge_detail('thread-1', 'run-1', read['id'])['text'], text)
        usage = next(r for r in rows if r['state'] == 'usage')
        self.assertEqual(usage['evidence'][0]['note']['outcome'], 'not_used')
        lesson = next(r for r in rows if r['state'] == 'learned_candidate')
        self.assertIn('边界要核对', self.data.knowledge_detail('thread-1', 'run-1', lesson['id'])['text'])
        with self.assertRaises(ValueError):self.data.knowledge_detail('thread-2', 'run-1', frozen['id'])
        p.write_text('changed')
        self.assertEqual(self.data.knowledge_detail('thread-1', 'run-1', frozen['id'])['integrity'], 'changed')

    def test_timeline_preserves_gaps_overlap_and_stale_activity(self):
        def event(kind, at, **data):
            return {'id': str(at)+kind, 'kind': kind, 'occurred_at': f'2026-11-03T00:{at}:00+00:00', 'data': data}
        events = [event('stage_recorded', '02', stage='cli.analyze', started_at='2026-11-03T00:00:00+00:00', ended_at='2026-11-03T00:02:00+00:00'),
                  event('stage_recorded', '03', stage='nested', parent_id='parent', started_at='2026-11-03T00:01:00+00:00', ended_at='2026-11-03T00:03:00+00:00'),
                  event('stage_recorded', '03', stage='parallel', started_at='2026-11-03T00:01:00+00:00', ended_at='2026-11-03T00:03:00+00:00'),
                  event('stage_recorded', '06', stage='cli.render', started_at='2026-11-03T00:05:00+00:00', ended_at='2026-11-03T00:06:00+00:00'),
                  event('executor.started', '07', stage='cli.capture', execution_id='open'),
                  event('executor.heartbeat', '08', stage='cli.capture', execution_id='open'),
                  event('claim', '00', stage='解析'), event('stage', '04', stage='合成')]
        from console_timeline import epoch
        lanes = chains(events, epoch('2026-11-03T00:20:00+00:00'))
        agent = next(l for l in lanes if l['kind'] == 'agent')['items']
        self.assertEqual(agent[0]['seconds'], 240)
        self.assertEqual(agent[-1]['state'], 'unconfirmed')
        self.assertEqual(agent[-1]['seconds'], 0)
        script = next(l for l in lanes if l['kind'] == 'executor')['items']
        self.assertEqual(len(script), 4)
        self.assertEqual(script[1]['overlap_seconds'], 60)
        self.assertEqual(script[2]['gap_before_seconds'], 120)
        self.assertEqual(script[-1]['state'], 'unconfirmed')
        self.assertEqual(script[-1]['seconds'], 60)
        fresh = chains(events, epoch('2026-11-03T00:08:30+00:00'))
        current = next(l for l in fresh if l['kind'] == 'executor')['items'][-1]
        self.assertEqual(current['state'], 'running')
        self.assertEqual(current['seconds'], 90)

        closed = chains([event('executor.started', '01', stage='cli.render', execution_id='done'),
                         event('executor.finished', '02', stage='cli.render', execution_id='done')],
                        epoch('2026-11-03T00:20:00+00:00'))
        self.assertEqual(closed[0]['items'][0]['seconds'], 60)
        self.assertEqual(closed[0]['items'][0]['state'], 'completed')

    def test_intake_has_one_active_command_for_exact_number(self):
        a = self.data.enqueue({'command_id': 'stable-intake-0001', 'action': 'intake', 'code': 'ABC-20261102-001'})
        b = self.data.enqueue({'command_id': 'stable-intake-0002', 'action': 'intake', 'code': 'ABC-20261102-001'})
        self.assertEqual(a['id'], b['id'])

    def test_click_handoff_is_single_use_and_not_a_dispatch_receipt(self):
        cid = 'click-handoff-0001'
        self.data.enqueue({'command_id': cid, 'action': 'message', 'thread_id': 'thread-1', 'text': '原始定向交办'})
        preview = handoff(self.data, cid)
        self.assertTrue(preview['can_notify'])
        self.assertIn('prepare --id '+cid, preview['prompt'])
        self.assertIn(sys.executable, preview['prompt'])
        self.assertNotIn('原始定向交办', preview['prompt'])
        first = handoff(self.data, cid, reserve=True)
        self.assertTrue(first['can_notify'])
        self.assertFalse(handoff(self.data, cid, reserve=True)['can_notify'])
        notified(self.data, cid, 'unknown')
        self.assertFalse(handoff(self.data, cid)['can_notify'])
        row = self.data.commands()[0]
        self.assertEqual(row['status'], 'queued')
        self.assertEqual(row['notification_state'], 'unknown')
        self.assertIsNone(row['receipt'])

    def test_handoff_rejects_tampered_signed_payload(self):
        cid = 'click-tamper-0001'
        self.data.enqueue({'command_id': cid, 'action': 'message', 'thread_id': 'thread-1', 'text': '原文'})
        with self.data._db() as db:
            row = db.execute('SELECT payload FROM commands WHERE id=?', (cid,)).fetchone()
            payload = json.loads(row['payload']);payload['text'] = '篡改'
            db.execute('UPDATE commands SET payload=? WHERE id=?', (json.dumps(payload), cid))
        with self.assertRaises(ValueError): handoff(self.data, cid, True)

    def test_click_prepare_leaves_other_queued_and_dispatching_commands_alone(self):
        for cid in ('exact-click-0001', 'other-queue-0001', 'other-active-001'):
            self.data.enqueue({'command_id': cid, 'action': 'sync', 'thread_id': 'thread-1'})
        # sync requests are separately identified; do not collapse different clicks.
        with self.data._db() as db:
            db.execute("UPDATE commands SET status='dispatching' WHERE id='other-active-001'")
        spec = prepare(self.data, 'exact-click-0001')
        self.assertEqual([c['command_id'] for c in spec['commands']], ['exact-click-0001'])
        self.assertEqual(spec['commands'][0]['tool'], 'wait_threads')
        self.assertEqual(spec['commands'][0]['args']['timeoutMs'], 0)
        rows = {r['id']: r['status'] for r in self.data.commands()}
        self.assertEqual(rows['other-queue-0001'], 'queued')
        self.assertEqual(rows['other-active-001'], 'dispatching')
        self.assertFalse(prepare(self.data, 'exact-click-0001')['commands'])
        self.assertEqual({r['id']: r['status'] for r in self.data.commands()}['exact-click-0001'], 'unknown')

    def test_panel_api_does_not_expose_server_token_or_arbitrary_paths(self):
        self.assertNotIn('token', read_api(self.data, '/api/console/config'))
        for path in ('https://example.com/api/console/config', '/api/media?path=.env', '/api/ledger'):
            with self.assertRaises(ValueError): read_api(self.data, path)

    def requirement_fixture(self):
        request = {'code': 'ABC-20261103-001', 'requirement_id': 'real-id', 'content_version': 'v1',
                   'created_at': '2026-11-03T00:00:00Z', 'chat': {'threadId': 'thread-1'},
                   'targets': ['es', 'ja'], 'videos': [{'index': 1, 'targets': ['es', 'ja']}],
                   'snapshot': {'row': {'description': '真实需求正文', 'status': 'not_started'}}}
        path = self.put('state/fireplay/ABC-20261103-001/request.json', request)
        ledger = {'id': 'fireplay:real-id', 'code': request['code'], 'content_version': 'v1',
                  'origin': 'fireplay', 'state': 'complete', 'countable': True, 'task_count': 2, 'output_count': 2,
                  'quality_count': 0, 'issue_count': 2, 'stage_counts': {'delivered_with_issues': 2},
                  'scope': [{'targets': ['es', 'ja']}], 'threads': [{'threadId': 'thread-1'}, {'threadId': 'outside'}]}
        self.data.ledger_rows = lambda: [ledger]
        return path, request, ledger

    def test_requirement_board_separates_output_quality_and_platform_completion(self):
        self.requirement_fixture()
        row = self.data.requirement_board()['requirements'][0]
        self.assertEqual(row['state'], 'output')
        self.assertEqual(row['progress_state'], 'active')
        self.assertEqual(row['output_count'], 2)
        self.assertEqual(row['quality_count'], 0)
        self.assertEqual(row['issue_count'], 2)
        self.assertEqual(row['platform']['state'], 'unrecorded')
        self.assertIsNone(row['platform']['verified'])
        self.assertEqual([t['id'] for t in row['threads']], ['thread-1'])
        self.assertEqual(read_api(self.data, '/api/console/requirements')['summary']['output'], 1)

    def test_requirement_platform_evidence_must_match_current_request_and_closure(self):
        path, request, ledger = self.requirement_fixture()
        check = {**{k: request[k] for k in ('code', 'requirement_id', 'content_version')},
                 'request_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'expected_count': 2,
                 'verified_count': 2, 'complete': True, 'missing': [], 'checked_at': '2026-11-03T01:00:00Z'}
        check_path = self.put('state/fireplay/ABC-20261103-001/completion-check.json', check)
        self.assertEqual(self.data.requirement_board()['requirements'][0]['state'], 'verified')
        closure_path = self.put('state/fireplay/ABC-20261103-001/delivery-closures/receipt.json',
                               {'requirement_id': 'real-id', 'content_version': 'v1', 'complete': True,
                                'completion_check_sha256': hashlib.sha256(check_path.read_bytes()).hexdigest(),
                                'closed_at': '2026-11-03T01:01:00Z'})
        self.put('state/fireplay/ABC-20261103-001/delivery-closure.json',
                 {'receipt': str(closure_path.relative_to(self.root)), 'sha256': hashlib.sha256(closure_path.read_bytes()).hexdigest()})
        self.data.cache.clear()
        ledger['blockers'] = ['旧的阻塞记录']
        closed = self.data.requirement_board()['requirements'][0]
        self.assertEqual(closed['state'], 'closed')
        self.assertEqual(closed['progress_state'], 'done')
        ledger.pop('blockers')
        request['content_version'] = 'v2';path.write_text(json.dumps(request));self.data.cache.clear()
        row = self.data.requirement_board()['requirements'][0]
        self.assertEqual(row['platform']['state'], 'stale')
        self.assertIsNone(row['platform']['verified'])
        self.assertIsNone(row['output_count'])
        self.assertEqual(row['state'], 'unknown')

    def test_requirement_uses_only_newer_matching_monitor_status(self):
        path, request, _ = self.requirement_fixture()
        request['refreshed_at'] = '2026-11-03T01:00:00Z'
        path.write_text(json.dumps(request))
        monitored = {'row': {'id': 'real-id', 'code': request['code'], 'status': 'pending_upload'},
                     'last_seen_at': '2026-11-03T02:00:00Z'}
        for override, status, observed_at in (
            ({}, 'pending_upload', monitored['last_seen_at']),
            ({'last_seen_at': '2026-11-03T00:59:00Z'}, 'not_started', request['refreshed_at']),
            ({'row': {**monitored['row'], 'id': 'other-id'}}, 'not_started', request['refreshed_at']),
        ):
            self.put('state/fireplay/monitor/state.json', {'requirements': {'real-id': {**monitored, **override}}})
            self.data.cache.clear()
            row = self.data.requirement_board()['requirements'][0]
            self.assertEqual((row['platform_status'], row['platform_snapshot_at']), (status, observed_at))
            self.assertIsNone(row['platform']['verified'])

    def test_status_refresh_retains_closed_delivery_only_with_matching_current_bindings(self):
        _, request, _ = self.requirement_fixture()
        folder = 'state/fireplay/ABC-20261103-001'
        items = [{'video_index': 1, 'locale': locale, 'sha256': str(index)*64,
                  'material_id': f'00000000-0000-0000-0000-00000000000{index}'}
                 for index, locale in enumerate(('es', 'ja'), 1)]
        identity = {key: request[key] for key in ('code', 'requirement_id', 'content_version')}
        check = {**identity, 'request_sha256': self.data.store.sha(folder+'/request.json'),
                 'expected_count': 2, 'verified_count': 2, 'complete': True, 'missing': [], 'verified': items}
        check_file = self.put(folder+'/completion-check.json', check)
        closure = self.put(folder+'/delivery-closures/receipt.json',
                           {**identity, 'expected_count': 2, 'verified_count': 2, 'complete': True,
                            'completion_check_sha256': hashlib.sha256(check_file.read_bytes()).hexdigest(),
                            'closed_at': '2026-11-03T01:01:00Z'})
        self.put(folder+'/delivery-closure.json',
                 {'receipt': str(closure.relative_to(self.root)), 'sha256': hashlib.sha256(closure.read_bytes()).hexdigest()})
        binding = {'requirement_id': request['requirement_id'], 'state': 'returned_user_approved', 'items': items}
        self.put(folder+'/user-approved-return-1.json', binding)
        request['snapshot']['row']['status'] = 'done'
        request['blockers'] = ['Requirement is already done; no automatic reproduction']
        self.put(folder+'/request.json', request)

        def observed():
            self.data.cache.clear()
            row = self.data.requirement_board()['requirements'][0]
            return row['platform']['state'], row['platform']['verified'], row['progress_state']

        self.assertEqual(observed(), ('closed', 2, 'done'))
        self.put(folder+'/user-approved-return-1.json', {**binding, 'items': items[:1]})
        self.assertEqual(observed(), ('stale', None, 'done'))
        request['blockers'].append('Current delivery hold')
        self.put(folder+'/request.json', request)
        self.assertEqual(observed(), ('stale', None, 'done'))
        board = self.data.requirement_board()
        self.assertEqual(board['requirements'][0]['state'], 'completed')
        self.assertEqual(board['summary']['attention'], 0)
        self.assertEqual(self.data.session_usage()['sessions'], [])
        session = next(row for row in self.data.overview()['sessions'] if row['id'] == 'thread-1')
        self.assertEqual(session['business_state'], 'completed')
        self.assertFalse(session['blocked'])
        self.assertNotIn('thread-1', {row['id'] for row in self.data.overview(state='attention')['sessions']})
        request['snapshot']['row']['status'] = 'in_progress'
        self.put(folder+'/request.json', request)
        self.assertEqual(observed(), ('stale', None, 'blocked'))

    def test_session_publication_step_matches_current_source_language_and_version(self):
        path, request, _ = self.requirement_fixture()
        source_sha, candidate_sha, delivered_sha = 'a'*64, 'b'*64, 'c'*64
        request['videos'][0].update(members=['run-1'], source={'sha256': source_sha})
        self.put(path.relative_to(self.root), request)
        self.put('runs/run-1/run.json', {'source_sha256': source_sha})
        self.put('runs/run-1/inputs/request.json', {'target_language': 'es'})
        self.put('runs/run-1/outputs/completion.json', {
            'state': 'delivered_with_issues', 'video_sha256': delivered_sha,
            'candidate_sha256_at_completion': candidate_sha})
        self.put('runs/run-1/outputs/candidate.json', {'sha256': candidate_sha})
        item = {'video_index': 1, 'locale': 'es', 'sha256': delivered_sha,
                'material_id': '00000000-0000-0000-0000-000000000001'}
        check = {**{key: request[key] for key in ('code', 'requirement_id', 'content_version')},
                 'request_sha256': self.data.store.sha(str(path.relative_to(self.root))),
                 'expected_count': 2, 'verified_count': 1, 'complete': False, 'verified': [item]}
        check_path = 'state/fireplay/ABC-20261103-001/completion-check.json'

        def publication_state():
            info = self.data.detail('thread-1', 'run-1')
            return next(node['state'] for node in info['nodes'] if node['id'] == 'publication')

        for receipt in ({**item, 'video_index': 2}, {**item, 'locale': 'ja'}, {**item, 'sha256': candidate_sha}):
            self.put(check_path, {**check, 'verified': [receipt]})
            self.assertNotEqual(publication_state(), 'verified')
        self.put(check_path, check)
        self.assertEqual(publication_state(), 'verified')
        self.put('runs/run-1/run.json', {'source_sha256': 'd'*64})
        self.assertNotEqual(publication_state(), 'verified')
        self.put('runs/run-1/run.json', {'source_sha256': source_sha})
        self.put('runs/run-1/outputs/candidate.json', {'sha256': 'e'*64})
        self.assertNotEqual(publication_state(), 'verified')

    def test_session_usage_does_not_duplicate_shared_request_credits(self):
        path, request, ledger = self.requirement_fixture()
        rollout = self.home/'sessions/thread-1.jsonl'
        rollout.parent.mkdir()
        self._write_token_usage(rollout, '2026-11-03T00:00:00Z', 12000, 345, 9000)
        with sqlite3.connect(self.home/'state_5.sqlite') as db:
            db.execute('ALTER TABLE threads ADD COLUMN tokens_used INTEGER')
            db.execute("UPDATE threads SET tokens_used=12345, rollout_path=? WHERE id='thread-1'", (str(rollout),))
        request.update(budget='shared', videos=[
            {'index': 1, 'targets': ['es'], 'members': ['run-first'], 'chat': {'threadId': 'thread-1'}},
            {'index': 2, 'targets': ['ja'], 'members': ['run-second'], 'chat': {'threadId': 'thread-2'}},
        ])
        path.write_text(json.dumps(request))
        budget = {'id': 'shared', 'reservations': {
            'billed-first': {'run': 'run-first', 'actual_credits': 12},
            'billed-second': {'run': 'run-second', 'actual_credits': 19},
            'unknown': {'run': 'run-first', 'actual_credits': None},
            'unassigned': {'run': 'other-run', 'actual_credits': 23},
        }}
        self.put('state/budgets/shared.json', budget)
        self.assertEqual(self.data.session_usage()['sessions'], [])
        self.assertFalse((self.root/'state/ledger/session-usage.sqlite3').exists())
        check = {**{key: request[key] for key in ('code', 'requirement_id', 'content_version')},
                 'request_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                 'complete': True, 'missing': [], 'expected_count': 2, 'verified_count': 2}
        self.put('state/fireplay/ABC-20261103-001/completion-check.json', check)
        self.data.cache.clear()
        sessions = self.data.session_usage()['sessions']
        self.assertEqual(len(sessions), 2)
        first = next(row for row in sessions if row['codex_total']==12345)
        self.assertEqual(first['requirements'], [{'code': request['code'], 'language_count': 2}])
        self.assertEqual(first['kie'], {'known': 12, 'unknown': 1, 'ambiguous': 1})
        self.assertEqual(first['codex_breakdown'], {'input': 12000, 'output': 345, 'cached_input': 9000})
        self.assertEqual(sum(row['kie']['known'] for row in sessions if row['kie']), 31)
        self.assertNotIn(23, [row['kie']['known'] for row in sessions if row['kie']])
        budget['reservations']['unknown']['actual_credits'] = 3
        self.put('state/budgets/shared.json', budget)
        with sqlite3.connect(self.home/'state_5.sqlite') as db:
            db.execute("UPDATE threads SET tokens_used=99999 WHERE id='thread-1'")
        self.data.cache.clear()
        self.assertEqual(self.data.session_usage()['sessions'], sessions)
        ledger['content_version'] = 'v2'
        self.data.cache.clear()
        self.assertEqual(self.data.session_usage()['sessions'], [])

    def _write_token_usage(self, path, timestamp, inputs, outputs, cached):
        record = {'timestamp': timestamp, 'type': 'event_msg', 'payload': {'type': 'token_count', 'info': {
            'total_token_usage': {'input_tokens': inputs, 'output_tokens': outputs,
                                  'cached_input_tokens': cached, 'total_tokens': inputs+outputs},
            'last_token_usage': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}}}}
        with path.open('a') as stream:
            stream.write(json.dumps(record)+'\n')

    def test_legacy_usage_backfills_only_from_the_frozen_total_and_time(self):
        state = self.root/'state/ledger'
        state.mkdir(parents=True)
        frozen = {'codex_total': 120, 'kie': {'known': 7}, 'recorded_at': '2026-11-03T00:10:00+00:00'}
        with sqlite3.connect(state/'session-usage.sqlite3') as db:
            db.execute('CREATE TABLE snapshots (thread TEXT, scope TEXT, usage TEXT NOT NULL, PRIMARY KEY (thread, scope))')
            db.executemany('INSERT INTO snapshots VALUES (?, ?, ?)', [
                ('thread-1', 'scope', json.dumps(frozen)),
                ('thread-2', 'scope', json.dumps({**frozen, 'codex_total': 333})),
                ('thread-3', 'scope', json.dumps(frozen)),
            ])
        rollout = self.home/'archived_sessions/history.jsonl'
        rollout.parent.mkdir()
        self._write_token_usage(rollout, '2026-11-03T00:04:00Z', 100, 20, 80)
        self._write_token_usage(rollout, '2026-11-03T00:06:00Z', 150, 30, 100)
        self._write_token_usage(rollout, '2026-11-03T00:11:00Z', 110, 10, 99)
        self._write_token_usage(rollout, '2026-11-03T00:12:00Z', 300, 33, 260)
        outside = self.home/'other.jsonl'
        outside.write_bytes(rollout.read_bytes())
        threads = {f'thread-{number}': {'name': str(number), 'tokens_used': 333,
                   'rollout_path': str(outside if number == 3 else rollout)} for number in (1, 2, 3)}
        eligible = dict.fromkeys(threads, 'scope')
        rows = {row['title']: row for row in self.data._completed_usage(threads, eligible, {}, {}, {})}
        self.assertEqual(rows['1'], {'title': '1', 'requirements': [], **frozen,
                                    'codex_breakdown': {'input': 100, 'output': 20, 'cached_input': 80}})
        self.assertIsNone(rows['2']['codex_breakdown'])
        self.assertIsNone(rows['3']['codex_breakdown'])
        self._write_token_usage(rollout, '2026-11-03T00:07:00Z', 115, 5, 1)
        self.assertEqual({row['title']: row for row in self.data._completed_usage(threads, eligible, {}, {}, {})}, rows)

    def test_live_launch_check_reports_only_materials_returned_for_current_receipt(self):
        path, request, ledger = self.requirement_fixture()
        first, second = '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000002'
        check = {**{key: request[key] for key in ('code', 'requirement_id', 'content_version')},
                 'request_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                 'complete': True, 'expected_count': 2, 'verified_count': 2,
                 'verified': [{'material_id': first}, {'material_id': second}]}
        check_path = 'state/fireplay/ABC-20261103-001/completion-check.json'
        self.put(check_path, check)
        ledger['platform'] = {'check_path': check_path, 'verified': 2}

        class LedgerFixture:
            def view(self, **kwargs):
                return {'requirements': [ledger]}

        scope = LedgerFixture()
        query = plan_launch(self.data.store, scope)[0]
        self.assertEqual(set(query['materialIds']), {first, second})
        observed_at = now()
        response = {'query_meta': {'filters': {**query, 'page': 1, 'resultSource': 'all'},
                                   'queried_at': observed_at, 'truncated': False, 'launch_status_scope': None},
                    'has_more': False, 'total': 1, 'items': [{'id': first, 'hasLaunchRecord': True}]}
        self.assertEqual(record_launch(self.data.store, scope, response)['updated'], 1)
        self.assertEqual(self.data.requirement_board()['requirements'][0]['launch'],
                         {'materials': 2, 'checked': 1, 'launched': 1, 'observed_at': observed_at})
        response['items'] = [{'id': 'outside', 'hasLaunchRecord': False}]
        with self.assertRaises(ValueError):
            record_launch(self.data.store, scope, response)

    def test_registered_requirement_without_ledger_does_not_fabricate_zero_progress(self):
        self.requirement_fixture()
        self.data.ledger_rows = lambda: [{'id': 'unlinked', 'countable': False, 'code': 'unlinked'}]
        board = self.data.requirement_board()
        self.assertEqual(board['summary']['total'], 1)
        row = board['requirements'][0]
        self.assertEqual(row['task_count'], 2)
        self.assertIsNone(row['output_count'])
        self.assertIsNone(row['quality_count'])
        self.assertEqual(row['description'], '真实需求正文')

    def test_requirement_expired_artifacts_are_not_reported_as_active_production(self):
        _, _, ledger = self.requirement_fixture()
        ledger.update(state='executing', output_count=0, stage_counts={'expired': 2})
        board = self.data.requirement_board()
        self.assertEqual(board['requirements'][0]['state'], 'expired')
        self.assertEqual(board['summary']['working'], 0)

    @unittest.skipUnless(sys.platform == 'darwin', 'native macOS events')
    def test_native_filesystem_events_are_lazy_filtered_and_release_after_clients(self):
        state = self.root/'state';state.mkdir()
        hub = EventHub(self.root, self.home)
        self.addCleanup(hub.close)
        self.assertIsNone(hub.watcher)
        self.assertFalse(hub.relevant(self.root/'unrelated.txt'))
        self.assertFalse(hub.relevant(self.home/'unrelated.log'))
        revision = hub.subscribe()
        watcher = hub.watcher
        (state/'observed.json').write_text('{}')
        self.assertGreater(hub.wait(revision, 5), revision)
        hub.unsubscribe()
        hub.subscribe()
        self.assertIs(hub.watcher, watcher)  # no lost-event gap between UI waits
        hub.unsubscribe()
        hub.close_if_unused()
        self.assertIsNone(hub.watcher)
        self.assertFalse(watcher.thread.is_alive())


class ConsoleHTTPTests(unittest.TestCase):
    setUp = ConsoleTests.setUp

    def server(self):
        from server import WorkbenchServer
        server = WorkbenchServer(('127.0.0.1', 0), self.root, collect=False)
        server.console = self.data
        server.console_events = EventHub(self.root, self.home)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        return server

    def request(self, server, method, path, body=None, headers=None):
        c = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        c.request(method, path, body, headers or {})
        r = c.getresponse();result = (r.status, r.read());c.close();return result

    def test_command_requires_same_origin_and_server_token(self):
        server = self.server()
        body = json.dumps({'command_id': 'http-message-0001', 'action': 'message', 'thread_id': 'thread-1', 'text': '只读检查'})
        self.assertEqual(self.request(server, 'POST', '/api/console/command', body)[0], 403)
        headers = {'Content-Type': 'application/json', 'Origin': f'http://127.0.0.1:{server.server_port}', 'X-Ledger-Token': server.ledger_token}
        status, value = self.request(server, 'POST', '/api/console/command', body, headers)
        self.assertEqual(status, 200);self.assertEqual(json.loads(value)['status'], 'queued')
        self.assertEqual(self.request(server, 'POST', '/api/console/command', body, headers), (status, value))
        headers['Origin'] = 'https://example.com'
        self.assertEqual(self.request(server, 'POST', '/api/console/command', body, headers)[0], 403)

    def test_http_pages_and_unmatched_thread_access(self):
        server = self.server()
        status, body = self.request(server, 'GET', '/api/console/sessions?page=2')
        self.assertEqual(status, 200);self.assertEqual(len(json.loads(body)['sessions']), 8)
        self.assertEqual(self.request(server, 'GET', '/api/console/detail?id=outside')[0], 400)
        self.assertEqual(self.request(server, 'GET', '/console'), (302, b''))
        for path in ['/', '/console/app.js', '/console/styles.css']:
            status, body = self.request(server, 'GET', path)
            self.assertEqual(status, 200);self.assertTrue(body)
        status, body = self.request(server, 'GET', '/api/console/requirements')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['summary']['total'], 0)

    @unittest.skipUnless(sys.platform == 'darwin', 'native macOS events')
    def test_sse_waits_for_real_local_file_change(self):
        (self.root/'state').mkdir()
        server = self.server()
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=8)
        connection.request('GET', '/api/console/events')
        response = connection.getresponse()
        self.addCleanup(connection.close);self.addCleanup(response.close)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader('Content-Type'), 'text/event-stream')
        self.assertEqual(response.readline(), b'event: ready\n')
        initial = json.loads(response.readline().decode().removeprefix('data: '))
        self.assertEqual(initial['backend'], 'macos_fsevents')
        self.assertFalse(initial['agent_polling'])
        self.assertEqual(response.readline(), b'\n')
        (self.root/'state/event-check.json').write_text('{}')
        self.assertEqual(response.readline(), b'event: change\n')
        change = json.loads(response.readline().decode().removeprefix('data: '))
        self.assertGreater(change['revision'], initial['revision'])


if __name__ == '__main__':unittest.main(verbosity=2)
