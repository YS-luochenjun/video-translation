"""Recovery and publication boundaries; all connector/model evidence is synthetic."""
from datetime import datetime, timedelta, timezone
import unittest
import json

import test_fireplay as fixtures
import test_fireplay_publication as publication_fixtures
from video_localizer import fireplay, fireplay_monitor as monitor, fireplay_publication as publication
from video_localizer import fireplay_submission as submission
from video_localizer.common import WorkflowError, file_hash, read_json, utc_now, write_json


class DeliveryClosureTests(unittest.TestCase):
    setUp = fixtures.FireplayTests.setUp
    register = fixtures.FireplayTests.register
    record = fixtures.FireplayTests.record
    save = fixtures.FireplayTests.save
    downloaded = fixtures.FireplayTests.downloaded
    returned_setup = fixtures.FireplayTests.returned_setup
    complete_output = publication_fixtures.PublicationTests.complete_output

    def best(self, assessment):
        assessment['best_available'] = {'stop_condition': 'retry_limit',
                                      'reason': 'Synthetic bounded repair reached its limit', 'evidence': ['final.mp4']}
        for defect in assessment['defects']:
            defect['publication_impact'] = 'ordinary'
        return assessment

    def test_ordinary_internal_major_and_many_defects_can_publish_when_bounded(self):
        spec, assessment = self.complete_output('major', many=True)
        self.best(assessment)
        for p in spec['packages']:
            self.assertEqual(publication.review(fixtures.CODE, {'package': p['package'], 'assessment': assessment},
                             self.root)['decision'], 'bounded_best_available_acceptable')
        box = fireplay.prepare_return(fixtures.CODE, spec, self.root)
        self.assertTrue(all(p['publication_acceptance']['mode'] == 'bounded_best_available_publication' for p in box['packages']))
        self.assertFalse(fireplay.status(fixtures.CODE, self.root)['whole_requirement_complete'])

    def test_tearing_is_blocked_even_if_labeled_ordinary_and_best(self):
        spec, assessment = self.complete_output()
        self.best(assessment)
        assessment['defects'][0]['kind'] = 'large_area_tearing'
        r = publication.review(fixtures.CODE, {'package': spec['packages'][0]['package'], 'assessment': assessment}, self.root)
        self.assertEqual(r['decision'], 'blocked_major_or_incomplete')

    def test_legacy_minor_review_remains_idempotent_under_new_policy(self):
        spec, assessment = self.complete_output()
        item = spec['packages'][0]
        r = publication.review(fixtures.CODE, {'package': item['package'], 'assessment': assessment}, self.root)
        p = self.root / 'state/fireplay' / fixtures.CODE / 'publication-reviews' / (r['video_sha256'] + '.json')
        old = read_json(p)
        old.pop('policy_authorization_ref')
        write_json(p, old)
        digest = file_hash(p)
        self.assertEqual(publication.review(fixtures.CODE, {'package': item['package'], 'assessment': assessment}, self.root), old)
        self.assertEqual(file_hash(p), digest)

    def test_one_locale_success_does_not_waive_other_locale_missing_audio(self):
        spec, assessment = self.complete_output('major')
        self.best(assessment)
        publication.review(fixtures.CODE, {'package': spec['packages'][0]['package'], 'assessment': assessment}, self.root)
        assessment['required_audio_complete'] = False
        self.assertEqual(publication.review(fixtures.CODE, {'package': spec['packages'][1]['package'], 'assessment': assessment},
                         self.root)['decision'], 'blocked_major_or_incomplete')

    def test_reassessment_preserves_rejected_review_and_does_not_need_new_paid_video(self):
        spec, assessment = self.complete_output('major', many=True)
        p = spec['packages'][0]
        first = publication.review(fixtures.CODE, {'package': p['package'], 'assessment': assessment}, self.root)
        original = self.root / 'state/fireplay' / fixtures.CODE / 'publication-reviews' / (first['video_sha256'] + '.json')
        digest = file_hash(original)
        self.best(assessment)
        r = publication.review(fixtures.CODE, {'package': p['package'], 'assessment': assessment,
                               'reassess_under_current_policy': True}, self.root)
        self.assertEqual(file_hash(original), digest)
        self.assertEqual(r['prior_review']['sha256'], digest)
        self.assertEqual(publication.publication_decision(fixtures.CODE, first['video_sha256'], self.root),
                         'bounded_best_available_acceptable')

    def owner(self):
        self.downloaded()
        fireplay.chat(fixtures.CODE, {'title': fixtures.CODE, 'threadId': fixtures.THREAD}, root=self.root)
        r = self.record()
        r['videos'][0]['members'] = ['fixture-es', 'fixture-ko']
        self.save(r)
        write_json(self.root / 'outputs/index.json', {'entries': [{'origin_run_id': 'fixture-es',
                   'target_language': 'es', 'source_sha256': r['videos'][0]['source']['sha256'],
                   'status': 'delivered', 'video_sha256': 'b' * 64}]})
        return monitor.followups(self.root)[0]

    def expired_signal(self):
        task = self.owner()
        monitor.signal({'key': task['key']}, self.root)
        monitor.signal({'key': task['key'], 'response': {'threadId': fixtures.THREAD}}, self.root)
        p = self.root / 'state/fireplay/monitor/signals' / (task['key'] + '.json')
        d = read_json(p)
        d['receipt_at'] = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        write_json(p, d)
        return task, p

    def observation(self, status='idle'):
        p = self.root / 'work/owner-status.json'
        write_json(p, {'threadId': fixtures.THREAD, 'status': status, 'synthetic_fixture': True})
        return {'threadId': fixtures.THREAD, 'status': status, 'observed_at': utc_now(), 'source': 'wait_threads',
                'evidence': {'path': str(p.relative_to(self.root)), 'sha256': file_hash(p)}}

    def test_ready_locale_is_dispatched_before_missing_locale_is_produced(self):
        t = self.owner()
        self.assertEqual(t['action'], 'auto_return')
        self.assertEqual(t['ready_locales'], ['es'])
        self.assertEqual(t['production_locales'], ['ko'])

    def test_standing_submission_consent_reaches_chat_status_and_recovery(self):
        self.register()
        consent = read_json(self.root / 'config/fireplay-publication.json')['submission_consent']
        chat = fireplay.chat(fixtures.CODE, root=self.root)
        instruction = fireplay.status(fixtures.CODE, self.root)['submission_consent_instruction']
        self.assertIn(consent['authorization_ref'], instruction)
        self.assertIn(consent['source_quote'], instruction)
        self.assertIn('共享到对应需求组', instruction)
        self.assertIn('不通过换接口或工具绕过', instruction)
        self.assertIn(instruction, chat['prompt'])
        task = self.owner()
        signal = monitor.signal({'key': task['key']}, self.root)
        self.assertIn(instruction, signal['host_action']['arguments']['prompt'])
        self.assertEqual(signal['state'], 'unknown')
        self.assertFalse(fireplay.status(fixtures.CODE, self.root)['whole_requirement_complete'])

    def test_submission_consent_does_not_invent_human_authority(self):
        path = self.root / 'config/fireplay-publication.json'
        config = read_json(path)
        config['submission_consent']['authority'] = 'agent'
        write_json(path, config)
        self.downloaded()
        self.assertEqual(fireplay.submission_consent_instruction(self.root), '')
        self.assertNotIn(config['submission_consent']['authorization_ref'],
                         fireplay.chat(fixtures.CODE, root=self.root)['prompt'])

    def test_expired_sent_task_needs_fresh_idle_observation_before_redispatch(self):
        t, p = self.expired_signal()
        self.assertEqual(monitor.followups(self.root)[0]['signal_state'], 'owner_check_required')
        monitor.signal({'key': t['key'], 'response': {'threadId': fixtures.THREAD}}, self.root)
        self.assertEqual(monitor.followups(self.root)[0]['signal_state'], 'owner_check_required')
        self.assertEqual(monitor.signal({'key': t['key']}, self.root)['state'], 'sent')
        r = monitor.signal({'key': t['key'], 'owner_observation': self.observation()}, self.root)
        self.assertEqual((r['state'], r['attempt']), ('unknown', 2))
        self.assertTrue((self.root / r['previous_dispatch']).is_file())
        self.assertEqual(monitor.signal({'key': t['key']}, self.root), r)
        with self.assertRaisesRegex(WorkflowError, 'matching delivery follow-up attempt'):
            monitor.signal({'key': t['key'], 'response': {'threadId': fixtures.THREAD}}, self.root)
        self.assertEqual(monitor.signal({'key': t['key'], 'attempt': 2,
                         'response': {'threadId': fixtures.THREAD}}, self.root)['state'], 'sent')

    def test_active_owner_is_not_interrupted_or_redispatched(self):
        t, p = self.expired_signal()
        r = monitor.signal({'key': t['key'], 'owner_observation': self.observation('running')}, self.root)
        self.assertEqual(r['state'], 'sent')
        self.assertEqual(monitor.followups(self.root)[0]['signal_state'], 'sent')

    def test_unknown_send_cannot_be_retried_on_idle_observation(self):
        t = self.owner()
        monitor.signal({'key': t['key']}, self.root)
        with self.assertRaisesRegex(WorkflowError, 'unknown send'):
            monitor.signal({'key': t['key'], 'owner_observation': self.observation()}, self.root)

    def test_repeat_stalls_escalate_instead_of_infinite_prompts(self):
        t, p = self.expired_signal()
        d = read_json(p)
        d['attempt'] = 3
        write_json(p, d)
        self.assertEqual(monitor.followups(self.root)[0]['signal_state'], 'escalation_required')
        r = monitor.signal({'key': t['key'], 'owner_observation': self.observation()}, self.root)
        self.assertEqual(r['attempt'], 3)

    def test_designer_ids_resolved_from_platform_without_extra_human_id_approval(self):
        spec = self.returned_setup()
        (self.root / 'state/fireplay' / fixtures.CODE / 'return-1.json').unlink()
        spec.pop('attribution')
        spec['designer_receipt'] = {'member_directory': {'members': [
            {'feishuUserId': 'test', 'username': 'Synthetic Designer'}], 'query_meta': {'observed_at': utc_now()}}}
        spec['designer_receipt'] = {'content': [{'type': 'text', 'text': json.dumps(spec['designer_receipt'])}]}
        box = fireplay.prepare_return(fixtures.CODE, spec, self.root)
        self.assertEqual(box['attribution']['designer_ids'], ['test'])
        self.assertEqual(box['attribution']['creation_type'], 'derivative')
        self.assertIn('二创', box['packages'][0]['tags'])

    def test_partial_directory_does_not_silently_remove_the_designer(self):
        spec = self.returned_setup()
        (self.root / 'state/fireplay' / fixtures.CODE / 'return-1.json').unlink()
        spec['designer_receipt'] = {'member_directory': {'members': [], 'query_meta': {'observed_at': utc_now()}}}
        with self.assertRaisesRegex(WorkflowError, 'partial/empty directory'):
            fireplay.prepare_return(fixtures.CODE, spec, self.root)

    def test_whole_requirement_close_requires_full_platform_receipt(self):
        self.owner()
        with self.assertRaisesRegex(WorkflowError, 'Whole requirement is incomplete'):
            submission.close_delivery(fixtures.CODE, self.root)
        r = self.record()
        folder = self.root / 'state/fireplay' / fixtures.CODE
        rows = [{'locale': locale, 'material_id': mid, 'sha256': digest * 64}
                for locale, mid, digest in [('es', fixtures.MID, 'b'), ('ko', fixtures.RESOURCE, 'c')]]
        write_json(folder / 'user-approved-return-1.json', {'requirement_id': fixtures.RID,
                   'state': 'returned_user_approved', 'items': rows})
        t = monitor.followups(self.root)[0]
        self.assertEqual(t['action'], 'verify_completion')
        submission.verify_completion(fixtures.CODE, {'serverTime': utc_now(), 'items': [{'id': fixtures.RID,
                   'materials': [{'id': r['material_id']} for r in rows]}]}, self.root)
        self.assertTrue(submission.close_delivery(fixtures.CODE, self.root)['complete'])
        self.assertEqual(monitor.followups(self.root), [])


if __name__ == '__main__':
    unittest.main()
