import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from video_localizer import model_tasks, workflow
from video_localizer.common import WorkflowError, object_hash, read_json, write_json


class AudioTaskRetryTests(unittest.TestCase):
    def test_two_zero_cost_rounds_are_idempotent_and_do_not_retry_ambiguous_or_paid_failures(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'work/test-tmp') as tmp:
            run=Path(tmp)/'runs/fixture';run.mkdir(parents=True)
            packet={'source_sha256':'source','purpose':'fixed character','estimated_credits':1,
                    'payload':{'model':'google/gemini-2-5-pro-tts','input':{}}}
            first=object_hash(packet)
            write_json(run/'jobs'/f'{first}.json',{'id':first,'state':'fail','task_id':'original','credits_consumed':0})
            client=Mock();client.credits.return_value=100;client.create.side_effect=['retry1','retry2']
            limits={'max_paid_jobs_per_run':30,'max_estimated_credits_per_run':60,'max_revision_rounds':2}
            with patch.object(model_tasks,'packet',return_value=packet), \
                 patch.object(workflow,'execution_limits',return_value=limits), \
                 patch('video_localizer.batches.reserve',return_value={}):
                one=model_tasks.submit(run,'inputs/tts.json',client,retry_failed=True)
                repeated=model_tasks.submit(run,'inputs/tts.json',client,retry_failed=True)
                self.assertEqual(one['job'],repeated['job']);self.assertEqual(client.create.call_count,1)
                path=run/'jobs'/f"{one['job']}.json";job=read_json(path)
                job.update(state='ambiguous',credits_consumed=None);write_json(path,job)
                self.assertTrue(model_tasks.submit(run,'inputs/tts.json',client,retry_failed=True)['reused'])
                self.assertEqual(client.create.call_count,1)
                job.update(state='fail',credits_consumed=1);write_json(path,job)
                with self.assertRaisesRegex(WorkflowError,'zero-cost'):
                    model_tasks.submit(run,'inputs/tts.json',client,retry_failed=True)
                job['credits_consumed']=0;write_json(path,job)
                two=model_tasks.submit(run,'inputs/tts.json',client,retry_failed=True)
                self.assertEqual(client.create.call_count,2)
                path=run/'jobs'/f"{two['job']}.json";job=read_json(path)
                self.assertEqual(job['retry_of'],one['job']);self.assertEqual(job['retry_attempt'],2)
                job.update(state='fail',credits_consumed=0);write_json(path,job)
                with self.assertRaisesRegex(WorkflowError,'retry limit'):
                    model_tasks.submit(run,'inputs/tts.json',client,retry_failed=True)
                self.assertEqual(client.create.call_count,2)
