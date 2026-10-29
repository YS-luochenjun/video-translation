import copy
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


if __name__ == '__main__':
    unittest.main()
