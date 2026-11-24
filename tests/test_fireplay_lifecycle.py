import copy
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

import test_fireplay
from test_fireplay import CODE, MID, RESOURCE, RID, THREAD
from video_localizer import fireplay, fireplay_parallel, fireplay_submission, workflow
from video_localizer.fireplay_status_transition import transition
from video_localizer.common import WorkflowError, file_hash, utc_now, write_json


class FireplayLifecycleTests(unittest.TestCase):
    setUp = test_fireplay.FireplayTests.setUp
    register = test_fireplay.FireplayTests.register
    record = test_fireplay.FireplayTests.record
    save = test_fireplay.FireplayTests.save

    def setup_sources(self, count=2):
        self.snap['summary']['items'][0]['aiMode'] = 'video_translate'
        brief = self.snap['brief']['items'][0]
        for number in range(1, count):
            brief['description'] += f'\nhttps://example.com/video-{number}.mp4'
        brief['quantity'] = count * 2
        self.register()
        record = self.record()
        for video in record['videos']:
            path = self.root / f"source-{video['index']}.mp4"
            path.write_bytes(path.name.encode())
            video['source'] = {'path': path.name, 'sha256': file_hash(path)}
        self.save(record)

    def snapshot(self, state):
        result = copy.deepcopy(self.snap)
        timestamp = datetime.now(timezone.utc).isoformat()
        result['summary']['serverTime'] = timestamp
        result['summary']['items'][0].update(status=state, updatedAt=timestamp)
        result['brief']['items'][0]['updatedAt'] = timestamp
        return result

    def start_platform(self, index):
        reservation = fireplay.chat(CODE, index=index, dispatch=True, root=self.root)
        self.assertEqual(reservation['state'], 'needs_status_start')
        self.assertNotIn('host_actions', reservation)
        pending = self.snapshot('not_started')
        write = transition(CODE, 'start', pending, True, self.root)
        self.assertEqual(write['host_action']['arguments']['items'], [{
            'requirement_id': RID, 'status': 'in_progress',
            'base_updated_at': pending['summary']['items'][0]['updatedAt']}])
        self.assertNotIn('host_action', transition(CODE, 'start', pending, True, self.root))
        started = self.snapshot('in_progress')
        self.assertEqual(transition(CODE, 'start', started, root=self.root)['state'], 'confirmed')
        return started

    def test_per_source_chats_and_shared_budget_when_second_starts_first(self):
        self.setup_sources()
        self.start_platform(2)
        for index, thread_id in ((2, THREAD), (1, MID)):
            packet = fireplay.chat(CODE, index=index, dispatch=True, root=self.root)
            self.assertEqual(packet['state'], 'prepared')
            self.assertEqual(packet['title'], f'{CODE}-{index}')
            self.assertIn(f'只处理原片 {index}', packet['prompt'])
            self.assertEqual(fireplay.chat(CODE, index=index, dispatch=True, root=self.root)['state'], 'unknown')
            fireplay.chat(CODE, {'threadId': thread_id, 'title': packet['title']}, index, root=self.root)
        self.assertEqual(self.record()['chat']['threadId'], THREAD)
        authority = {'authority': 'user', 'authorization_ref': 'test:split', 'user_request': 'Translate both', 'mode': 'first'}
        with patch.object(workflow, 'ROOT', self.root), patch('video_localizer.media.probe',
                   return_value={'duration': 16, 'width': 1080, 'height': 1920}):
            second = fireplay.start(CODE, authority, 2, self.root)
            first = fireplay.start(CODE, authority, 1, self.root)
        self.assertEqual(first['budget'], second['budget'])
        self.assertEqual(first['videos'][0]['chat']['threadId'], MID)
        self.assertEqual(first['videos'][1]['chat']['threadId'], THREAD)

    def test_eleventh_source_waits_and_uses_released_slot(self):
        self.setup_sources(11)
        self.start_platform(1)
        for index in range(1, 11):
            self.assertEqual(fireplay.chat(CODE, index=index, dispatch=True, root=self.root)['state'], 'prepared')
        queued = fireplay.chat(CODE, index=11, dispatch=True, root=self.root)
        self.assertEqual(queued['state'], 'queued')
        self.assertEqual(queued['active_source_count'], 10)
        self.assertNotIn('chat', self.record()['videos'][10])
        self.bind_source(1, MID, RESOURCE)
        self.assertEqual(fireplay_parallel.capacity(self.root)['available_source_slots'], 1)
        self.assertEqual(fireplay.chat(CODE, index=11, dispatch=True, root=self.root)['state'], 'prepared')

    def bind_source(self, index, *material_ids):
        rows = [{'locale': locale, 'material_id': material_id, 'sha256': 'a' * 64}
                for locale, material_id in zip(('es', 'ko'), material_ids)]
        write_json(self.root / f'state/fireplay/{CODE}/user-approved-return-{index}.json',
                   {'requirement_id': RID, 'state': 'returned_user_approved', 'items': rows})

    def test_full_current_bindings_required_before_done_and_readback_before_close(self):
        self.setup_sources(1)
        started = self.start_platform(1)
        with self.assertRaisesRegex(WorkflowError, 'every video and locale'):
            transition(CODE, 'finish', started, True, self.root)
        self.bind_source(1, MID, RESOURCE)
        row_updated_at = started['summary']['items'][0]['updatedAt']
        verification = {'serverTime': utc_now(), 'items': [{'id': RID, 'updatedAt': row_updated_at,
                        'materials': [{'id': MID}, {'id': RESOURCE}]}]}
        self.assertTrue(fireplay_submission.verify_completion(CODE, verification, self.root)['complete'])
        with self.assertRaisesRegex(WorkflowError, 'Confirm the Fireplay done'):
            fireplay_submission.close_delivery(CODE, self.root)
        with self.assertRaisesRegex(WorkflowError, 'Refresh the full delivery check'):
            transition(CODE, 'finish', self.snapshot('in_progress'), True, self.root)
        self.assertEqual(transition(CODE, 'finish', self.snapshot('pending_upload'), True, self.root)['state'], 'manual_review')
        finish = transition(CODE, 'finish', started, True, self.root)
        self.assertEqual(finish['host_action']['arguments']['items'][0]['status'], 'done')
        self.assertFalse(fireplay.status(CODE, self.root)['whole_requirement_complete'])
        done = transition(CODE, 'finish', self.snapshot('done'), root=self.root)
        self.assertEqual(done['state'], 'confirmed')
        self.assertTrue(fireplay_submission.close_delivery(CODE, self.root)['complete'])

    def test_start_preserves_other_status_and_requires_permission(self):
        self.setup_sources(1)
        fireplay.chat(CODE, dispatch=True, root=self.root)
        self.assertEqual(transition(CODE, 'start', self.snapshot('pending_upload'), True, self.root)['state'], 'manual_review')
        pending = self.snapshot('not_started')
        pending['summary']['items'][0]['canUpdateStatus'] = False
        self.assertEqual(transition(CODE, 'start', pending, True, self.root)['state'], 'needs_status_permission')
        with self.assertRaisesRegex(WorkflowError, 'started elsewhere'):
            transition(CODE, 'start', self.snapshot('in_progress'), root=self.root)
        self.assertEqual(fireplay.chat(CODE, root=self.root, release_reservation=True)['state'], 'reservation_released')
        self.assertEqual(fireplay_parallel.capacity(self.root)['active_source_count'], 0)

    def test_timeout_allows_only_one_retry_after_fresh_platform_read(self):
        self.setup_sources(1)
        fireplay.chat(CODE, dispatch=True, root=self.root)
        first = self.snapshot('not_started')
        self.assertEqual(transition(CODE, 'start', first, True, self.root)['attempt'], 1)
        with self.assertRaisesRegex(WorkflowError, 'newer platform read'):
            transition(CODE, 'start', first, True, self.root, retry=True)
        later = self.snapshot('not_started')
        self.assertEqual(transition(CODE, 'start', later, True, self.root, retry=True)['attempt'], 2)
        with self.assertRaisesRegex(WorkflowError, 'unresolved first attempt'):
            transition(CODE, 'start', self.snapshot('not_started'), True, self.root, retry=True)
