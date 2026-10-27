from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from video_localizer import budgets, workflow, media
from video_localizer.common import ROOT, WorkflowError, file_hash, read_json, write_json


class DurationBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / 'work/test-tmp')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'config').mkdir()
        write_json(self.root / 'config/budget-policy.json', {
            'mode': 'source_duration', 'max_credits_per_source_second': 3})
        write_json(self.root / 'config/workspace.json', {
            'request_budget_policy': 'source_duration', 'max_paid_jobs_per_run': 2,
            'max_segment_seconds': 8, 'default_workflow':'video-localization',
            'default_profile':'fixture', 'require_target_audio_for_speech':True})
        write_json(self.root / 'config/profiles/fixture/profile.json', {})
        self.source = self.root / 'source.mp4'
        self.source.write_bytes(b'original fixture')
        self.spec = {'authority':'user', 'authorization_ref':'human:test-event', 'user_request':'Six languages',
                     'mode':'first', 'source':str(self.source), 'duration':99999}

    def open(self, seconds=75):
        with patch.object(media, 'probe', return_value={'duration':seconds}):
            return budgets.open_request(self.spec, self.root)

    def make_run(self, name, data=None):
        run = self.root / 'runs' / name
        run.mkdir(parents=True)
        source = run / 'source.mp4'
        source.write_bytes(self.source.read_bytes() if data is None else data)
        write_json(run / 'run.json', {'source':'source.mp4', 'source_sha256':file_hash(source)})
        return run

    def test_measured_duration_and_floor_no_minimum_or_locale_multiplier(self):
        for seconds, limit in [(10,30), (60,180), (75,225), (1.23456,3.703)]:
            with self.subTest(seconds=seconds), patch.object(media,'probe',return_value={'duration':seconds}) as probe:
                quote = budgets.duration_allowance(self.source,self.root)
                self.assertEqual(quote['credit_limit'],limit)
                probe.assert_called_once_with(self.source)
        self.assertEqual(self.open()['credit_limit'],225)

    def test_bad_duration_does_not_register_a_budget(self):
        for duration in (0, -2, float('nan'), float('inf')):
            with self.subTest(duration=duration), self.assertRaises(WorkflowError):
                self.open(duration)
        self.assertFalse((self.root/'state/budgets/index.json').exists())

    def test_roles_locales_and_derived_clip_share_original_balance(self):
        record = self.open()
        first = self.make_run('es')
        child = self.make_run('jp-short', b'clip')
        budgets.bind(first)
        budgets.bind(child,first)
        # The child's own duration is deliberately never probed for a fresh allowance.
        with patch.object(media,'probe',side_effect=AssertionError('must inherit')):
            self.assertEqual(budgets.run_allowance(child)['budget_basis']['source_duration_seconds'],75)
        with budgets.operation():
            budgets.reserve(first,'a'*64,224)
        with budgets.operation():
            with self.assertRaisesRegex(WorkflowError,'Whole-request'):
                budgets.reserve(child,'b'*64,2)
        self.assertEqual(budgets.status(record['id'],self.root)['remaining_credits'],1)

    def test_existing_ledger_does_not_reprice_or_clear_unknown_cost(self):
        (self.root/'config/budget-policy.json').unlink()
        old = budgets.open_request(self.spec,self.root)
        run = self.make_run('legacy')
        with budgets.operation():
            budgets.reserve(run,'c'*64,12)
        shutil.copyfile(ROOT/'config/budget-policy.json',self.root/'config/budget-policy.json')
        with patch.object(media,'probe',side_effect=AssertionError('must not reprice')):
            again = budgets.open_request(self.spec,self.root)
        self.assertEqual(again['credit_limit'],60)
        self.assertEqual(budgets.run_allowance(run)['credit_limit'],60)
        self.assertEqual(budgets.status(old['id'],self.root)['remaining_credits'],48)

    def test_probe_failure_leaves_settled_reuse_request_open(self):
        old = self.open()
        self.spec.update(mode='reuse',authorization_ref='human:new',reuse_of=old['id'],reuse_confirmation='new_user_request')
        with patch.object(media,'probe',side_effect=WorkflowError('invalid input')):
            with self.assertRaisesRegex(WorkflowError,'invalid input'):
                budgets.open_request(self.spec,self.root)
        self.assertEqual(budgets.for_source(file_hash(self.source),self.root)['state'],'open')

    def test_long_video_limits_and_role_jobs_are_finite_and_clamped_to_ledger(self):
        record = self.open(600)
        run = self.make_run('long')
        budgets.bind(run)
        write_json(run/'analysis/inventory.json',{'speech_segments':[{'character_id':f'role{i}'} for i in range(90)]})
        with patch.object(workflow,'ROOT',self.root):
            limits = workflow.execution_limits(run)
            self.assertEqual(limits['max_estimated_credits_per_run'],1800)
            self.assertEqual(limits['max_paid_jobs_per_run'],272)
            write_json(run/'inputs/budget.json',{'source_sha256':file_hash(self.source),'reason':'bounded planning override',
                'max_paid_jobs_per_run':270,'max_estimated_credits_per_run':9999})
            self.assertEqual(workflow.execution_limits(run)['max_estimated_credits_per_run'],record['credit_limit'])

    def test_long_intake_keeps_required_audio_and_extract_has_no_demo_duration_cap(self):
        with patch.object(workflow,'ROOT',self.root), patch.object(media,'probe',return_value={'duration':600}):
            workflow.create_run(self.source,'es','fixture long input','intake')
        request = read_json(self.root/'runs/intake/inputs/request.json')
        self.assertTrue(request['require_target_audio'])
        meta = {'duration':181,'has_audio':False}
        # Empty sampled navigation is sufficient to test extraction dispatch, not visual coverage.
        with patch.object(media,'probe',return_value=meta), patch.object(media,'ffmpeg'), \
                patch.object(media,'scene_points',return_value=[0,181]):
            _,shots = media.extract(self.source,self.root/'extract',max_clip=8)
        self.assertEqual(shots[-1]['end'],181)
        self.assertTrue(all(shot['end']-shot['start']<=8 for shot in shots))
