import unittest
from video_localizer.common import WorkflowError
from video_localizer.fireplay_materials import verify_tags

class MaterialLanguageTagTests(unittest.TestCase):
    def test_actual_uppercase_tag_and_project_aliases(self):
        verify_tags(['ar','fruit'], {'AR','fruit'}, 'ar')
        verify_tags(['ja','fruit'], {'JP','fruit'}, 'ja')
        verify_tags(['zh-TW','fruit'], {'TW','fruit'}, 'zh-TW')

    def test_product_and_correct_language_still_required(self):
        for tags in [{'AR'}, {'FR','fruit'}, {'AR','Fruit'}]:
            with self.assertRaises(WorkflowError):
                verify_tags(['ar','fruit'], tags, 'ar')
