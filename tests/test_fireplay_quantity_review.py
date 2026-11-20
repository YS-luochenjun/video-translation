import unittest
import test_fireplay as fixtures
from video_localizer import fireplay
from video_localizer.common import WorkflowError, read_json, write_json


class QuantityReviewTests(unittest.TestCase):
    setUp = fixtures.FireplayTests.setUp
    register = fixtures.FireplayTests.register
    record = fixtures.FireplayTests.record
    save = fixtures.FireplayTests.save

    def funded(self):
        self.register({'authorization_ref': 'human-original', 'source_quote': 'One per locale',
                       'quantity_mode': 'one_per_locale'})
        old = self.record()
        old['budget'] = 'original-pool'
        old['videos'][0]['members'] = ['existing-run']
        self.save(old)
        return old

    def decision(self, old):
        return {'authorization_ref': 'human-current', 'source_quote': 'Upload these existing versions',
                'quantity_mode': 'one_per_locale', 'review_quantity_only': True,
                'reviewed_content_version': old['content_version'], 'revision_reason': 'Correct count to existing scope',
                'continue_pending_delivery': True, 'continue_unsubmitted_outputs': True,
                'continuation_content_version': fireplay.snapshot(fixtures.CODE, self.snap)['content_version']}

    def test_quantity_only_done_continuation_preserves_funded_production(self):
        # Existing interpretation may differ from the raw original quantity.
        self.snap['brief']['items'][0]['quantity'] = 1
        self.snap['summary']['items'][0]['quantity'] = 1
        old = self.funded()
        for view in ('brief', 'summary'):
            self.snap[view]['items'][0]['quantity'] = 2
        self.snap['summary']['items'][0]['status'] = 'done'
        self.register(self.decision(old))
        current = self.record()
        self.assertEqual(current['budget'], old['budget'])
        self.assertEqual(current['videos'], old['videos'])
        self.assertEqual(read_json(self.root / current['revision_history'][0]['path']), old)
        self.assertFalse(current['blockers'])
        self.register(self.decision(old))
        self.assertEqual(len(self.record()['revision_history']), 1)
        box = self.root / 'state/fireplay' / fixtures.CODE / 'return-1.json'
        write_json(box, {'state': 'ready', 'pending_locales': [], 'packages': [{'locale': 'es'}]})
        self.register(self.decision(old))
        self.assertEqual(read_json(box)['state'], 'ready')

    def test_quantity_review_rejects_source_change(self):
        old = self.funded()
        self.snap['brief']['items'][0]['description'] += ' changed text'
        with self.assertRaisesRegex(WorkflowError, 'Quantity-only review'):
            self.register(self.decision(old))
        self.assertEqual(self.record(), old)

    def test_settled_partial_return_follows_quantity_correction_without_replaying(self):
        from video_localizer.fireplay_revision import reconcile_quantity_return
        old = self.funded()
        box_path = self.root / 'state/fireplay' / fixtures.CODE / 'return-1.json'
        box = {'requirement_id': old['requirement_id'], 'content_version': old['content_version'],
               'state': 'returned', 'pending_locales': ['es'], 'packages': [],
               'operations': {'bind': {'state': 'verified', 'receipt': 'original-receipt'}}}
        write_json(box_path, box)
        for view in ('brief', 'summary'):
            self.snap[view]['items'][0]['quantity'] = 1
        self.register(self.decision(old))
        result = reconcile_quantity_return(self.record(), box, box_path, self.root)
        self.assertEqual(result['content_version'], self.record()['content_version'])
        self.assertEqual(result['operations'], box['operations'])
        self.assertEqual(read_json(self.root / result['content_revision_history'][0]['path'])['content_version'], old['content_version'])
        self.assertEqual(len(reconcile_quantity_return(self.record(), result, box_path, self.root)['content_revision_history']), 1)

    def test_unsettled_return_cannot_follow_quantity_correction(self):
        from video_localizer.fireplay_revision import reconcile_quantity_return
        old = self.funded()
        box_path = self.root / 'state/fireplay' / fixtures.CODE / 'return-1.json'
        box = {'requirement_id': old['requirement_id'], 'content_version': old['content_version'],
               'state': 'ready', 'packages': [], 'operations': {'upload-1': {'state': 'unknown'}}}
        write_json(box_path, box)
        for view in ('brief', 'summary'):
            self.snap[view]['items'][0]['quantity'] = 1
        self.register(self.decision(old))
        with self.assertRaisesRegex(WorkflowError, 'Only settled'):
            reconcile_quantity_return(self.record(), box, box_path, self.root)
        self.assertEqual(read_json(box_path), box)

    def test_quantity_review_accepts_one_per_locale_without_reducing_funded_scope(self):
        old = self.funded()
        for view in ('brief', 'summary'):
            self.snap[view]['items'][0]['quantity'] = 1
        updated = self.register(self.decision(old))
        self.assertFalse(updated['blockers'])
        current = self.record()
        self.assertEqual(current['budget'], old['budget'])
        self.assertEqual(current['videos'], old['videos'])
        self.assertEqual(current['targets'], old['targets'])
        self.assertEqual(read_json(self.root / current['revision_history'][0]['path']), old)

    def test_quantity_review_accepts_locale_count_for_multiple_sources(self):
        self.snap['brief']['items'][0]['description'] = '\n'.join([
            'https://www.youtube.com/shorts/Z6AJoQe5wI0',
            'https://www.youtube.com/shorts/6JWkgSsaJZY',
            'https://www.youtube.com/shorts/-tn3mOEPLqY',
            'https://www.youtube.com/shorts/CqrfXm50Bmo',
            'https://www.youtube.com/shorts/Al_6wXXMxac',
        ])
        for view in ('brief', 'summary'):
            self.snap[view]['items'][0]['quantity'] = 1
        old = self.funded()
        for view in ('brief', 'summary'):
            self.snap[view]['items'][0]['quantity'] = 2
        updated = self.register(self.decision(old))
        self.assertFalse(updated['blockers'])
        current = self.record()
        self.assertNotEqual(current['content_version'], old['content_version'])
        self.assertEqual(current['budget'], old['budget'])
        self.assertEqual(current['videos'], old['videos'])
        self.assertEqual(read_json(self.root / current['revision_history'][0]['path']), old)

    def test_quantity_review_accepts_source_count_without_reducing_delivery(self):
        self.snap['brief']['items'][0]['description'] = '\n'.join([
            'https://www.youtube.com/shorts/Z6AJoQe5wI0',
            'https://www.youtube.com/shorts/6JWkgSsaJZY',
            'https://www.youtube.com/shorts/-tn3mOEPLqY',
            'https://www.youtube.com/shorts/CqrfXm50Bmo',
            'https://www.youtube.com/shorts/Al_6wXXMxac',
        ])
        for view in ('brief', 'summary'):
            self.snap[view]['items'][0]['quantity'] = 2
        old = self.funded()
        for view in ('brief', 'summary'):
            self.snap[view]['items'][0]['quantity'] = 5
        updated = self.register(self.decision(old))
        self.assertFalse(updated['blockers'])
        current = self.record()
        self.assertEqual(current['budget'], old['budget'])
        self.assertEqual(current['videos'], old['videos'])
        self.assertEqual(current['targets'], old['targets'])
        self.assertEqual(read_json(self.root / current['revision_history'][0]['path']), old)

    def test_quantity_review_rejects_unrelated_count_for_multiple_sources(self):
        self.snap['brief']['items'][0]['description'] += '\nhttps://www.youtube.com/shorts/6JWkgSsaJZY'
        for view in ('brief', 'summary'):
            self.snap[view]['items'][0]['quantity'] = 1
        old = self.funded()
        for view in ('brief', 'summary'):
            self.snap[view]['items'][0]['quantity'] = 3
        with self.assertRaisesRegex(WorkflowError, 'Quantity-only review'):
            self.register(self.decision(old))
        self.assertEqual(self.record(), old)


if __name__ == '__main__':
    unittest.main()
