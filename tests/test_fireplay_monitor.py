import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'src'))
from video_localizer import budgets, fireplay_monitor as monitor, workflow
from video_localizer.common import WorkflowError, read_json, write_json, utc_now
from test_fireplay import fixture, CODE, RID, MID, THREAD


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=PROJECT / 'work/test-tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(PROJECT / 'config', self.root / 'config', ignore=shutil.ignore_patterns('*.local.json'))
        self.config = read_json(self.root / 'config/fireplay-monitor.json')
        self.config['activated_at'] = (datetime.now(timezone.utc)-timedelta(minutes=10)).isoformat()
        write_json(self.root / 'config/fireplay-monitor.json', self.config)
        self.snap = fixture()
        for view in ['summary', 'brief']:
            self.snap[view]['items'][0].update(createdAt=(datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat(),
                                             priority='P1', status='not_started',assigneeIds=[self.config['assignees'][0]['id']])
        self.snap['summary']['serverTime'] = utc_now()

    def pages(self, rows=None):
        return {'summary_pages': [{'arguments': self.config['query'],
                 'response': {'items': rows if rows is not None else self.snap['summary']['items'],
                              'serverTime': utc_now(), 'next_cursor': None}}]}

    def state(self):
        return read_json(self.root / 'state/fireplay/monitor/state.json')

    def decision(self, yes=True):
        return {'snapshot': self.snap, 'decision': {'is_translation': yes,
                 'reason': 'Observed actual fixture title and declared locales', 'evidence': ['brief.title', 'brief.locales']}}

    def test_baseline_all_groups_excludes_old_and_survives_repeat(self):
        old = copy.deepcopy(self.snap['summary']['items'][0])
        old.update(createdAt='2025-01-01T00:00:00Z', deptName='KEY')
        result = monitor.scan(self.pages([old]), self.root)
        self.assertEqual(result['needs_review'], [])
        self.assertEqual(result['visible_count'], 1)
        monitor.scan(self.pages([old]), self.root)
        self.assertEqual(self.state()['requirements'][RID]['state'], 'baseline')
        self.assertFalse((self.root / 'state/budgets').exists())

    def test_no_group_allowlist_new_she_and_p0_first_without_p1_barrier(self):
        monitor.scan(self.pages([]), self.root)
        p1 = self.snap['summary']['items'][0]
        p0 = {**p1, 'id': MID, 'code': 'SHE-20261027-999', 'deptName': 'SHE', 'priority': 'P0'}
        result = monitor.scan(self.pages([p1, p0]), self.root)
        self.assertEqual([r['code'] for r in result['needs_review']], ['SHE-20261027-999', CODE])
        self.assertFalse(result['p1_waits_for_p0'])
        self.assertEqual(result['scope'], 'translation_intent_in_all_visible_groups')

    def test_other_assignees_excluded_even_when_they_request_translation(self):
        self.config['assignee_mode'] = 'strict'
        self.config['query']['assignee_ids'] = [p['id'] for p in self.config['assignees']]
        write_json(self.root / 'config/fireplay-monitor.json', self.config)
        other = {**self.snap['summary']['items'][0], 'assigneeIds':['someone-else'], 'title':'翻译'}
        with self.assertRaisesRegex(WorkflowError, 'outside the selected assignees'):
            monitor.scan(self.pages([other]), self.root)

    def test_partial_failed_or_changed_pagination_never_advances_checkpoint(self):
        spec = self.pages()
        spec['summary_pages'][0]['response']['next_cursor'] = 'next'
        self.assertEqual(monitor.scan(spec, self.root)['state'], 'needs_more_pages')
        self.assertFalse((self.root / 'state/fireplay/monitor/state.json').exists())
        continuation = {'arguments': {**self.config['query'], 'cursor': 'next'}, 'response': {'items': []}}
        spec['summary_pages'].append(continuation)
        self.assertEqual(monitor.scan(spec, self.root)['visible_count'], 1)
        previous = self.state()
        broken = copy.deepcopy(spec)
        broken['summary_pages'][1]['arguments']['dept_id'] = 'different-group'
        with self.assertRaisesRegex(WorkflowError, 'exact monitor filters'):
            monitor.scan(broken, self.root)
        self.assertEqual(self.state(), previous)
        broken = copy.deepcopy(spec)
        broken['summary_pages'][1]['response'] = {'isError': True}
        with self.assertRaises(WorkflowError):
            monitor.scan(broken, self.root)
        self.assertEqual(self.state(), previous)

    def test_invalid_historical_code_is_quarantined_not_a_path(self):
        row = {**self.snap['summary']['items'][0], 'code': '../outside'}
        monitor.scan(self.pages([row]), self.root)
        self.assertEqual(self.state()['requirements'][RID]['state'], 'unsupported_code')

    def test_old_new_visibility_is_not_a_fresh_user_request(self):
        monitor.scan(self.pages([]), self.root)
        row = {**self.snap['summary']['items'][0], 'createdAt': '2025-01-01T00:00:00Z'}
        monitor.scan(self.pages([row]), self.root)
        self.assertEqual(self.state()['requirements'][RID]['state'], 'newly_visible_old')
        with self.assertRaisesRegex(WorkflowError, 'backlog'):
            monitor.assess(CODE, self.decision(), self.root)

    def test_real_assessment_registers_without_spending_and_preserves_authority(self):
        monitor.scan(self.pages(), self.root)
        result = monitor.assess(CODE, self.decision(), self.root)
        self.assertEqual(result['state'], 'admitted')
        authority = read_json(self.root / result['authority_path'])
        self.assertEqual(authority['scope_requirement'], CODE)
        self.assertIn(RID, authority['authorization_ref'])
        self.assertEqual(authority['standing_authorization_ref'], self.config['authority']['authorization_ref'])
        self.assertFalse((self.root / 'state/budgets').exists())
        self.assertEqual(len(monitor.status(self.root)['ready_to_dispatch']), 1)
        monitor.assess(CODE, self.decision(), self.root)
        self.assertEqual(len(monitor.status(self.root)['ready_to_dispatch']), 1)

    def test_nontranslation_in_progress_and_no_permission_do_not_start(self):
        for case in ('not_translation', 'in_progress', 'no_permission'):
            with self.subTest(case=case):
                for view in ['summary', 'brief']:
                    self.snap[view]['items'][0].update(status='in_progress' if case == 'in_progress' else 'not_started',
                                                     canBindMaterials=case != 'no_permission')
                # Reset only this disposable discovery record between cases.
                state = self.root / 'state/fireplay/monitor/state.json'
                state.unlink(missing_ok=True)
                monitor.scan(self.pages(), self.root)
                result = monitor.assess(CODE, self.decision(case != 'not_translation'), self.root)
                self.assertIn(result['state'], ('ignored', 'not_eligible'))
                self.assertFalse((self.root / 'state/fireplay' / CODE / 'request.json').exists())

    def test_metadata_change_does_not_restart_historical_work_but_new_title_does(self):
        old = {**self.snap['summary']['items'][0], 'createdAt': '2025-01-01T00:00:00Z', 'updatedAt': '2025-01-01T00:00:00Z'}
        monitor.scan(self.pages([old]), self.root)
        monitor.scan(self.pages(), self.root)
        self.assertEqual(monitor.assess(CODE, self.decision(), self.root)['state'], 'historical_translation_pending')
        self.assertTrue(self.state()['requirements'][RID]['decision']['is_translation'])
        self.assertEqual(monitor.status(self.root)['historical_translation_candidates'][0]['code'], CODE)
        self.assertFalse((self.root / 'state/fireplay' / CODE / 'request.json').exists())
        for view in ['summary', 'brief']:
            self.snap[view]['items'][0]['title'] = 'new product 翻译'
        monitor.scan(self.pages(), self.root)
        self.assertEqual(monitor.assess(CODE, self.decision(), self.root)['state'], 'admitted')

    def test_targeted_baseline_recheck_keeps_real_translation_pending_without_starting_it(self):
        old = {**self.snap['summary']['items'][0], 'createdAt': '2025-01-01T00:00:00Z'}
        monitor.scan(self.pages([old]), self.root)
        result = monitor.assess(CODE, {**self.decision(), 'recheck': True}, self.root)
        self.assertEqual(result['state'], 'historical_translation_pending')
        self.assertEqual(monitor.status(self.root)['ready_to_dispatch'], [])
        self.assertFalse((self.root / 'state/budgets').exists())

    def test_refresh_registered_requirement_preserves_direct_user_interpretation_and_authority(self):
        from video_localizer import fireplay
        for view in ['summary', 'brief']:
            self.snap[view]['items'][0]['locales'] = ['kr', 'es']
        monitor.scan(self.pages(), self.root)
        interpretation = {'authorization_ref': 'actual-user-direct-request', 'source_quote': 'offline direct fixture',
                          'quantity_mode': 'one_per_locale', 'targets': ['ko', 'es']}
        fireplay.register(CODE, self.snap, interpretation, self.root)
        authority_path = self.root / 'state/fireplay' / CODE / 'monitor-authority.json'
        original = {'authority': 'user', 'authorization_ref': 'actual-user-direct-request', 'source_quote': 'offline fixture'}
        write_json(authority_path, original)
        self.assertEqual(monitor.assess(CODE, self.decision(), self.root)['state'], 'admitted')
        self.assertEqual(read_json(authority_path), original)
        self.assertEqual(read_json(authority_path.parent / 'request.json')['decision'], interpretation)

    def explicit_authority(self):
        return {'authority': 'user', 'authorization_ref': 'actual-user-selection:' + CODE,
                'source_quote': 'Start these explicitly selected requirements separately',
                'source_thread_id': THREAD, 'user_request': 'Start ' + CODE,
                'scope_requirement': CODE, 'requirement_id': RID, 'mode': 'first'}

    def configure_conditional_intake(self):
        person = self.config['assignees'][0]['id']
        self.config['conditional_intakes'] = [{'code': CODE, 'requirement_id': RID,
                                             'assignee_id': person, 'authority': self.explicit_authority()}]
        write_json(self.root / 'config/fireplay-monitor.json', self.config)
        return person

    def test_conditional_assignment_releases_history_even_without_timestamp_change(self):
        person = self.configure_conditional_intake()
        for view in ('brief', 'summary'):
            self.snap[view]['items'][0].update(assigneeIds=['other-person'], createdAt='2025-01-01T00:00:00Z')
        initial = monitor.scan(self.pages(), self.root)
        self.assertEqual(initial['needs_review'][0]['code'], CODE)
        self.assertEqual(monitor.assess(CODE, self.decision(), self.root)['state'], 'waiting_for_assignment')
        s = monitor.status(self.root)
        self.assertEqual(s['historical_review_required'], [])
        self.assertEqual(s['waiting_for_assignment'][0]['assignee_id'], person)
        self.assertFalse((self.root / 'state/fireplay' / CODE / 'request.json').exists())
        for view in ('brief', 'summary'):
            self.snap[view]['items'][0]['assigneeIds'] = ['other-person', person]
        # Same title, body, status and updatedAt; the assignment itself is material.
        self.assertEqual(monitor.scan(self.pages(), self.root)['needs_review'][0]['code'], CODE)
        r = monitor.assess(CODE, self.decision(), self.root)
        self.assertEqual(r['state'], 'admitted')
        self.assertEqual(read_json(self.root / r['authority_path']), self.explicit_authority())
        self.assertFalse((self.root / 'state/budgets').exists())
        self.assertEqual(len(monitor.status(self.root)['ready_to_dispatch']), 1)
        monitor.assess(CODE, self.decision(), self.root)
        self.assertEqual(len(monitor.status(self.root)['ready_to_dispatch']), 1)

    def test_conditional_assignment_still_requires_eligibility(self):
        self.configure_conditional_intake()
        for status, permission in [('done', True), ('in_progress', True), ('not_started', False)]:
            with self.subTest(status=status, permission=permission):
                for view in ('brief', 'summary'):
                    self.snap[view]['items'][0].update(status=status, canBindMaterials=permission)
                monitor.scan(self.pages(), self.root)
                self.assertEqual(monitor.assess(CODE, self.decision(), self.root)['state'], 'not_eligible')
        self.assertFalse((self.root / 'state/fireplay' / CODE / 'request.json').exists())

    def test_conditional_rule_does_not_become_global_assignee_filter(self):
        self.configure_conditional_intake()
        other = copy.deepcopy(self.snap)
        other_code = 'MOG-20261027-999'
        for view in ('brief', 'summary'):
            other[view]['items'][0].update(id=MID, code=other_code, assigneeIds=['other-person'])
        monitor.scan(self.pages(other['summary']['items']), self.root)
        spec = {**self.decision(), 'snapshot': other}
        self.assertEqual(monitor.assess(other_code, spec, self.root)['state'], 'admitted')

    def test_explicit_selection_releases_pending_without_spending_or_reopening_budget(self):
        old = {**self.snap['summary']['items'][0], 'createdAt': '2025-01-01T00:00:00Z'}
        monitor.scan(self.pages([old]), self.root)
        monitor.assess(CODE, {**self.decision(), 'recheck': True}, self.root)
        pending = monitor.status(self.root)['historical_review_required'][0]
        self.assertEqual(pending['code'], CODE)
        self.assertIn('ask the owner once', pending['next_action'])
        authority = self.explicit_authority()
        spec = {**self.decision(), 'authority': authority}
        result = monitor.assess(CODE, spec, self.root)
        self.assertEqual(result['state'], 'admitted')
        self.assertEqual(read_json(self.root / result['authority_path']), authority)
        self.assertEqual(monitor.status(self.root)['historical_review_required'], [])
        p = self.root / 'state/fireplay' / CODE / 'request.json'
        record = read_json(p)
        record.update(budget='keep-original', chat={'state': 'ready', 'threadId': THREAD})
        write_json(p, record)
        monitor.assess(CODE, spec, self.root)
        self.assertEqual(read_json(p)['budget'], 'keep-original')
        self.assertEqual(read_json(p)['chat']['threadId'], THREAD)
        self.assertFalse((self.root / 'state/budgets').exists())

    def test_wrong_or_incomplete_explicit_authority_cannot_release_history(self):
        old = {**self.snap['summary']['items'][0], 'createdAt': '2025-01-01T00:00:00Z'}
        monitor.scan(self.pages([old]), self.root)
        for field, value in [('scope_requirement', 'MOG-20261027-999'),
                             ('requirement_id', MID), ('source_quote', '')]:
            with self.subTest(field=field):
                authority = {**self.explicit_authority(), field: value}
                with self.assertRaises(WorkflowError):
                    monitor.assess(CODE, {**self.decision(), 'authority': authority}, self.root)
        self.assertFalse((self.root / 'state/fireplay' / CODE / 'request.json').exists())

    def test_explicit_history_does_not_bypass_done_permission_or_content_revision(self):
        for status, allowed in [('done', True), ('in_progress', True), ('not_started', False)]:
            for view in ('brief', 'summary'):
                self.snap[view]['items'][0].update(status=status, canBindMaterials=allowed)
            monitor.scan(self.pages(), self.root)
            r = monitor.assess(CODE, {**self.decision(), 'authority': self.explicit_authority()}, self.root)
            self.assertEqual(r['state'], 'not_eligible')
        self.assertFalse((self.root / 'state/fireplay' / CODE / 'request.json').exists())

    def test_historical_completed_is_not_a_pending_question_and_real_body_revision_admits(self):
        old = {**self.snap['summary']['items'][0], 'createdAt': '2025-01-01T00:00:00Z'}
        monitor.scan(self.pages([old]), self.root)
        for view in ('brief', 'summary'):
            self.snap[view]['items'][0]['status'] = 'done'
        self.assertEqual(monitor.assess(CODE, {**self.decision(), 'recheck': True}, self.root)['state'], 'not_eligible')
        self.assertEqual(monitor.status(self.root)['historical_review_required'], [])
        for view in ('brief', 'summary'):
            self.snap[view]['items'][0].update(status='not_started', updatedAt=utc_now())
        self.snap['brief']['items'][0]['description'] += '\nNew actual content revision'
        monitor.scan(self.pages(), self.root)
        self.assertEqual(monitor.assess(CODE, self.decision(), self.root)['state'], 'admitted')

    def test_existing_content_revision_preserves_chat_and_budget(self):
        monitor.scan(self.pages(), self.root)
        monitor.assess(CODE, self.decision(), self.root)
        p = self.root / 'state/fireplay' / CODE / 'request.json'
        record = read_json(p)
        record.update(budget='original-budget', chat={'state': 'ready', 'threadId': THREAD})
        write_json(p, record)
        for view in ['summary', 'brief']:
            self.snap[view]['items'][0].update(title='another product 翻译', updatedAt=utc_now())
        monitor.scan(self.pages(), self.root)
        result = monitor.assess(CODE, {**self.decision(), 'authority': self.explicit_authority()}, self.root)
        self.assertEqual(result['state'], 'needs_revision_review')
        self.assertEqual(read_json(p)['budget'], 'original-budget')
        self.assertEqual(read_json(p)['chat']['threadId'], THREAD)

    def test_reviewed_queue_revision_accepts_new_scope_without_creating_budget(self):
        monitor.scan(self.pages(), self.root)
        monitor.assess(CODE, self.decision(), self.root)
        p = self.root / 'state/fireplay' / CODE / 'request.json'
        old = read_json(p)
        self.snap['brief']['items'][0]['description'] += '\nUpdated actual copy'
        self.assertEqual(monitor.assess(CODE, self.decision(), self.root)['state'], 'needs_revision_review')
        spec = self.decision()
        spec['decision'].update(reviewed_content_version=old['content_version'], targets=['es', 'pt', 'fr'])
        spec['decision']['source_targets'] = {old['videos'][0]['source_url']: ['es', 'pt', 'fr']}
        self.assertEqual(monitor.assess(CODE, spec, self.root)['state'], 'admitted')
        new = read_json(p)
        self.assertCountEqual(new['targets'], ['es', 'pt', 'fr'])
        self.assertCountEqual(new['videos'][0]['targets'], ['es', 'pt', 'fr'])
        self.assertEqual(new['decision']['source_targets'], spec['decision']['source_targets'])
        self.assertEqual(read_json(self.root / new['revision_history'][0]['path']), old)
        self.assertFalse((self.root / 'state/budgets').exists())

    def test_agent_resolves_unparsed_multilingual_brief_before_production(self):
        for view in ('brief', 'summary'):
            self.snap[view]['items'][0]['title'] = ''
            self.snap[view]['items'][0]['locales'] = []
        self.snap['brief']['items'][0]['description'] = 'family time [es/pt] https://www.youtube.com/watch?v=abcdefghijk'
        monitor.scan(self.pages(), self.root)
        spec = {'snapshot': self.snap, 'decision': {'is_translation': True,
                'reason': 'Actual multilingual source video', 'evidence': ['brief.description']}}
        self.assertEqual(monitor.assess(CODE, spec, self.root)['state'], 'needs_information')
        spec['decision']['targets'] = ['es', 'pt']
        self.assertEqual(monitor.assess(CODE, spec, self.root)['state'], 'admitted')
        record = read_json(self.root / 'state/fireplay' / CODE / 'request.json')
        self.assertEqual(record['targets'], ['es', 'pt'])
        self.assertEqual(record['videos'][0]['targets'], ['es', 'pt'])
        self.assertEqual(record['interpretation_history'][0]['targets'], [])
        self.assertFalse((self.root / 'state/budgets').exists())

    def test_missing_language_resolution_does_not_touch_funded_or_dispatched_record(self):
        from video_localizer import fireplay
        for view in ('brief', 'summary'):
            self.snap[view]['items'][0].update(title='', locales=[])
        self.snap['brief']['items'][0]['description'] = 'family time [es/pt] https://www.youtube.com/watch?v=abcdefghijk'
        decision = {'authorization_ref': 'actual-human-scope', 'source_quote': 'Actual request',
                    'quantity_mode': 'one_per_locale'}
        fireplay.register(CODE, self.snap, decision, self.root)
        path = self.root / 'state/fireplay' / CODE / 'request.json'
        pristine = read_json(path)
        for field, value in [('budget', 'original-budget'), ('chat', {'state': 'unknown'})]:
            with self.subTest(field=field):
                old = {**pristine, field: value}
                write_json(path, old)
                with self.assertRaisesRegex(WorkflowError, 'revision review'):
                    fireplay.register(CODE, self.snap, {**decision, 'targets': ['es', 'pt']}, self.root)
                self.assertEqual(read_json(path), old)

    def test_independent_requirement_budgets_even_for_identical_source_bytes(self):
        original = self.root / 'source.mp4'
        original.write_bytes(b'synthetic identical original')
        records = []
        with patch('video_localizer.media.probe', return_value={'duration': 8}):
            for code in [CODE, 'MOG-20261027-999']:
                authority = {'authority': 'user', 'authorization_ref': 'test-standing:' + code,
                             'scope_requirement': code, 'mode': 'first', 'user_request': 'Explicit per-requirement fixture',
                             'source': str(original), 'targets': ['es', 'pt']}
                record = budgets.open_request(authority, self.root)
                self.assertEqual(budgets.open_request(authority, self.root)['id'], record['id'])
                run = self.root / 'runs' / (code+'-01')
                run.mkdir(parents=True)
                shutil.copyfile(original, run / 'source.mp4')
                from video_localizer.common import file_hash
                write_json(run / 'run.json', {'source': 'source.mp4', 'source_sha256': file_hash(original)})
                write_json(run / 'inputs/request.json', {'target_language': 'es'})
                write_json(run / 'inputs/fireplay.json', {'code': code})
                self.assertEqual(budgets.bind(run)['id'], record['id'])
                records.append(record)
        self.assertNotEqual(records[0]['id'], records[1]['id'])
        self.assertEqual([r['credit_limit'] for r in records], [120, 120])

    def test_publication_followup_deduplicates_unknown_and_real_receipts(self):
        from video_localizer import fireplay
        monitor.scan(self.pages(), self.root)
        monitor.assess(CODE, self.decision(), self.root)
        fireplay.chat(CODE, {'title': CODE, 'threadId': THREAD}, root=self.root)
        record_path = self.root / 'state/fireplay' / CODE / 'request.json'
        record = read_json(record_path)
        record['videos'][0].update(members=['fixture-es','fixture-ko'], source={'sha256':'a'*64})
        write_json(record_path, record)
        entries = [{'origin_run_id':'fixture-'+lang,'target_language':lang,'source_sha256':'a'*64,
                    'status':'delivered','technical_decision':'pass'} for lang in ['es','ko']]
        write_json(self.root / 'outputs/index.json', {'entries':entries})
        task = monitor.followups(self.root)[0]
        first = monitor.signal({'key':task['key']}, self.root)
        self.assertEqual(first['state'], 'unknown')
        self.assertEqual(monitor.signal({'key':task['key']}, self.root), first)
        with self.assertRaisesRegex(WorkflowError, 'another chat'):
            monitor.signal({'key':task['key'],'response':{'threadId':RID}}, self.root)
        self.assertEqual(monitor.signal({'key':task['key'],'response':{'threadId':THREAD}}, self.root)['state'], 'sent')
        entries[0].update(status='delivered_with_issues',technical_decision='revise')
        write_json(self.root / 'outputs/index.json', {'entries':entries})
        self.assertEqual(monitor.followups(self.root)[0]['action'], 'review_publication')
        write_json(self.root/'state/fireplay'/CODE/'user-approved-return-1.json', {'state':'returned_user_approved'})
        self.assertEqual(monitor.followups(self.root), [])

    def test_cli_and_mcp_monitor_status(self):
        r = subprocess.run([sys.executable, 'bin/va.py', 'fireplay-monitor', 'scan'],cwd=PROJECT,capture_output=True,text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['state'], 'needs_summary')
        request = {'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'localizer_fireplay_monitor','arguments':{'action':'scan'}}}
        r = subprocess.run([sys.executable,'bin/mcp_server.py'],cwd=PROJECT,input=json.dumps(request)+'\n',capture_output=True,text=True)
        self.assertFalse(json.loads(r.stdout)['result']['isError'])

    def test_partial_return_monitors_only_remaining_locale_without_reopening_accepted_media(self):
        from video_localizer import fireplay
        monitor.scan(self.pages(), self.root)
        monitor.assess(CODE, self.decision(), self.root)
        fireplay.chat(CODE, {'title': CODE, 'threadId': THREAD}, root=self.root)
        folder = self.root / 'state/fireplay' / CODE
        record = read_json(folder / 'request.json')
        record['videos'][0].update(members=['fixture-es', 'fixture-ko'], source={'sha256': 'a'*64})
        write_json(folder / 'request.json', record)
        write_json(folder / 'return-1.json', {'state': 'returned', 'pending_locales': ['ko'],
                   'packages': [{'locale': 'es', 'sha256': 'b'*64}], 'operations': {
                       'bind': {'state': 'verified'}, 'import-1': {'result': {'material_id': MID}}}})
        entries = [{'origin_run_id': 'fixture-'+lang, 'target_language': lang, 'source_sha256': 'a'*64,
                    'status': 'delivered', 'video_sha256': ('b' if lang == 'es' else 'c')*64}
                   for lang in ['es', 'ko']]
        write_json(self.root / 'outputs/index.json', {'entries': entries})
        first = monitor.followups(self.root)[0]
        # A changed already-bound Spanish candidate must not change the pending
        # Korean task identity or cause the accepted Spanish file to be resent.
        entries[0]['video_sha256'] = 'd'*64
        write_json(self.root / 'outputs/index.json', {'entries': entries})
        self.assertEqual(monitor.followups(self.root)[0]['key'], first['key'])
        entries[1]['status'] = 'delivered_with_issues'
        write_json(self.root / 'outputs/index.json', {'entries': entries})
        write_json(folder / 'publication-reviews' / ('c'*64 + '.json'), {'decision': 'blocked'})
        self.assertEqual(monitor.followups(self.root), [])


if __name__ == '__main__':
    unittest.main()
