from pathlib import Path
import sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from video_localizer import workflow
from video_localizer.common import write_json,file_hash,read_json
from video_localizer.common import WorkflowError


class ReuseBudgetTests(unittest.TestCase):
    def test_character_voice_override_requires_source_binding_and_stays_bounded(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'work/test-tmp') as tmp:
            run=Path(tmp);(run/'inputs').mkdir()
            source=run/'inputs/source.mp4';source.write_bytes(b'fixture character source')
            digest=file_hash(source)
            write_json(run/'run.json',{'source':'inputs/source.mp4','source_sha256':digest})
            settings={'max_paid_jobs_per_run':2,'max_estimated_credits_per_run':60}
            def load(path):return dict(settings) if Path(path).name=='workspace.json' else read_json(path)
            with patch.object(workflow,'read_json',side_effect=load):
                self.assertEqual(workflow.execution_limits(run)['max_paid_jobs_per_run'],2)
                budget={'source_sha256':digest,'max_paid_jobs_per_run':30,
                        'max_estimated_credits_per_run':60,'reason':'Nine character voices, review and bounded repairs'}
                write_json(run/'inputs/budget.json',budget)
                self.assertEqual(workflow.execution_limits(run)['max_paid_jobs_per_run'],30)
                for change in ({'source_sha256':'wrong'},{'reason':''},{'max_paid_jobs_per_run':31}):
                    with self.subTest(change=change):
                        write_json(run/'inputs/budget.json',{**budget,**change})
                        with self.assertRaises(WorkflowError):workflow.execution_limits(run)

    def test_new_reuse_defaults_to_40_but_explicit_historical_budget_stays_bound(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'work/test-tmp') as tmp:
            run=Path(tmp);(run/'inputs').mkdir();source=run/'inputs/source.mp4';source.write_bytes(b'fixture source')
            write_json(run/'run.json',{'source':'inputs/source.mp4','source_sha256':file_hash(source)})
            write_json(run/'inputs/reuse-manifest.json',{'source_sha256':file_hash(source)})
            settings={'max_paid_jobs_per_run':2,'max_estimated_credits_per_run':60,'max_estimated_credits_per_reused_run':40}
            def load(path):return dict(settings) if Path(path).name=='workspace.json' else read_json(path)
            with patch.object(workflow,'read_json',side_effect=load):
                self.assertEqual(workflow.execution_limits(run)['max_estimated_credits_per_run'],40)
                write_json(run/'inputs/budget.json',{'source_sha256':file_hash(source),'max_paid_jobs_per_run':2,
                    'max_estimated_credits_per_run':60,'reason':'Frozen user-authorized historical run budget'})
                self.assertEqual(workflow.execution_limits(run)['max_estimated_credits_per_run'],60)


if __name__=='__main__':unittest.main()
