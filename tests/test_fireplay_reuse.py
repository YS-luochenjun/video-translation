from hashlib import md5
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from test_fireplay import CODE, MID, PROJECT, RESOURCE, RID, THREAD, URL, fixture
from video_localizer import bundles, fireplay, fireplay_reuse, fireplay_reuse_index, fireplay_submission, library, media, workflow
from video_localizer.common import WorkflowError, file_hash, object_hash, read_json, utc_now, write_json


OLD_CODE = 'WOW-20261026-001'
OLD_REQUIREMENT = '01a17b8f-0cf6-7b63-868a-56b46d725264'
NEW_MATERIAL = '01a15d9f-08bd-7f3c-9de2-0c1e77ad3fe5'
SECOND_MATERIAL = '01a15d9f-08bd-7f3c-9de2-0c1e77ad3fe6'
R2_URL = 'https://material-library.mixberry.io/materials/old.mp4'
AUTHORITY = {'authority': 'user', 'authorization_ref': 'test:human', 'user_request': 'Translate', 'mode': 'first'}


class HistoricalFireplayTests(unittest.TestCase):
    def setUp(self):
        temp_base = PROJECT / 'work/test-tmp'
        temp_base.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=temp_base)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        shutil.copytree(PROJECT / 'config', self.root / 'config', ignore=shutil.ignore_patterns('*.local.json'))
        write_json(self.root / 'config/fireplay-youtube-routing.json', {'require_requirement_group': False})
        dns = patch('video_localizer.kie.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('93.184.216.34', 443))])
        dns.start()
        self.addCleanup(dns.stop)
        self.original = self.root / 'work/source.mp4'
        self.original.parent.mkdir()
        self.original.write_bytes(b'Test source identity')

    def register(self, locales=None, *, dedicated=False):
        snapshot = fixture()
        if locales:
            for view in ('summary', 'brief'):
                snapshot[view]['items'][0].update(locales=locales, quantity=len(locales))
        fireplay.register(CODE, snapshot, root=self.root)
        path = fireplay._folder(CODE, self.root) / 'request.json'
        record = read_json(path)
        record['videos'][0]['source'] = {'path': 'work/source.mp4', 'sha256': file_hash(self.original)}
        record['videos'][0]['chat'] = {'state': 'ready', 'threadId': THREAD}
        if dedicated:
            record['thread_policy'] = 'one_chat_per_source_video_all_locales'
        write_json(path, record)

    def test_new_batch_waits_for_scoped_preflight_and_records_candidate_outcomes(self):
        self.register(dedicated=True)
        self.assertEqual(fireplay.start(CODE, AUTHORITY, root=self.root)['state'], 'reuse_preflight_required')
        self.assertFalse((self.root / 'state/batches').exists())
        self.assertFalse((self.root / 'state/budgets').exists())
        with self.assertRaisesRegex(WorkflowError, 'saved for this source'):
            fireplay_reuse.preflight(CODE, {'search_sha256s': ['0' * 64]}, root=self.root)
        report = self.search()
        spec = {'search_sha256s': [report['search_sha256']],
                'fallback': {'kind': 'lookup_incomplete', 'reason': 'Fixture omitted the keyword query'},
                'candidate_dispositions': [{'candidate_id': report['candidates'][0]['id'], 'locale': 'es',
                                            'decision': 'unsuitable', 'reason': 'Fixture has another edit'}]}
        result = fireplay_reuse.preflight(CODE, spec, root=self.root)
        self.assertEqual(result['production_locales'], ['es', 'ko'])
        self.assertEqual(result['candidate_dispositions'], spec['candidate_dispositions'])
        with patch.object(workflow, 'ROOT', self.root), patch.object(media, 'probe',
                return_value={'duration': 1, 'width': 160, 'height': 288}):
            first = fireplay.start(CODE, AUTHORITY, root=self.root)
            self.assertEqual(fireplay.start(CODE, AUTHORITY, root=self.root)['budget'], first['budget'])
        batch = read_json(self.root / 'state/batches' / f'{CODE}.json')
        self.assertIn('reuse_preflight_sha256', batch)

    def search(self, *, keyword=False, relation='source', description=URL, tags=None, delivered_url=None,
               status='done', selection=None):
        kind = 'keyword' if keyword else 'youtube'
        arguments = fireplay_reuse.search(CODE, root=self.root)['queries']
        filters = {'keyword': arguments[kind]['keyword']} if keyword else {'youtube_video_ids': [fireplay.youtube_id(URL)]}
        trace = {'searches': {kind: {'arguments': arguments[kind], 'response': {
            'view': 'summary', 'serverTime': utc_now(), 'query_meta': {'filters_applied': filters},
            'items': [{'id': OLD_REQUIREMENT, 'matched_relations': [relation]}]}}}, 'deliveries': [
                {'view': 'delivery', 'serverTime': utc_now(), 'items': [{
                    'id': OLD_REQUIREMENT, 'code': OLD_CODE, 'description': description, 'status': status,
                    'materialSelection': selection or {},
                    'materials': [{'id': MID, 'type': 'video', 'name': 'legacy', 'tagNames': tags or ['ES'],
                                   'videoUrl': delivered_url}]}]}]}
        if keyword:
            trace['searches']['youtube'] = {'arguments': arguments['youtube'], 'error': '120000ms timeout'}
        return fireplay_reuse.search(CODE, trace, root=self.root)

    def capture(self, *, allowed=True, distinct_backup=False):
        search = self.search()
        translated = self.root / 'work/translated.mp4'
        media.ffmpeg(['-f', 'lavfi', '-i', 'color=red:s=160x288:d=1', '-f', 'lavfi', '-i',
                      'sine=frequency=440:duration=1', '-shortest', '-c:v', 'libx264', '-c:a', 'aac', translated])
        detail = {'material': {'id': MID, 'type': 'video', 'status': 'available', 'access': {'canUse': allowed},
                               'currentVideoResourceId': RESOURCE, 'videoR2Url': R2_URL,
                               'resources': [{'id': RESOURCE, 'backupUrl': R2_URL, 'mimeType': 'video/mp4',
                                              'status': 'normal', 'storageStatus': 'r2',
                                              'fileSize': translated.stat().st_size,
                                              'md5': md5(translated.read_bytes(), usedforsecurity=False).hexdigest()}]}}
        if distinct_backup:
            resource = detail['material']['resources'][0]
            resource['fileSize'] -= 512
            resource['extraInfo'] = {'youtubeUpload': {'sourceUrl': R2_URL.replace('old.mp4', 'ingest.mp4')}}
        spec = {'search_sha256': search['search_sha256'], 'candidate_id': search['candidates'][0]['id'],
                'material_detail': detail}
        with patch('video_localizer.kie.download', side_effect=lambda url, path, **kwargs: shutil.copyfile(translated, path)):
            return fireplay_reuse.capture(CODE, spec, root=self.root)

    def fixture_review(self, captured):
        edge = {'decision': 'pass', 'original': 'test source fixture tone', 'delivery': 'test destination fixture tone',
                'original_language_residue': 'synthetic fixture', 'target_speech_completeness': 'synthetic fixture'}
        return {'capture': captured['capture'], 'video_sha256': captured['video_sha256'], 'locale': 'es',
                'reviewer': 'offline test fixture', 'target_voice_needed': True, 'target_language_observed': 'es',
                'observations': dict.fromkeys(fireplay_reuse.OBSERVATIONS, 'synthetic review fixture'),
                'head_tail_audio': {'head': edge, 'tail': edge}, 'decision': 'eligible'}

    def fixture_media(self):
        media.ffmpeg(['-f', 'lavfi', '-i', 'color=blue:s=160x288:d=1', '-f', 'lavfi', '-i',
                      'sine=frequency=550:duration=1', '-shortest', '-c:v', 'libx264', '-c:a', 'aac', self.original])

    def prepare(self, package, partial=False):
        spec = {'packages': [package], 'partial': partial, 'upload_route': 'bytes',
                'sharing_receipt': {'departments': [{'deptId': 'test', 'deptName': 'Test'}]},
                'designer_receipt': {'member_directory': {
                    'members': [{'feishuUserId': 'test', 'username': '罗晨钧'}],
                    'query_meta': {'observed_at': utc_now()}}},
                'authority': {'authorization_ref': 'test:host-event', 'source_quote': 'Offline fixture',
                              'actions': ['upload', 'import', 'bind']}}
        return fireplay.prepare_return(CODE, spec, self.root)

    def accept_return(self, slot, new_material, bound_materials):
        fireplay.dispatch(CODE, True, self.root)
        fireplay.receipt(CODE, f'upload-{slot}', {'response': {'publicUrl': R2_URL, 'resourceId': RESOURCE}},
                         self.root)
        operation = fireplay.dispatch(CODE, True, self.root)['operation']
        arguments = operation['arguments']['items'][0]
        fireplay.receipt(CODE, f'import-{slot}', {'response': {'results': [{
            'success': True, 'material_imported': True, 'material_id': new_material,
            'name': arguments['name'], 'shared_dept_id': arguments['shared_dept_id'], 'is_public': False,
            'tags': arguments['tags']}]}, 'youtube_status': {'state': 'queued'}}, self.root)
        binding = fireplay.dispatch(CODE, True, self.root)['operation']
        self.assertEqual(binding['arguments']['items'][0]['material_ids'], bound_materials)
        fireplay.receipt(CODE, 'bind', {'response': {}, 'verification': {
            'serverTime': utc_now(), 'items': [{'id': RID, 'materials': [{'id': item} for item in bound_materials]}]}},
                         self.root)

    def test_timeout_fallback_requires_the_exact_original_link(self):
        self.register()
        report = self.search(keyword=True, tags=['ES', 'kr'])
        self.assertEqual(report['failed_or_truncated_searches'], ['youtube'])
        self.assertEqual(report['candidates'][0]['locales_from_tags'], ['es', 'ko'])
        unrelated = self.search(keyword=True, description='promotional mention of Z6AJoQe5wI0')
        self.assertEqual(unrelated['state'], 'lookup_incomplete')
        self.assertEqual(unrelated['candidates'], [])

    def test_linked_rework_skips_search_after_platform_status_changes(self):
        self.register()
        path = fireplay._folder(CODE, self.root) / 'request.json'
        record = read_json(path)
        record['videos'][0].pop('chat')
        record['videos'][0].pop('source')
        brief = record['snapshot']['brief']
        for status in ('not_started', 'in_progress', 'done'):
            for title, description in (
                ('【驳回返工】face翻译', URL),
                ('样片翻译', f'基于原需求 {OLD_CODE}「样片翻译」驳回返工。\n\n原需求说明：\n{URL}'),
            ):
                with self.subTest(status=status, title=title):
                    brief.update(title=title, description=description)
                    record['snapshot']['row']['status'] = status
                    write_json(path, record)
                    result = fireplay_reuse.search(CODE, {'searches': {'unexpected': {}}}, root=self.root)
                    self.assertEqual(result['state'], 'skipped_linked_rework')
                    self.assertEqual(result['queries'], {})
                    self.assertNotIn('material_usage_query', result)
        prompt = fireplay.chat(CODE, root=self.root)['prompt']
        self.assertIn('按驳回原因及问题素材确认本次返工范围', prompt)
        self.assertNotIn('fireplay-reuse', prompt)

    def index_history(self, *, state='verified'):
        folder = fireplay._folder(OLD_CODE, self.root)
        write_json(folder / 'request.json', {
            'code': OLD_CODE, 'requirement_id': OLD_REQUIREMENT, 'content_version': 'old',
            'snapshot': {'row': {'status': 'done'}}, 'videos': [{
                'index': 1, 'targets': ['es'], 'youtube_video_id': 'uPStream001',
                'source': {'sha256': file_hash(self.original), 'path': 'runs/expired/source.mp4'},
            }],
        })
        write_json(folder / 'return-1.json', {
            'requirement_id': OLD_REQUIREMENT, 'content_version': 'old', 'video_index': 1,
            'state': 'returned', 'packages': [{'locale': 'es', 'sha256': 'b' * 64}],
            'operations': {'bind': {'state': state, 'result': {'material_ids': [MID]}},
                           'import-1': {'state': 'verified', 'result': {'material_id': MID}},
                           'verify-1': {'state': 'verified'}},
        })
        self.assertTrue(fireplay_reuse_index.refresh_request(OLD_CODE, self.root))

    def indexed_delivery(self, *, status='done', materials=None, selection=None):
        return {'view': 'delivery', 'serverTime': utc_now(),
                'query_meta': {'filters_applied': {'scope': 'all', 'requirement_ids': [OLD_REQUIREMENT]}},
                'items': [{'id': OLD_REQUIREMENT, 'code': OLD_CODE, 'status': status,
                           'materials': materials if materials is not None else [
                               {'id': MID, 'type': 'video', 'tagNames': ['ES']}],
                           'materialSelection': selection or {}}]}

    def test_local_index_survives_media_expiry_and_uses_current_binding_and_selection(self):
        self.register()
        self.index_history()
        plan = fireplay_reuse.search(CODE, root=self.root, profile='quick')
        self.assertEqual(plan['state'], 'local_match')
        self.assertEqual(plan['queries'], {})
        self.assertEqual(plan['local_delivery_query']['requirement_ids'], [OLD_REQUIREMENT])
        receipt = self.indexed_delivery()
        result = fireplay_reuse.search(CODE, {'local_deliveries': [receipt]}, root=self.root, profile='quick')
        self.assertEqual(result['state'], 'local_candidates')
        self.assertEqual(result['candidates'][0]['material_id'], MID)
        self.assertEqual(result['candidates'][0]['indexed_locale'], 'es')
        for changed in (self.indexed_delivery(status='rejected'), self.indexed_delivery(materials=[]),
                        self.indexed_delivery(selection={'status': 'waiting_selection'})):
            with self.subTest(row=changed['items'][0]):
                result = fireplay_reuse.search(CODE, {'local_deliveries': [changed]}, root=self.root)
                self.assertEqual(result['state'], 'local_match_unavailable')
                self.assertEqual(result['candidates'], [])
        self.index_history(state='unknown')
        self.assertEqual(fireplay_reuse.search(CODE, root=self.root)['state'], 'search_ready')

    def test_local_index_finds_original_from_delivered_hash(self):
        self.register(['en'])
        self.index_history()
        path = fireplay._folder(CODE, self.root) / 'request.json'
        record = read_json(path)
        record['videos'][0]['source']['sha256'] = 'b' * 64
        write_json(path, record)
        report = fireplay_reuse.search(CODE, {'local_deliveries': [self.indexed_delivery()]}, root=self.root)
        self.assertEqual(report['candidates'], [])
        self.assertEqual(report['original_candidates'][0]['source_youtube_id'], 'uPStream001')
        self.assertEqual(report['original_candidates'][0]['input_material_id'], MID)

    def test_delivery_youtube_id_migrates_and_rechecks_current_binding(self):
        self.register(['en'])
        self.index_history()
        folder = fireplay._folder(OLD_CODE, self.root)
        box_path = folder / 'return-1.json'
        box = read_json(box_path)
        material = {'id': MID, 'type': 'video', 'tagNames': ['ES'], 'videoUrl': URL}
        delivery = self.indexed_delivery(materials=[material])
        receipt = {'verification': delivery}
        box['operations']['bind']['receipt_sha256'] = object_hash(receipt)
        box['operations']['bind']['result']['verification_sha256'] = object_hash(delivery)
        receipt_path = folder / 'receipts/1-bind.json'
        write_json(receipt_path, receipt)
        write_json(box_path, box)
        with sqlite3.connect(fireplay_reuse_index.database_path(self.root)) as database:
            database.execute('DROP INDEX assets_delivery_youtube')
            database.execute('ALTER TABLE assets DROP COLUMN delivery_youtube_id')
            database.execute("INSERT OR REPLACE INTO checkpoints VALUES ('all_requests', 9999999999)")
        path = fireplay._folder(CODE, self.root) / 'request.json'
        record = read_json(path)
        record['videos'][0]['source']['sha256'] = 'a' * 64
        write_json(path, record)
        self.assertEqual(fireplay_reuse.search(CODE, root=self.root)['state'], 'local_match')
        result = fireplay_reuse.search(CODE, {'local_deliveries': [delivery]}, root=self.root)
        original = result['original_candidates'][0]
        self.assertEqual(original['input_youtube_video_id'], fireplay.youtube_id(URL))
        self.assertEqual(original['source_youtube_id'], 'uPStream001')
        changed = self.indexed_delivery(materials=[{**material, 'videoUrl': 'https://youtu.be/sOmEvid0001'}])
        self.assertEqual(fireplay_reuse.search(CODE, {'local_deliveries': [changed]}, root=self.root)
                         ['original_candidates'], [])
        write_json(receipt_path, {'verification': delivery, 'different_receipt': True})
        self.assertTrue(fireplay_reuse_index.refresh_request(OLD_CODE, self.root))
        self.assertEqual(fireplay_reuse.search(CODE, root=self.root)['state'], 'search_ready')

    def test_completion_readback_indexes_video_published_after_binding(self):
        self.register(['en'])
        self.index_history()
        path = fireplay._folder(CODE, self.root) / 'request.json'
        record = read_json(path)
        record['videos'][0]['source']['sha256'] = 'a' * 64
        write_json(path, record)
        self.assertEqual(fireplay_reuse.search(CODE, root=self.root)['state'], 'search_ready')
        delivery = self.indexed_delivery(materials=[
            {'id': MID, 'type': 'video', 'tagNames': ['ES'], 'videoUrl': URL}])
        result = fireplay_submission.verify_completion(OLD_CODE, delivery, self.root)
        self.assertTrue(result['complete'])
        self.assertEqual(result['verified'][0]['delivery_youtube_id'], fireplay.youtube_id(URL))
        self.assertTrue(fireplay_reuse_index.refresh_request(OLD_CODE, self.root))
        report = fireplay_reuse.search(CODE, {'local_deliveries': [delivery]}, root=self.root)
        self.assertEqual(report['original_candidates'][0]['source_youtube_id'], 'uPStream001')

    def test_quick_miss_reuses_only_complete_scope_for_five_minutes(self):
        self.register()
        path = fireplay._folder(CODE, self.root) / 'request.json'
        record = read_json(path)
        record['snapshot']['raw']['summary']['operator'] = 'fixture owner'
        write_json(path, record)
        quick = fireplay_reuse.search(CODE, root=self.root, profile='quick')
        full = fireplay_reuse.search(CODE, root=self.root, profile='full')
        self.assertEqual(set(quick['queries']), {'keyword'})
        self.assertEqual(set(full['queries']), {'keyword', 'youtube'})
        usage = {'items': [{'videoId': fireplay.youtube_id(URL), 'materialCount': 0, 'materialRecords': []}]}
        response = {'view': 'summary', 'operator': 'fixture owner', 'serverTime': utc_now(),
                    'total': 0, 'items': [], 'query_meta': {'total_exact': True, 'offset': 0, 'filters_applied': {
                        'scope': 'all', 'asset_type': 'video', 'keyword': fireplay.youtube_id(URL)}}}
        trace = {'material_usage': usage, 'searches': {'keyword': {
            'arguments': quick['queries']['keyword'], 'response': response}}}
        rows = response.pop('items')
        result = fireplay_reuse.search(CODE, trace, root=self.root, profile='quick')
        self.assertEqual(result['state'], 'lookup_incomplete')
        response['items'] = rows
        result = fireplay_reuse.search(CODE, {'searches': trace['searches']}, root=self.root, profile='quick')
        self.assertEqual(result['failed_or_truncated_searches'], ['material_usage'])
        response['next_offset'] = 20
        result = fireplay_reuse.search(CODE, trace, root=self.root, profile='quick')
        self.assertEqual(result['state'], 'lookup_incomplete')
        self.assertEqual(fireplay_reuse.search(CODE, root=self.root, profile='quick')['state'], 'search_ready')
        response.pop('next_offset')
        with patch.object(fireplay_reuse_index, 'time', return_value=1000):
            miss = fireplay_reuse.search(CODE, trace, root=self.root, profile='quick')
            self.assertEqual(miss['state'], 'no_quick_match')
            ready = fireplay_reuse.preflight(CODE, {'search_sha256s': [miss['search_sha256']]}, root=self.root)
            self.assertEqual(ready['production_locales'], ['es', 'ko'])
            self.assertIsNone(ready['fallback'])
            self.assertEqual(fireplay_reuse.search(CODE, root=self.root, profile='quick')['state'], 'cached_no_match')
            second_code = 'APC-20261027-021'
            write_json(fireplay._folder(second_code, self.root) / 'request.json', {
                **record, 'code': second_code, 'requirement_id': NEW_MATERIAL})
            self.assertEqual(fireplay_reuse.search(second_code, root=self.root, profile='quick')['state'],
                             'cached_no_match')
            self.assertEqual(fireplay_reuse.search(second_code, root=self.root, profile='full')['state'],
                             'search_ready')
            self.assertEqual(fireplay_reuse.search(second_code, {'refresh': True}, root=self.root,
                                                   profile='quick')['state'], 'search_ready')
            record['snapshot']['raw']['summary']['operator'] = 'different fixture owner'
            write_json(path, record)
            self.assertEqual(fireplay_reuse.search(CODE, root=self.root, profile='quick')['state'], 'search_ready')
        with patch.object(fireplay_reuse_index, 'time', return_value=1301):
            self.assertEqual(fireplay_reuse.search(second_code, root=self.root, profile='quick')['state'],
                             'search_ready')

    @unittest.skipUnless(media.tools_available(), 'FFmpeg and ffprobe required for real media fixtures')
    def test_linked_rework_blocks_earlier_reuse_evidence_and_start_produces_target(self):
        self.fixture_media()
        self.register(['es'], dedicated=True)
        captured = self.capture()
        review = self.fixture_review(captured)
        package = fireplay_reuse.package(CODE, review, root=self.root)
        self.prepare(package)
        path = fireplay._folder(CODE, self.root) / 'request.json'
        record = read_json(path)
        record['snapshot']['brief']['title'] = '【驳回返工】face翻译'
        write_json(path, record)
        with self.assertRaisesRegex(WorkflowError, 'Linked rework'):
            fireplay_reuse.capture(CODE, {}, root=self.root)
        with self.assertRaisesRegex(WorkflowError, 'Linked rework'):
            fireplay_reuse.package(CODE, review, root=self.root)
        with self.assertRaisesRegex(WorkflowError, 'Linked rework'):
            self.prepare(package)
        with self.assertRaisesRegex(WorkflowError, 'Linked rework'):
            fireplay.dispatch(CODE, True, self.root)
        self.assertEqual(read_json(path.parent / 'return-1.json')['operations'], {})
        with patch.object(workflow, 'ROOT', self.root):
            started = fireplay.start(CODE, AUTHORITY, root=self.root)
        self.assertEqual(started['videos'][0]['members'], [f'{CODE}-01'])

    def test_delivery_relation_alone_does_not_prove_original_identity(self):
        self.register()
        report = self.search(relation='delivery', delivered_url=URL.replace('Z6A', 'z6A'))
        self.assertEqual(report['candidates'], [])
        self.assertEqual(report['historical_deliveries'], [])
        self.assertEqual(report['unverified_delivery_requirement_ids'], [OLD_REQUIREMENT])

    def test_historical_delivery_surfaces_original_brief_without_reuse_approval(self):
        self.register()
        original = 'https://www.youtube.com/watch?v=n2KaJuipZIw'
        report = self.search(relation='delivery', description=original, delivered_url=URL, tags=['pt'])
        self.assertEqual(report['state'], 'historical_delivery_found')
        self.assertEqual(report['candidates'], [])
        self.assertEqual(report['historical_deliveries'], [{
            'requirement_id': OLD_REQUIREMENT, 'requirement_code': OLD_CODE, 'material_id': MID,
            'youtube_video_id': fireplay.youtube_id(URL), 'tags': ['pt'], 'requirement_status': 'done',
            'brief_source_links': [{'source_url': original, 'youtube_video_id': 'n2KaJuipZIw'}],
        }])
        self.assertEqual(report['original_candidates'][0]['material_lookup']['arguments']['urls'], [original])

    def test_material_reverse_lookup_recovers_delivery_when_youtube_times_out(self):
        self.register()
        path = fireplay._folder(CODE, self.root) / 'request.json'
        record = read_json(path)
        record['videos'][0]['resolved'] = {'material_id': MID}
        write_json(path, record)
        queries = fireplay_reuse.search(CODE, root=self.root)['queries']
        trace = {'searches': {
            'material': {'arguments': queries['material'], 'response': {
                'view': 'summary', 'serverTime': utc_now(),
                'query_meta': {'filters_applied': {'material_ids': [MID]}},
                'items': [{'id': OLD_REQUIREMENT, 'matched_relations': ['delivery']}]}},
            'youtube': {'arguments': queries['youtube'], 'error': '120000ms timeout'},
        }, 'deliveries': [{'view': 'delivery', 'serverTime': utc_now(), 'items': [{
            'id': OLD_REQUIREMENT, 'code': OLD_CODE, 'description': 'https://youtu.be/n2KaJuipZIw',
            'materials': [{'id': MID, 'type': 'video', 'tagNames': ['pt']}],
        }]}]}
        report = fireplay_reuse.search(CODE, trace, root=self.root)
        self.assertEqual(report['state'], 'historical_delivery_found')
        self.assertIn('youtube', report['failed_or_truncated_searches'])
        self.assertEqual(report['historical_deliveries'][0]['material_id'], MID)
        self.assertEqual(report['candidates'], [])

    def test_rejected_history_preserves_lineage_but_cannot_supply_a_reuse_candidate(self):
        self.register()
        for status in ('rejected', 'ai_rejected'):
            with self.subTest(status=status):
                report = self.search(status=status, tags=['es'])
                self.assertEqual(report['candidates'], [])
                self.assertEqual(report['rejected_requirements'], [
                    {'requirement_id': OLD_REQUIREMENT, 'requirement_code': OLD_CODE, 'status': status}])
                lineage = self.search(relation='delivery', status=status, delivered_url=URL)
                self.assertEqual(lineage['historical_deliveries'][0]['requirement_status'], status)
                self.assertEqual(lineage['candidates'], [])
                self.assertEqual(lineage['original_candidates'], [])

    def test_exact_youtube_material_duplicates_are_searched_together(self):
        self.register()
        video_id = fireplay.youtube_id(URL)
        usage = {'items': [{'videoId': video_id, 'materialCount': 2, 'materialRecords': [
            {'materialId': SECOND_MATERIAL, 'resourceUrl': URL}, {'materialId': MID, 'resourceUrl': URL},
        ]}]}
        plan = fireplay_reuse.search(CODE, {'material_usage': usage}, root=self.root)
        args = plan['queries']['material']
        self.assertEqual(args['material_ids'], sorted([SECOND_MATERIAL, MID]))
        trace = {'material_usage': usage, 'searches': {'material': {'arguments': args, 'response': {
            'view': 'summary', 'serverTime': utc_now(),
            'query_meta': {'filters_applied': {'material_ids': args['material_ids']}},
            'items': [{'id': OLD_REQUIREMENT, 'matched_relations': ['delivery']}],
        }}}, 'deliveries': [{'view': 'delivery', 'serverTime': utc_now(), 'items': [{
            'id': OLD_REQUIREMENT, 'code': OLD_CODE,
            'materials': [{'id': SECOND_MATERIAL, 'type': 'video', 'tagNames': ['en']}],
        }]}]}
        self.assertEqual(fireplay_reuse.search(CODE, trace, root=self.root)['historical_deliveries'][0]['material_id'],
                         SECOND_MATERIAL)
        usage['items'][0]['materialRecords'][1]['resourceUrl'] = URL.replace('Z6A', 'z6A')
        with self.assertRaisesRegex(WorkflowError, 'different YouTube video'):
            fireplay_reuse.search(CODE, trace, root=self.root)

    def test_waiting_for_platform_selection_cannot_supply_candidates(self):
        self.register()
        selection = {'status': 'waiting_selection', 'selectionUrl': 'https://example.com/selection'}
        report = self.search(selection=selection, tags=['es'])
        self.assertEqual(report['state'], 'lookup_incomplete')
        self.assertEqual(report['candidates'], [])
        self.assertEqual(report['platform_selection'], [{'requirement_id': OLD_REQUIREMENT, **selection}])

    def test_no_visible_match_distinguishes_empty_complete_and_truncated_searches(self):
        self.register()
        queries = fireplay_reuse.search(CODE, root=self.root)['queries']
        trace = {'searches': {
            kind: {'arguments': args, 'response': {
                'view': 'summary', 'serverTime': utc_now(), 'items': [],
                'query_meta': {'filters_applied': filters, 'total_exact': True},
            }}
            for kind, args, filters in (
                ('youtube', queries['youtube'], {'youtube_video_ids': [fireplay.youtube_id(URL)]}),
                ('keyword', queries['keyword'], {'keyword': fireplay.youtube_id(URL)}),
            )}}
        self.assertEqual(fireplay_reuse.search(CODE, trace, root=self.root)['state'], 'no_visible_match')
        response = trace['searches']['youtube']['response']
        for page_info in ({'next_offset': 20}, {'next_cursor': 'page-two'},
                          {'query_meta': {**response['query_meta'], 'source_limit_reached': True}},
                          {'query_meta': {**response['query_meta'], 'total_exact': False}}):
            with self.subTest(page_info=page_info):
                trace['searches']['youtube']['response'] = {**response, **page_info}
                result = fireplay_reuse.search(CODE, trace, root=self.root)
                self.assertEqual(result['state'], 'lookup_incomplete')
                self.assertEqual(result['failed_or_truncated_searches'], ['youtube'])

    @unittest.skipUnless(media.tools_available(), 'FFmpeg and ffprobe required for real media fixtures')
    def test_partial_reuse_only_creates_missing_locale_and_preserves_budget(self):
        self.fixture_media()
        self.register(dedicated=True)
        captured = self.capture(distinct_backup=True)
        self.assertEqual(captured['byte_identity']['verified_by'], 'md5')
        self.assertTrue(captured['byte_identity']['url'].endswith('/ingest.mp4'))
        self.assertNotEqual(captured['byte_identity']['bytes'], captured['resource']['fileSize'])
        self.assertIn('delivery-tail.wav', captured['evidence'])
        package = fireplay_reuse.package(CODE, self.fixture_review(captured), root=self.root)
        outbox = self.prepare(package, partial=True)
        self.assertEqual(outbox['pending_locales'], ['ko'])
        self.assertEqual(outbox['packages'][0]['historical_reuse']['old_material_id'], MID)
        report = self.search()
        fireplay_reuse.preflight(CODE, {'search_sha256s': [report['search_sha256']],
                                       'fallback': {'kind': 'lookup_incomplete', 'reason': 'Fixture only queried YouTube'}},
                                 root=self.root)
        with patch.object(workflow, 'ROOT', self.root):
            first = fireplay.start(CODE, AUTHORITY, root=self.root)
            second = fireplay.start(CODE, AUTHORITY, root=self.root)
        self.assertEqual(first['videos'][0]['members'], [f'{CODE}-02'])
        self.assertEqual(first['budget'], second['budget'])
        self.assertEqual(read_json(self.root / 'state/budgets' / (first['budget'] + '.json'))['credit_limit'], 120)
        self.assertFalse((self.root / 'runs' / f'{CODE}-01').exists())
        self.accept_return(1, NEW_MATERIAL, [NEW_MATERIAL])
        self.assertFalse(fireplay.status(CODE, self.root)['completion_gate']['can_close'])
        fresh_video = self.root / 'work/fresh.mp4'
        fresh_video.write_bytes(b'Synthetic already reviewed Korean cut')
        fresh_digest = file_hash(fresh_video)
        source_digest = file_hash(self.original)
        quality = self.root / 'work/fresh-quality.json'
        write_json(quality, {'decision': 'pass', 'video_sha256': fresh_digest})
        folder = self.root / 'outputs/fixture-fresh'
        bundles.create(folder, 'delivery', fresh_digest, {'final.mp4': fresh_video,
                       'payload/outputs/quality.json': quality}, {
                           'status': 'delivered', 'technical_decision': 'pass',
                           'source_sha256': source_digest, 'target_language': 'ko', 'video_sha256': fresh_digest})
        self.prepare({'video_index': 1, 'locale': 'ko', 'package': folder.relative_to(self.root).as_posix()},
                     partial=True)
        self.accept_return(2, SECOND_MATERIAL, [NEW_MATERIAL, SECOND_MATERIAL])
        self.assertTrue(fireplay_submission.close_delivery(CODE, self.root)['complete'])

    @unittest.skipUnless(media.tools_available(), 'FFmpeg and ffprobe required for real media fixtures')
    def test_complete_reuse_skips_production_and_verifies_new_binding(self):
        self.fixture_media()
        self.register(['es'], dedicated=True)
        captured = self.capture()
        package = fireplay_reuse.package(CODE, self.fixture_review(captured), root=self.root)
        archived = library.find(file_hash(self.original), 'es', self.root)[0]
        self.assertEqual(archived['availability'], 'available')
        self.assertFalse(archived['production_eligible'])
        self.assertTrue((self.root / archived['presentation']).is_file())
        self.prepare(package)
        result = fireplay_reuse.preflight(CODE, {}, root=self.root)
        self.assertEqual(result['prepared_reuse_locales'], ['es'])
        status = fireplay.start(CODE, AUTHORITY, root=self.root)
        self.assertEqual(status['state'], 'reuse_ready')
        self.assertIsNone(status['budget'])
        self.assertFalse(status['completion_gate']['can_close'])
        self.accept_return(1, NEW_MATERIAL, [NEW_MATERIAL])
        self.assertTrue(fireplay_submission.close_delivery(CODE, self.root)['complete'])

    @unittest.skipUnless(media.tools_available(), 'FFmpeg and ffprobe required for real media fixtures')
    def test_english_original_of_a_translated_input_goes_through_review_and_return(self):
        self.fixture_media()
        self.register(['en'])
        upstream_id = 'uPStream001'
        upstream = f'https://youtu.be/{upstream_id}'
        report = self.search(relation='delivery', description=upstream, delivered_url=URL, tags=['zh-TW'])
        candidate = report['original_candidates'][0]
        self.assertEqual(report['candidates'], [])
        detail = {'material': {'id': SECOND_MATERIAL, 'type': 'video', 'status': 'available',
                               'access': {'canUse': True}, 'currentVideoResourceId': RESOURCE,
                               'currentVideoUrl': upstream, 'videoR2Url': R2_URL, 'tags': [{'name': 'US'}],
                               'resources': [{'id': RESOURCE, 'backupUrl': R2_URL, 'mimeType': 'video/mp4',
                                              'status': 'normal', 'storageStatus': 'r2',
                                              'url': upstream, 'youtubeVideoId': upstream_id,
                                              'fileSize': self.original.stat().st_size}]}}
        spec = {'search_sha256': report['search_sha256'], 'candidate_id': candidate['id'],
                'material_detail': detail}
        resource = detail['material']['resources'][0]
        resource['youtubeVideoId'] = upstream_id.upper()
        with self.assertRaisesRegex(WorkflowError, 'does not match the upstream YouTube ID'):
            fireplay_reuse.capture(CODE, spec, root=self.root)
        resource['youtubeVideoId'] = upstream_id
        with patch('video_localizer.kie.download',
                   side_effect=lambda url, path, **kwargs: shutil.copyfile(self.original, path)):
            captured = fireplay_reuse.capture(CODE, spec, root=self.root)
        review = {**self.fixture_review(captured), 'locale': 'en', 'target_language_observed': 'en',
                  'language_tag_resolution': 'Synthetic fixture for a reviewed original without an English delivery tag'}
        with self.assertRaisesRegex(WorkflowError, 'edges'):
            fireplay_reuse.package(CODE, {**review, 'head_tail_audio': {}}, root=self.root)
        record_path = fireplay._folder(CODE, self.root) / 'request.json'
        record = read_json(record_path)
        record['delivery_specifications'] = {'clear_audio': True}
        write_json(record_path, record)
        with self.assertRaisesRegex(WorkflowError, 'hash-bound passing audio review'):
            fireplay_reuse.package(CODE, review, root=self.root)
        package = fireplay_reuse.package(CODE, {**review, 'clear_audio_decision': 'pass'}, root=self.root)
        outbox = self.prepare(package)
        reuse = outbox['packages'][0]['historical_reuse']
        self.assertEqual(reuse['reuse_origin'], 'upstream_original')
        self.assertEqual(reuse['old_material_id'], SECOND_MATERIAL)
        self.assertEqual(fireplay.start(CODE, AUTHORITY, root=self.root)['state'], 'reuse_ready')
        self.accept_return(1, NEW_MATERIAL, [NEW_MATERIAL])
        self.assertTrue(fireplay_submission.close_delivery(CODE, self.root)['complete'])

    @unittest.skipUnless(media.tools_available(), 'FFmpeg and ffprobe required for real media fixtures')
    def test_permission_and_review_evidence_are_enforced(self):
        self.fixture_media()
        self.register()
        with self.assertRaisesRegex(WorkflowError, 'cannot use'):
            self.capture(allowed=False)
        captured = self.capture()
        incomplete = self.fixture_review(captured)
        incomplete['head_tail_audio'].pop('tail')
        with self.assertRaisesRegex(WorkflowError, 'both actual audio edges'):
            fireplay_reuse.package(CODE, incomplete, root=self.root)
        (self.root / captured['capture']).with_name('final.mp4').write_bytes(b'changed')
        with self.assertRaisesRegex(WorkflowError, 'capture, evidence or original scope changed'):
            fireplay_reuse.package(CODE, self.fixture_review(captured), root=self.root)
