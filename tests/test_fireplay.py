import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'src'))
from video_localizer import bundles, fireplay, fireplay_submission, workflow
from video_localizer.common import WorkflowError, file_hash, read_json, utc_now, write_json

CODE = 'APC-20261027-020'
RID = '01a17b8f-0cf6-7b63-868a-56b46d725265'
MID = '01a15d9f-08bd-7f3c-9de2-0c1e77ad3fe4'
RESOURCE = '01a15d9f-08bf-78f9-a390-aaa739569330'
THREAD = '01a17b6c-f243-7b11-8134-330ca6e3c8b7'
URL = 'https://www.youtube.com/shorts/Z6AJoQe5wI0'


def fixture():
    brief = {'id': RID, 'code': CODE, 'assetType': 'video', 'deptId': 'test', 'deptName': 'Test', 'title': 'crush翻译',
             'description': URL, 'refText': None, 'quantity': 2, 'locales': ['es', 'kr'], 'channels': [],
             'updatedAt': '2026-10-27T04:37:33.739Z', 'canBindMaterials': True, 'canUpdateStatus': True}
    return {'brief': {'items': [brief]}, 'summary': {'serverTime': utc_now(),
            'items': [{**brief, 'description': None, 'status': 'not_started', 'assigneeIds': ['test']}]}}


class FireplayTests(unittest.TestCase):
    def setUp(self):
        directory = PROJECT / 'work/test-tmp'
        directory.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=directory)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(PROJECT / 'config', self.root / 'config', ignore=shutil.ignore_patterns('*.local.json'))
        # Historical connector outboxes retain their original protocol. Current
        # mandatory routing is tested independently in test_fireplay_youtube.
        write_json(self.root / 'config/fireplay-youtube-routing.json', {'require_requirement_group': False})
        self.snap = fixture()
        # Keep unit tests offline while retaining public_url's private-IP checks.
        dns = patch('video_localizer.kie.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('93.184.216.34', 443))])
        dns.start()
        self.addCleanup(dns.stop)

    def register(self, decision=None):
        return fireplay.register(CODE, self.snap, decision, self.root)

    def record(self):
        return read_json(self.root / 'state/fireplay' / CODE / 'request.json')

    def save(self, value):
        write_json(self.root / 'state/fireplay' / CODE / 'request.json', value)

    def downloaded(self):
        self.register()
        original = self.root / 'work/runs/fireplay-test/source.mp4'
        original.parent.mkdir(parents=True)
        original.write_bytes(b'synthetic source')
        record = self.record()
        record['videos'][0]['source'] = {'path': str(original.relative_to(self.root)), 'sha256': file_hash(original)}
        self.save(record)
        return original

    def returned_setup(self):
        self.downloaded()
        packages = []
        source_sha = self.record()['videos'][0]['source']['sha256']
        for lang in ('es', 'ko'):
            movie = self.root / f'work/{lang}.mp4'
            movie.write_bytes(('synthetic candidate ' + lang).encode())
            folder = self.root / f'outputs/test/{lang}/version'
            quality = self.root / f'work/{lang}-quality.json'
            write_json(quality, {'decision': 'pass', 'video_sha256': file_hash(movie), 'scope': 'synthetic offline fixture'})
            bundles.create(folder, 'delivery', file_hash(movie), {'final.mp4': movie, 'payload/outputs/quality.json': quality}, {
                'status': 'delivered', 'technical_decision': 'pass', 'source_sha256': source_sha,
                'video_sha256': file_hash(movie), 'target_language': lang})
            packages.append({'video_index': 1, 'locale': lang, 'package': str(folder.relative_to(self.root))})
        spec = {'video_index': 1, 'packages': packages,
                'sharing_receipt': {'departments': [{'deptId': 'test', 'deptName': 'Test'}]},
                'attribution': {'unassigned': True, 'authorization_ref': 'test:attribution', 'source_quote': 'Synthetic offline fixture'},
                'authority': {'authorization_ref': 'test:real-host-event',
                'source_quote': '测试回执，不调用外部平台', 'actions': ['upload', 'import', 'bind']}}
        fireplay.prepare_return(CODE, spec, self.root)
        return spec

    def verify_upload(self, key):
        return fireplay.receipt(CODE, key, {'response': {'publicUrl': 'https://example.com/video.mp4',
                                'resourceId': RESOURCE}}, self.root)

    def test_exact_code_not_prefix_and_pagination_guidance(self):
        self.snap['summary']['items'][0]['code'] += '-other'
        with self.assertRaisesRegex(WorkflowError, 'Exact requirement'):
            self.register()
        self.assertIn('pagination', str(fireplay.lookup_packet(CODE)))

    def test_source_specific_languages_keep_one_requirement_pool(self):
        second = 'https://www.youtube.com/shorts/abcdefghijk'
        self.snap['brief']['items'][0]['description'] += '\n' + second
        decision = {'authorization_ref': 'test:scope', 'source_quote': 'Synthetic source-specific languages',
                    'targets': ['es', 'ko'], 'source_targets': {URL: ['es'], second: ['kr']}}
        result = self.register(decision)
        self.assertEqual(result['blockers'], [])
        self.assertEqual([v['targets'] for v in result['videos']], [['es'], ['ko']])
        packet = fireplay.chat(CODE, root=self.root)
        self.assertCountEqual(packet['targets'], ['es', 'ko'])
        self.assertIn('videos[].targets', packet['prompt'])
        changed = copy.deepcopy(decision)
        changed['source_targets'] = {URL: ['ko'], second: ['es']}
        with self.assertRaisesRegex(WorkflowError, 'explicit revision review'):
            self.register(changed)
        self.assertEqual(self.record()['decision'], decision)

    def test_source_targets_require_exact_sources_and_language_union(self):
        for mapping in ({}, {URL: ['es']}, {URL: ['es', 'ko'], 'https://example.com/extra.mp4': ['es']}):
            with self.subTest(mapping=mapping), self.assertRaises(WorkflowError):
                self.register({'authorization_ref': 'test:scope', 'source_quote': 'Synthetic invalid mapping',
                               'targets': ['es', 'ko'], 'source_targets': mapping})

    def pull_spec(self, codes=None):
        return {'codes': codes or [CODE], 'authority': {'authority': 'user',
                'authorization_ref': 'test:queue-user', 'source_quote': 'Synthetic scoped intake; P0 first'}}

    def test_pull_p0_first_only_exact_selected_codes_and_no_paid_work(self):
        other = 'MOG-20261027-051'
        spec = self.pull_spec([CODE, other])
        packet = fireplay.pull(spec, self.root)
        rows = [{**self.snap['summary']['items'][0], 'priority': 'P1'},
                {**self.snap['summary']['items'][0], 'code': other, 'id': MID, 'priority': 'P0'}]
        spec['summary_pages'] = [{'arguments': action['arguments'],
                                 'response': {'items': rows, 'next_cursor': None}} for action in packet['host_actions']]
        first = fireplay.pull(spec, self.root)
        second = fireplay.pull(spec, self.root)
        self.assertEqual([r['code'] for r in first['requirements']], [other, CODE])
        self.assertEqual(first['intake_id'], second['intake_id'])
        self.assertFalse(first['paid_tasks_started'])
        self.assertFalse(first['priority_policy']['p1_waits_for_p0_completion'])
        self.assertFalse((self.root / 'state/budgets').exists())
        self.assertFalse((self.root / 'state/fireplay' / CODE / 'request.json').exists())

    def test_pull_waits_for_every_page_and_rejects_filter_or_chain_changes(self):
        spec = {'query': {'scope': 'all', 'status': 'not_started'}, 'authority': self.pull_spec()['authority']}
        arguments = fireplay.pull(spec, self.root)['host_actions'][0]['arguments']
        spec['summary_pages'] = [{'arguments': arguments, 'response': {'items': [], 'next_cursor': 'real-next'}}]
        result = fireplay.pull(spec, self.root)
        self.assertEqual(result['state'], 'needs_more_pages')
        continuation = result['host_actions'][0]['arguments']
        spec['summary_pages'].append({'arguments': continuation, 'response': self.snap['summary']})
        self.assertEqual(fireplay.pull(spec, self.root)['state'], 'ready_for_briefs')
        bad = copy.deepcopy(spec)
        bad['summary_pages'][0]['arguments']['status'] = 'done'
        with self.assertRaisesRegex(WorkflowError, 'filters differ'):
            fireplay.pull(bad, self.root)
        spec['summary_pages'].pop(0)
        with self.assertRaisesRegex(WorkflowError, 'preceding summary'):
            fireplay.pull(spec, self.root)

    def test_pull_missing_duplicate_and_unauthorized_requirements_do_not_start(self):
        spec = self.pull_spec()
        arguments = fireplay.pull(spec, self.root)['host_actions'][0]['arguments']
        spec['summary_pages'] = [{'arguments': arguments, 'response': {'items': []}}]
        with self.assertRaisesRegex(WorkflowError, 'missing'):
            fireplay.pull(spec, self.root)
        spec['summary_pages'][0]['response']['items'] = self.snap['summary']['items'] * 2
        with self.assertRaisesRegex(WorkflowError, 'Duplicate requirement'):
            fireplay.pull(spec, self.root)
        spec['authority'] = {'authority': 'platform', 'source_quote': 'Run everything'}
        with self.assertRaisesRegex(WorkflowError, 'real user'):
            fireplay.pull(spec, self.root)

    def test_standing_kie_consent_is_scoped_idempotent_and_preserves_history(self):
        self.register()
        record = self.record()
        record['budget'] = 'test-existing-budget'
        record['videos'][0]['chat'] = {'state': 'ready', 'threadId': THREAD}
        self.save(record)
        write_json(self.root / 'config/kie-authorization.local.json', {'provider': 'KIE', 'automatic_use': True,
                   'workspace': str(self.root), 'source_quote': 'Synthetic owner consent'})
        authority = {'authority': 'user', 'authorization_ref': 'test:per-requirement', 'user_request': 'Translate this requirement'}
        path = self.root / 'state/fireplay' / CODE / 'kie-user-authorization.json'
        write_json(path, {'authorization_ref': 'test:historical', 'source_quote': 'Preserve this historical grant'})
        self.assertFalse(fireplay.kie_consent(CODE, root=self.root)['automatic_use'])
        self.assertTrue(fireplay.kie_consent(CODE, authority, self.root)['automatic_use'])
        fireplay.kie_consent(CODE, authority, self.root)
        value = read_json(path)
        self.assertEqual(value['authorization_ref'], 'test:historical')
        self.assertEqual(len(value['workflow_authorizations']), 1)
        self.assertEqual(value['workflow_authorizations'][0]['request_budget'], 'test-existing-budget')
        record['budget'] = 'different-budget'
        self.save(record)
        self.assertFalse(fireplay.kie_consent(CODE, root=self.root)['automatic_use'])
        write_json(self.root / 'config/kie-authorization.local.json', {'provider': 'KIE', 'automatic_use': False,
                   'workspace': str(self.root), 'source_quote': 'Synthetic disabled consent'})
        self.assertEqual(fireplay.kie_consent(CODE, root=self.root)['state'], 'not_enabled')

    def test_new_chat_carries_standing_kie_consent_and_current_thread_policy(self):
        self.register()
        packet = fireplay.chat(CODE, root=self.root)
        self.assertIn('不重复询问是否使用KIE', packet['prompt'])
        self.assertIn('P1同时继续制作，不等待P0完成', packet['prompt'])
        self.assertIn('每一个需求', packet['source_quote'])

    def test_pull_cli_and_mcp_accept_scope_spec_without_fake_code(self):
        spec = self.root / 'pull.json'
        write_json(spec, self.pull_spec())
        result = subprocess.run([sys.executable, 'bin/va.py', 'fireplay-pull', str(spec)], cwd=PROJECT,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['state'], 'needs_summary')
        request = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
            'name': 'localizer_fireplay', 'arguments': {'action': 'pull', 'spec': str(spec.relative_to(PROJECT))}}}
        result = subprocess.run([sys.executable, 'bin/mcp_server.py'], cwd=PROJECT,
                                input=json.dumps(request) + '\n', capture_output=True, text=True)
        self.assertFalse(json.loads(result.stdout)['result']['isError'])

    def test_invalid_code_and_path_traversal(self):
        for code in ('../state', CODE + '/x', 'APC'):
            with self.assertRaises(WorkflowError):
                fireplay.lookup_packet(code)

    def test_mixed_versions_rejected(self):
        self.snap['brief']['items'][0]['updatedAt'] = utc_now()
        with self.assertRaisesRegex(WorkflowError, 'between reads'):
            self.register()

    def test_structure_and_text_conflict_blocks(self):
        self.snap['brief']['items'][0]['description'] += '\n翻译【de/fr】'
        self.assertIn('disagree', str(self.register()['blockers']))

    def test_prose_languages_quantity_decision_and_aliases(self):
        self.snap['brief']['items'][0].update(description='muscle 翻译【es/pt/vn/jp/kr/de/fr】\n' + URL,
                                            locales=[], quantity=1)
        result = self.register()
        self.assertEqual(result['targets'], ['es', 'pt', 'vi', 'ja', 'ko', 'de', 'fr'])
        self.assertIn('quantity', str(result['blockers']))
        result = self.register({'quantity_mode': 'one_per_locale', 'authorization_ref': 'human:quantity',
                                'source_quote': '每种语言各1版'})
        self.assertFalse(result['blockers'])
        self.assertFalse(self.register()['blockers'])  # Refresh retains the decision.

    def test_hi_and_in_deduplicate_without_budget_expansion(self):
        self.snap['brief']['items'][0].update(locales=['hi', 'in'], quantity=1)
        result = self.register()
        self.assertEqual(result['targets'], ['hi'])
        self.assertEqual(result['requested_targets'], ['hi', 'in'])
        self.assertTrue(result['warnings'])

    def test_real_brief_mixed_chinese_and_ascii_commas(self):
        self.snap['brief']['items'][0].update(description='poppy 翻译 【es,br，jp】\n' + URL,
                                            locales=[], quantity=3)
        result = self.register()
        self.assertEqual(result['targets'], ['es', 'pt', 'ja'])
        self.assertFalse(result['blockers'])

    def test_done_is_not_automatically_reproduced(self):
        self.snap['summary']['items'][0]['status'] = 'done'
        self.assertIn('already done', str(self.register()['blockers']))

    def test_done_explicit_continuation_only_finishes_existing_pending_delivery(self):
        self.returned_setup()
        record = self.record()
        record['budget'] = 'existing-funded-pool'
        record['videos'][0]['members'] = ['existing-run']
        self.save(record)
        box_path = self.root / 'state/fireplay' / CODE / 'return-1.json'
        box = read_json(box_path)
        box['pending_locales'] = ['ko']
        write_json(box_path, box)
        self.snap['summary']['items'][0]['status'] = 'done'
        decision = {'authorization_ref': 'human:finish-pending', 'source_quote': 'Continue and finish',
                    'continue_pending_delivery': True, 'continuation_content_version': record['content_version']}
        self.assertFalse(self.register(decision)['blockers'])
        self.assertEqual(self.record()['budget'], 'existing-funded-pool')
        self.assertEqual(read_json(box_path), box)
        box['pending_locales'] = []
        write_json(box_path, box)
        with self.assertRaisesRegex(WorkflowError, 'Continuation needs'):
            self.register(decision)

    def test_done_continuation_cannot_start_new_production(self):
        record = self.register()
        self.snap['summary']['items'][0]['status'] = 'done'
        with self.assertRaisesRegex(WorkflowError, 'Continuation needs'):
            self.register({'authorization_ref': 'human:finish', 'source_quote': 'Continue',
                           'continue_pending_delivery': True,
                           'continuation_content_version': record['content_version']})

    def test_content_change_does_not_overwrite_existing_request(self):
        before = self.register()['content_version']
        self.snap['brief']['items'][0]['description'] += ' new copy'
        with self.assertRaisesRegex(WorkflowError, 'content changed'):
            self.register()
        self.assertEqual(self.record()['content_version'], before)

    def test_reviewed_unstarted_revision_preserves_old_sources_and_isolates_new_downloads(self):
        self.register()
        cached = self.root / f'work/runs/{CODE}-01/fireplay-source.mp4'
        cached.parent.mkdir(parents=True)
        cached.write_bytes(b'old cached source')
        old = self.record()
        old['videos'][0]['source'] = {'path': cached.relative_to(self.root).as_posix(),
                                     'sha256': file_hash(cached), 'duration': 5, 'width': 320, 'height': 240}
        self.save(old)
        for view in ('brief', 'summary'):
            self.snap[view]['items'][0]['locales'] = ['es', 'pt', 'fr']
        self.snap['brief']['items'][0]['description'] = 'https://youtu.be/abcdefghijk\n' + URL
        decision = {'authorization_ref': 'actual-standing-request', 'source_quote': 'Translate actual requirements',
                    'quantity_mode': 'one_per_locale', 'reviewed_content_version': old['content_version'],
                    'revision_reason': 'Add one source before the original and expand actual languages'}
        self.register(decision)
        new = self.record()
        self.assertCountEqual(new['targets'], ['es', 'pt', 'fr'])
        self.assertEqual(new['videos'][1]['source'], old['videos'][0]['source'])
        self.assertEqual(read_json(self.root / new['revision_history'][0]['path']), old)
        receipt = {'items': [{'youtube_url': 'https://youtu.be/abcdefghijk', 'youtube_video_id': 'abcdefghijk',
                             'status': 'found', 'material_id': MID, 'video_r2_url': 'https://example.org/new.mp4'}]}
        def fetch(url, local):
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(b'new cached source')
        with patch('video_localizer.kie.download', side_effect=fetch), patch('video_localizer.media.probe',
                return_value={'duration': 5, 'width': 320, 'height': 240}):
            fireplay.source(CODE, receipt, download=True, root=self.root)
        source = self.record()['videos'][0]['source']
        self.assertIn('-source-' + new['content_version'][:16], source['path'])
        self.assertEqual(cached.read_bytes(), b'old cached source')
        self.register(decision)
        self.assertEqual(len(self.record()['revision_history']), 1)
        self.assertFalse((self.root / 'state/budgets').exists())

    def test_unstarted_revision_rejects_wrong_version_and_any_production_state(self):
        self.register()
        old = self.record()
        self.snap['brief']['items'][0]['description'] += ' new copy'
        decision = {'authorization_ref': 'actual-standing-request', 'source_quote': 'Translate actual requirements',
                    'quantity_mode': 'one_per_locale', 'reviewed_content_version': 'wrong', 'revision_reason': 'Changed copy'}
        with self.assertRaisesRegex(WorkflowError, 'exact previous version'):
            self.register(decision)
        self.assertEqual(self.record(), old)
        decision['reviewed_content_version'] = old['content_version']
        for kind in ('budget', 'unknown_chat', 'members', 'return'):
            with self.subTest(kind=kind):
                record = copy.deepcopy(old)
                if kind == 'budget': record['budget'] = 'keep-original'
                if kind == 'unknown_chat': record['chat'] = {'state': 'unknown'}
                if kind == 'members': record['videos'][0]['members'] = ['already-started']
                return_path = self.root / 'state/fireplay' / CODE / 'return-1.json'
                if kind == 'return': write_json(return_path, {'state': 'unknown'})
                self.save(record)
                with self.assertRaisesRegex(WorkflowError, 'Only an unstarted'):
                    self.register(decision)
                self.assertEqual(self.record(), record)
                return_path.unlink(missing_ok=True)

    def test_status_time_and_assignee_edits_do_not_change_content_version(self):
        before = self.register()['content_version']
        self.snap['summary']['items'][0].update(status='in_progress', assigneeIds=['new'], updatedAt=utc_now())
        self.snap['brief']['items'][0]['updatedAt'] = self.snap['summary']['items'][0]['updatedAt']
        self.assertEqual(self.register()['content_version'], before)

    def test_youtube_forms_and_duplicate_source_urls(self):
        for url in (URL, 'https://youtu.be/Z6AJoQe5wI0?feature=share',
                    'https://www.youtube.com/watch?v=Z6AJoQe5wI0&t=1'):
            self.assertEqual(fireplay.youtube_id(url), 'Z6AJoQe5wI0')
        self.assertIsNone(fireplay.youtube_id('https://youtube.com.evil.invalid/watch?v=Z6AJoQe5wI0'))
        self.snap['brief']['items'][0]['description'] += '\nhttps://youtu.be/Z6AJoQe5wI0'
        self.assertEqual(len(self.register()['videos']), 1)

    def test_multiple_videos_have_numbered_titles_with_all_languages(self):
        self.snap['brief']['items'][0]['description'] += '\nhttps://youtu.be/OqVXEjB8tRs'
        self.snap['brief']['items'][0]['quantity'] = 4
        videos = self.register()['videos']
        self.assertEqual([v['title'] for v in videos], [CODE + '-1', CODE + '-2'])
        self.assertTrue(all(v['targets'] == ['es', 'ko'] for v in videos))

    def test_source_lookup_never_accepts_different_video(self):
        self.register()
        self.assertEqual(fireplay.source(CODE, root=self.root)['state'], 'needs_source_lookup')
        with self.assertRaisesRegex(WorkflowError, 'exact YouTube'):
            fireplay.source(CODE, {'items': [{'youtube_video_id': 'OqVXEjB8tRs', 'youtube_url': URL,
                                              'status': 'found'}]}, root=self.root)

    def test_source_download_is_probed_hash_bound_and_resumable(self):
        self.register()
        response = {'items': [{'youtube_video_id': 'Z6AJoQe5wI0', 'youtube_url': URL, 'status': 'found',
                              'material_id': MID, 'video_r2_url': 'https://example.com/source.mp4', 'duration': 16}]}
        def fetch(url, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'synthetic source')
        with patch('video_localizer.kie.download', side_effect=fetch) as call, patch('video_localizer.media.probe',
                   return_value={'duration': 16, 'width': 1080, 'height': 1920}):
            fireplay.source(CODE, response, download=True, root=self.root)
            fireplay.source(CODE, download=True, root=self.root)
        self.assertEqual(call.call_count, 1)
        path = self.root / self.record()['videos'][0]['source']['path']
        path.write_bytes(b'tampered')
        with self.assertRaisesRegex(WorkflowError, 'changed'):
            fireplay.source(CODE, download=True, root=self.root)

    def test_classification_only_dimensions_need_exact_resource_and_file_size(self):
        self.register()
        response = {'items': [{'youtube_video_id': 'Z6AJoQe5wI0', 'youtube_url': URL, 'status': 'found',
                    'material_id': MID, 'source_resource_id': RESOURCE,
                    'video_r2_url': 'https://example.com/source.mp4', 'duration': 8, 'width': 1080, 'height': 1920}]}
        path = self.root / f'work/runs/{CODE}-01/fireplay-source.mp4'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'synthetic downloaded bytes')
        resource = {'id': RESOURCE, 'backupUrl': 'https://example.com/source.mp4',
                    'youtubeVideoId': 'Z6AJoQe5wI0', 'fileSize': path.stat().st_size,
                    'extraInfo': {'youtube': {'resolution': {'hasExactDimensions': False}}}}
        with patch('video_localizer.media.probe', return_value={'duration': 7.7, 'width': 608, 'height': 1080}):
            for detail in (None, {'material': {'id': MID, 'resources': [{**resource, 'fileSize': 1}]}},
                           {'material': {'id': MID, 'resources': [{**resource, 'id': 'wrong'}]}}):
                with self.subTest(detail=detail), self.assertRaisesRegex(WorkflowError, 'dimensions differ'):
                    fireplay.source(CODE, {**response, 'material_detail': detail}, download=True, root=self.root)
            fireplay.source(CODE, {**response, 'material_detail': {'material': {'id': MID, 'resources': [resource]}}},
                            download=True, root=self.root)
        video = self.record()['videos'][0]
        self.assertEqual(video['source']['sha256'], file_hash(path))
        self.assertEqual(video['source_metadata_review']['actual_dimensions'], [608, 1080])

    def test_chat_preview_no_create_unknown_does_not_create_twice(self):
        self.register()
        preview = fireplay.chat(CODE, root=self.root)
        self.assertEqual(preview['title'], CODE)
        self.assertNotIn('chat', self.record()['videos'][0])
        fireplay.chat(CODE, dispatch=True, root=self.root)
        self.assertEqual(fireplay.chat(CODE, dispatch=True, root=self.root)['state'], 'unknown')
        fireplay.chat(CODE, {'threadId': THREAD, 'hostId': 'local', 'title': CODE}, root=self.root)
        self.assertEqual(fireplay.chat(CODE, dispatch=True, root=self.root)['threadId'], THREAD)

    def test_pending_client_thread_id_cannot_start_production(self):
        self.register()
        with self.assertRaisesRegex(WorkflowError, 'ready threadId'):
            fireplay.chat(CODE, {'clientThreadId': THREAD}, root=self.root)

    def test_start_requires_human_authority_and_dedicated_chat(self):
        self.downloaded()
        with self.assertRaisesRegex(WorkflowError, 'real human'):
            fireplay.start(CODE, {}, root=self.root)
        with self.assertRaisesRegex(WorkflowError, 'dedicated video chat'):
            fireplay.start(CODE, {'authority': 'user', 'authorization_ref': 'test-human',
                                 'user_request': 'Translate', 'mode': 'first'}, root=self.root)

    def test_start_resume_uses_same_budget_and_runs(self):
        self.downloaded()
        fireplay.chat(CODE, {'threadId': THREAD, 'title': CODE}, root=self.root)
        authority = {'authority': 'user', 'authorization_ref': 'test:human', 'user_request': 'Translate', 'mode': 'first'}
        with patch.object(workflow, 'ROOT', self.root), patch('video_localizer.media.probe',
                   return_value={'duration': 16, 'width': 1080, 'height': 1920}):
            first = fireplay.start(CODE, authority, root=self.root)
            second = fireplay.start(CODE, authority, root=self.root)
        self.assertEqual(first['budget'], second['budget'])
        self.assertEqual(len(list((self.root / 'runs').glob('*/run.json'))), 2)
        self.assertEqual(read_json(self.root / 'state/budgets' / (first['budget'] + '.json'))['credit_limit'], 120)
        shutil.rmtree(self.root / 'runs' / first['videos'][0]['members'][0])
        with patch.object(workflow, 'ROOT', self.root):
            resumed = fireplay.start(CODE, authority, root=self.root)
        self.assertEqual(resumed['state'], 'needs_resume')
        self.assertFalse((self.root / 'runs' / first['videos'][0]['members'][0]).exists())

    def test_return_requires_every_language(self):
        spec = self.returned_setup()
        spec['packages'].pop()
        with self.assertRaisesRegex(WorkflowError, 'All requested languages'):
            fireplay.prepare_return(CODE, spec, self.root)

    def partial_setup(self):
        spec = self.returned_setup()
        (self.root / 'state/fireplay' / CODE / 'return-1.json').unlink()
        return spec

    def complete_partial_locale(self, number, locale, material_id, all_ids):
        fireplay.dispatch(CODE, True, self.root)
        self.verify_upload(f'upload-{number}')
        fireplay.dispatch(CODE, True, self.root)
        fireplay.receipt(CODE, f'import-{number}', {'response': {'material_id': material_id}}, self.root)
        fireplay.dispatch(CODE, True, self.root)
        fireplay.receipt(CODE, f'verify-{number}', {'response': {'material': {
            'id': material_id, 'name': CODE + '-' + locale, 'isPublic': False,
            'sharedDeptId': 'test', 'tags': [locale, 'crush']}}}, self.root)
        operation = fireplay.dispatch(CODE, True, self.root)['operation']
        self.assertEqual(set(operation['arguments']['items'][0]['material_ids']), set(all_ids))
        fireplay.receipt(CODE, 'bind', {'response': {'success': True}, 'verification': {
            'serverTime': utc_now(), 'items': [{'id': RID, 'materials': [{'id': x} for x in all_ids]}]}}, self.root)

    def test_partial_return_extends_only_after_binding_and_never_reuploads_accepted_locale(self):
        spec = self.partial_setup()
        first = {**spec, 'partial': True, 'packages': spec['packages'][:1]}
        box = fireplay.prepare_return(CODE, first, self.root)
        self.assertEqual(box['pending_locales'], ['ko'])
        self.complete_partial_locale(1, 'es', MID, [MID])
        self.assertEqual(fireplay.dispatch(CODE, root=self.root)['state'], 'partially_returned')
        self.assertEqual(fireplay.status(CODE, self.root)['returns'][1], 'partially_returned')
        self.assertEqual(fireplay.status(CODE, self.root)['return_pending_locales'][1], ['ko'])
        record = self.record()
        self.assertEqual(fireplay_submission.bound_materials(record, record['videos'][0], self.root), [])
        self.assertEqual(fireplay.prepare_return(CODE, first, self.root)['state'], 'returned')
        with self.assertRaisesRegex(WorkflowError, 'uploaded again'):
            fireplay.prepare_return(CODE, {**first, 'packages': spec['packages']}, self.root)
        old_upload = copy.deepcopy(box['packages'][0])
        extended = fireplay.prepare_return(CODE, {**spec, 'partial': True, 'packages': spec['packages'][1:]}, self.root)
        self.assertEqual(extended['packages'][0], old_upload)
        self.assertEqual(extended['operations']['upload-1']['state'], 'verified')
        self.assertEqual(len(extended['binding_history']), 1)
        self.assertEqual(fireplay.dispatch(CODE, root=self.root)['operation']['id'], 'upload-2')
        second = '01a1396c-7410-7002-b480-4d535a387a57'
        self.complete_partial_locale(2, 'ko', second, [MID, second])
        self.assertEqual(fireplay.dispatch(CODE, root=self.root)['state'], 'returned')
        self.assertEqual(len(fireplay_submission.bound_materials(record, record['videos'][0], self.root)), 2)

    def test_partial_return_preserves_unknown_outbox_and_rejects_empty_batch(self):
        spec = self.partial_setup()
        first = {**spec, 'partial': True, 'packages': spec['packages'][:1]}
        fireplay.prepare_return(CODE, first, self.root)
        fireplay.dispatch(CODE, True, self.root)
        path = self.root / 'state/fireplay' / CODE / 'return-1.json'
        before = path.read_bytes()
        with self.assertRaisesRegex(WorkflowError, 'reconcile'):
            fireplay.prepare_return(CODE, {**spec, 'partial': True, 'packages': spec['packages'][1:]}, self.root)
        self.assertEqual(path.read_bytes(), before)
        with self.assertRaisesRegex(WorkflowError, 'All requested languages'):
            fireplay.prepare_return(CODE, {**spec, 'partial': True, 'packages': []}, self.root)

    def test_deferred_only_partial_can_append_without_retrying_unknown_upload(self):
        spec = self.partial_setup()
        first = {**spec, 'partial': True, 'packages': spec['packages'][:1]}
        fireplay.prepare_return(CODE, first, self.root)
        fireplay.dispatch(CODE, True, self.root)
        decision = {'authority': 'agent', 'authorization_ref': 'test:actual-timeout',
                    'source_quote': 'Synthetic timeout, no resource identifier; preserve unknown and do not retry.'}
        fireplay.defer_unknown_upload(CODE, 'es', decision, self.root)
        path = self.root / 'state/fireplay' / CODE / 'return-1.json'
        before = read_json(path)
        extended = fireplay.prepare_return(CODE, {**spec, 'partial': True, 'packages': spec['packages'][1:]}, self.root)
        self.assertEqual(extended['operations']['upload-1'], before['operations']['upload-1'])
        self.assertEqual(extended['deferred_uploads'], before['deferred_uploads'])
        self.assertEqual(extended['packages'][0], before['packages'][0])
        self.assertEqual(extended['pending_locales'], ['es'])
        self.assertEqual(fireplay.dispatch(CODE, root=self.root)['operation']['id'], 'upload-2')
        with self.assertRaises(WorkflowError):
            fireplay.prepare_return(CODE, first, self.root)
        self.complete_partial_locale(2, 'ko', MID, [MID])
        self.assertEqual(fireplay.dispatch(CODE, root=self.root)['state'], 'partially_returned')
        self.assertEqual(read_json(path)['operations']['upload-1']['state'], 'unknown')

    def test_partial_return_cannot_bypass_a_quality_hold(self):
        spec = self.partial_setup()
        with patch('video_localizer.quality_holds.require_clear', side_effect=WorkflowError('active quality hold')):
            with self.assertRaisesRegex(WorkflowError, 'quality hold'):
                fireplay.prepare_return(CODE, {**spec, 'partial': True, 'packages': spec['packages'][:1]}, self.root)
        self.assertFalse((self.root / 'state/fireplay' / CODE / 'return-1.json').exists())

    def test_multiple_originals_share_request_budget_and_separate_chats(self):
        # This is the supported per-video policy. Do not inherit a changed
        # deployment default when verifying its separate-chat contract.
        settings_path = self.root / 'config/fireplay-intake.json'
        settings = read_json(settings_path)
        settings['thread_policy'] = 'one_chat_per_source_video_all_locales'
        write_json(settings_path, settings)
        self.snap['brief']['items'][0]['description'] += '\nhttps://youtu.be/OqVXEjB8tRs'
        self.snap['brief']['items'][0]['quantity'] = 4
        self.register()
        record = self.record()
        for i, video in enumerate(record['videos'], 1):
            path = self.root / f'work/source-{i}.mp4'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f'synthetic original {i}'.encode())
            video['source'] = {'path': str(path.relative_to(self.root)), 'sha256': file_hash(path)}
        self.save(record)
        for i in (1, 2):
            fireplay.chat(CODE, {'threadId': THREAD if i == 1 else RID, 'title': f'{CODE}-{i}'}, i, root=self.root)
        authority = {'authority': 'user', 'authorization_ref': 'test:multi-source-user', 'user_request': 'Translate both', 'mode': 'first'}
        with patch.object(workflow, 'ROOT', self.root), patch('video_localizer.media.probe',
                   return_value={'duration': 16, 'width': 1080, 'height': 1920}):
            one = fireplay.start(CODE, authority, 1, self.root)
            # Closing video one must not block binding the next original.
            for name in one['videos'][0]['members']:
                shutil.rmtree(self.root / 'runs' / name)
            two = fireplay.start(CODE, authority, 2, self.root)
        self.assertEqual(one['budget'], two['budget'])
        self.assertEqual(len(list((self.root / 'runs').glob('*/run.json'))), 2)
        record = read_json(self.root / 'state/budgets' / (two['budget'] + '.json'))
        self.assertEqual(record['credit_limit'], 120)
        self.assertEqual(len(record['sources']), 2)

    def test_requirement_chat_is_reused_for_all_originals_when_configured(self):
        settings_path = self.root / 'config/fireplay-intake.json'
        settings = read_json(settings_path)
        settings['thread_policy'] = 'one_chat_per_requirement_all_sources_and_locales'
        write_json(settings_path, settings)
        self.snap['brief']['items'][0]['description'] += '\nhttps://youtu.be/OqVXEjB8tRs'
        self.snap['brief']['items'][0]['quantity'] = 4
        self.register()
        pending = fireplay.chat(CODE, root=self.root)
        self.assertEqual(pending['title'], CODE)
        self.assertEqual(fireplay.chat(CODE, index=2, root=self.root)['title'], CODE)
        ready = fireplay.chat(CODE, {'threadId': THREAD, 'title': CODE}, root=self.root)
        self.assertEqual(fireplay.chat(CODE, index=2, root=self.root), ready)
        self.assertTrue(all(video['chat']['threadId'] == THREAD for video in self.record()['videos']))
        with self.assertRaisesRegex(WorkflowError, 'different chat'):
            fireplay.chat(CODE, {'threadId': RID, 'title': CODE}, index=2, root=self.root)

    def test_chat_name_must_be_exact(self):
        self.register()
        with self.assertRaisesRegex(WorkflowError, 'exact requirement'):
            fireplay.chat(CODE, {'threadId': THREAD, 'title': 'An invented title'}, root=self.root)

    def test_attaching_original_requires_registered_event_and_preserves_budget(self):
        from video_localizer import budgets
        original = self.downloaded()
        authority = {'authority': 'user', 'authorization_ref': 'test:source-owner', 'user_request': 'Translate',
                     'mode': 'first', 'source': str(original), 'targets': ['es', 'ko']}
        with patch('video_localizer.media.probe', return_value={'duration': 16}):
            budget = budgets.open_request(authority, self.root)
        second = self.root / 'work/second.mp4'
        second.write_bytes(b'another declared original')
        with self.assertRaisesRegex(WorkflowError, 'original registered'):
            budgets.attach_source(budget['id'], second, 'unregistered-event', self.root)
        once = budgets.attach_source(budget['id'], second, authority['authorization_ref'], self.root)
        twice = budgets.attach_source(budget['id'], second, authority['authorization_ref'], self.root)
        self.assertEqual(once, twice)
        self.assertEqual(twice['credit_limit'], budget['credit_limit'])
        self.assertEqual(twice['reservations'], budget['reservations'])

    def test_original_cannot_escape_existing_request_ledger(self):
        from video_localizer import budgets
        original = self.downloaded()
        second = self.root / 'work/another.mp4'
        second.write_bytes(b'another original with its own request')
        authority = {'authority': 'user', 'authorization_ref': 'test:first-owner', 'user_request': 'Translate',
                     'mode': 'first', 'source': str(original), 'targets': ['es', 'ko']}
        with patch('video_localizer.media.probe', return_value={'duration': 16}):
            first = budgets.open_request(authority, self.root)
            budgets.open_request({**authority, 'source': str(second), 'authorization_ref': 'test:second-owner'}, self.root)
        with self.assertRaisesRegex(WorkflowError, 'already belongs'):
            budgets.attach_source(first['id'], second, authority['authorization_ref'], self.root)

    def test_best_available_cannot_auto_return(self):
        spec = self.returned_setup()
        manifest = self.root / spec['packages'][0]['package'] / 'manifest.json'
        data = read_json(manifest)
        data['metadata']['status'] = 'delivered_with_issues'
        write_json(manifest, data)
        with self.assertRaisesRegex(WorkflowError, 'quality-passed'):
            fireplay.prepare_return(CODE, spec, self.root)

    def test_metadata_pass_without_hash_bound_quality_is_insufficient(self):
        spec = self.returned_setup()
        manifest = self.root / spec['packages'][0]['package'] / 'manifest.json'
        data = read_json(manifest)
        data['files'] = [a for a in data['files'] if a['path'] == 'final.mp4']
        write_json(manifest, data)
        with self.assertRaisesRegex(WorkflowError, 'quality record'):
            fireplay.prepare_return(CODE, spec, self.root)

    def test_designer_attribution_cannot_be_guessed_from_login(self):
        spec = self.returned_setup()
        spec.pop('attribution')
        # The current policy requires Agent-resolved platform identity rather
        # than silently applying the historical unassigned default.
        with self.assertRaisesRegex(WorkflowError, 'Read Fireplay members'):
            fireplay.prepare_return(CODE, spec, self.root)
        defaults = read_json(self.root / 'config/fireplay-intake.json')
        defaults['designer_selection']['automatic_verified_user_ids'] = False
        defaults.pop('attribution')
        write_json(self.root / 'config/fireplay-intake.json', defaults)
        with self.assertRaisesRegex(WorkflowError, 'human-confirmed designer'):
            fireplay.prepare_return(CODE, spec, self.root)
        spec['attribution'] = {'designer_dids': '../D288', 'authorization_ref': 'test:attr', 'source_quote': 'test'}
        with self.assertRaisesRegex(WorkflowError, 'Invalid designer'):
            fireplay.prepare_return(CODE, spec, self.root)

    def test_stale_or_revoked_permission_blocks_dispatch(self):
        self.returned_setup()
        record = self.record()
        record['snapshot']['server_time'] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        self.save(record)
        with self.assertRaisesRegex(WorkflowError, 'expired'):
            fireplay.dispatch(CODE, True, self.root)
        record['snapshot']['server_time'] = utc_now()
        record['snapshot']['row']['canBindMaterials'] = False
        self.save(record)
        with self.assertRaisesRegex(WorkflowError, 'permission'):
            fireplay.dispatch(CODE, True, self.root)

    def test_dispatch_preview_no_journal_execute_journals_unknown_before_call(self):
        self.returned_setup()
        self.assertEqual(fireplay.dispatch(CODE, root=self.root)['state'], 'preview')
        result = fireplay.dispatch(CODE, True, self.root)
        self.assertFalse(result['external_call_executed'])
        self.assertEqual(result['operation']['id'], 'upload-1')
        args = read_json(result['operation']['arguments_file'])
        self.assertIn('file_base64', args)
        self.assertEqual(fireplay.dispatch(CODE, True, self.root)['state'], 'needs_reconciliation')

    def test_failed_receipt_never_advances_unknown_write(self):
        self.returned_setup()
        fireplay.dispatch(CODE, True, self.root)
        for response in ({'error': 'timeout'}, {'success': False}, {'code': 500}):
            with self.assertRaises(WorkflowError):
                fireplay.receipt(CODE, 'upload-1', {'response': response}, self.root)
        self.assertEqual(fireplay.dispatch(CODE, True, self.root)['state'], 'needs_reconciliation')

    def test_changed_file_cannot_be_uploaded_after_review(self):
        spec = self.returned_setup()
        (self.root / spec['packages'][0]['package'] / 'final.mp4').write_bytes(b'changed')
        with self.assertRaisesRegex(WorkflowError, 'changed'):
            fireplay.dispatch(CODE, True, self.root)

    def test_return_phases_and_readback_no_status_write(self):
        self.returned_setup()
        ids = [MID, '01a1396c-7410-7002-b480-4d535a387a57']
        for i in (1, 2):
            fireplay.dispatch(CODE, True, self.root)
            self.verify_upload(f'upload-{i}')
            request = fireplay.dispatch(CODE, True, self.root)['operation']
            self.assertEqual(request['arguments']['VedioSouce'], 'YouTube')
            self.assertEqual(request['arguments']['items'][0]['shared_dept_id'], 'test')
            self.assertEqual(request['arguments']['items'][0]['tags'], [('es', 'ko')[i - 1], 'crush'])
            self.assertEqual(request['arguments']['items'][0]['name'], CODE + '-' + ('es', 'ko')[i - 1])
            self.assertNotIn('confirmed', request['arguments'])
            fireplay.receipt(CODE, f'import-{i}', {'response': {'items': [{'material_id': ids[i - 1]}],
                              'check_url': 'https://example.com/check'}}, self.root)
            verification = fireplay.dispatch(CODE, True, self.root)
            self.assertEqual(verification['state'], 'needs_material_verification')
            lang = ('es', 'ko')[i - 1]
            fireplay.receipt(CODE, f'verify-{i}', {'response': {'material': {'id': ids[i - 1],
                'name': CODE + '-' + lang, 'isPublic': False, 'sharedDeptId': 'test',
                'tags': [{'name': lang}, {'name': 'crush'}]}}}, self.root)
        packet = fireplay.dispatch(CODE, True, self.root)['operation']
        self.assertEqual(packet['tool'], 'requirement_bind_materials')
        with self.assertRaises(WorkflowError):
            fireplay.receipt(CODE, 'bind', {'response': {}, 'verification': {'items': []}}, self.root)
        verification = {'serverTime': utc_now(), 'items': [{'id': RID, 'materials': [{'id': x} for x in ids]}]}
        spec = {'response': {'success': True}, 'verification': verification}
        fireplay.receipt(CODE, 'bind', spec, self.root)
        self.assertEqual(fireplay.dispatch(CODE, True, self.root)['state'], 'returned')
        self.assertFalse(fireplay.dispatch(CODE, root=self.root)['status_changed'])
        self.assertEqual(fireplay.receipt(CODE, 'bind', spec, self.root)['state'], 'verified')
        with self.assertRaisesRegex(WorkflowError, 'overwritten'):
            fireplay.receipt(CODE, 'bind', {**spec, 'changed': True}, self.root)

    def test_fixed_submission_instruction_is_carried_into_video_chat(self):
        self.register()
        prompt = fireplay.chat(CODE, root=self.root)['prompt']
        for fragment in ('共享到需求组', 'YouTube', '语言tag', '产品tag', '最后再绑定'):
            self.assertIn(fragment, prompt)

    def test_sharing_group_must_come_from_real_options_and_product_is_short(self):
        spec = self.returned_setup()
        spec['sharing_receipt'] = {'departments': [{'deptId': 'different', 'deptName': 'Test'}]}
        with self.assertRaisesRegex(WorkflowError, 'exact requirement group'):
            fireplay.prepare_return(CODE, spec, self.root)
        spec['sharing_receipt'] = {'departments': [{'deptId': 'test', 'deptName': 'Test'}]}
        spec['product_tag'] = 'too many words here'
        with self.assertRaisesRegex(WorkflowError, 'one- or two-word'):
            fireplay.prepare_return(CODE, spec, self.root)

    def test_requirement_od_prefix_resolves_to_returned_sharing_id(self):
        self.snap['brief']['items'][0]['deptId'] = 'od-test'
        spec = self.returned_setup()
        outbox = fireplay.prepare_return(CODE, spec, self.root)
        self.assertEqual(outbox['publication']['shared_dept_id'], 'test')

    def test_missing_language_product_or_group_readback_blocks_binding(self):
        self.returned_setup()
        fireplay.dispatch(CODE, True, self.root)
        self.verify_upload('upload-1')
        fireplay.dispatch(CODE, True, self.root)
        fireplay.receipt(CODE, 'import-1', {'response': {'material_id': MID}}, self.root)
        fireplay.dispatch(CODE, True, self.root)
        material = {'id': MID, 'name': CODE + '-es', 'isPublic': False, 'sharedDeptId': 'test', 'tags': ['es']}
        with self.assertRaisesRegex(WorkflowError, 'missing language or product'):
            fireplay.receipt(CODE, 'verify-1', {'response': {'material': material}}, self.root)
        material.update(tags=['es', 'crush'], sharedDeptId='wrong-group')
        with self.assertRaisesRegex(WorkflowError, 'sharing'):
            fireplay.receipt(CODE, 'verify-1', {'response': {'material': material}}, self.root)
        self.assertEqual(fireplay.dispatch(CODE, True, self.root)['operation']['id'], 'verify-1')

    def test_connector_envelope_and_error(self):
        wrapped = {'content': [{'type': 'text', 'text': json.dumps(self.snap)}]}
        fireplay.register(CODE, wrapped, root=self.root)
        with self.assertRaisesRegex(WorkflowError, 'Connector returned'):
            fireplay.payload({'isError': True, 'content': []})

    def test_cli_and_stdio_entrypoint(self):
        result = subprocess.run([sys.executable, 'bin/va.py', 'fireplay', CODE], cwd=PROJECT,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['state'], 'needs_requirement')
        request = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
            'name': 'localizer_fireplay', 'arguments': {'code': CODE, 'action': 'lookup'}}}
        result = subprocess.run([sys.executable, 'bin/mcp_server.py'], cwd=PROJECT,
                                input=json.dumps(request) + '\n', capture_output=True, text=True)
        response = json.loads(result.stdout)
        self.assertFalse(response['result']['isError'])


if __name__ == '__main__':
    unittest.main()
