import copy
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_localizer import bundles, improvement, knowledge_review, media, review_probes, visual_audit
from video_localizer.common import WorkflowError, file_hash, read_json, write_json

PROJECT = Path(__file__).resolve().parents[1]


class ImprovementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=PROJECT / 'work/test-tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / 'runs/fixture'
        write_json(self.root / 'config/workspace.json', {'max_revision_rounds': 2})
        self.run.mkdir(parents=True)
        (self.run / 'source.mp4').write_bytes(b'explicit synthetic source; not media proof')
        self.sha = file_hash(self.run / 'source.mp4')
        write_json(self.run / 'run.json', {'source': 'source.mp4', 'source_sha256': self.sha})
        write_json(self.run / 'inputs/request.json', {'target_language': 'es'})
        write_json(self.run / 'analysis/inventory.json', {'source_sha256': self.sha,
            'text_instances': [{'id': 't1', 'action': 'translate'}], 'audio': {'has_speech': True}})
        (self.run / 'outputs').mkdir()
        (self.run / 'outputs/before.mp4').write_bytes(b'fixture old version')
        (self.run / 'outputs/after.mp4').write_bytes(b'fixture new version')
        self.asset = lambda name: {'path': name, 'sha256': file_hash(self.run / name)}
        write_json(self.run / 'outputs/candidate.json', {**self.asset('outputs/after.mp4'), 'plan_id': 'p1'})
        self.spec = {'source_sha256': self.sha, 'reviewed_by': 'fixture-only', 'review_type': 'same_agent',
            'symptom': 'Synthetic title lost slant', 'hypothesis': 'Font face mismatch', 'cause_status': 'hypothesis',
            'missed_reason': 'Compared text content without original lettering',
            'next_review_question': 'Compare actual slant and stroke on the whole scene',
            'intervention': 'Changed one font face', 'before': self.asset('outputs/before.mp4'),
            'after': self.asset('outputs/after.mp4'), 'evidence': [], 'outcome': 'improved',
            'observation': 'Fixture comparison schema only, no real video approval',
            'limitations': ['Synthetic unit fixture; not a media quality result'], 'next_action': 'Real playback required'}
        for role in ('before', 'after', 'unaffected'):
            name = f'review/{role}.md'
            (self.run / name).parent.mkdir(exist_ok=True)
            (self.run / name).write_text(f'Explicit synthetic {role} observation', encoding='utf-8')
            self.spec['evidence'].append({**self.asset(name), 'role': role,
                'video_sha256': self.spec['before' if role == 'before' else 'after']['sha256']})

    def record(self):
        write_json(self.run / 'inputs/improvement.json', self.spec)
        return improvement.record(self.run, 'inputs/improvement.json')

    def test_feedback_is_idempotent_queued_and_independent_of_run(self):
        result = self.record()
        self.assertEqual(result, self.record())
        self.assertFalse(result['automatic_promotion'])
        self.assertFalse(result['delivery_approval_changed'])
        self.assertIn(result['path'], knowledge_review.sources(self.root))
        value = read_json(self.root / result['path'])
        self.assertEqual(value['status'], 'candidate')
        self.assertEqual(value['scope']['target_language'], 'es')
        # Scoped fixture removal proves evidence survives without production media.
        shutil.rmtree(self.run)
        saved = bundles.verify(self.root / value['case'])
        self.assertTrue(any(f['path'] == 'evidence/review/unaffected.md' for f in saved['files']))

    def test_false_improvement_and_wrong_version_cannot_be_recorded(self):
        variants = []
        same = copy.deepcopy(self.spec); same['before'] = same['after']; variants.append((same, 'Unchanged video'))
        wrong = copy.deepcopy(self.spec); wrong['evidence'][1]['video_sha256'] = '0'*64
        variants.append((wrong, 'another video'))
        missing = copy.deepcopy(self.spec); missing['evidence'].pop(); variants.append((missing, 'unaffected control'))
        stale = copy.deepcopy(self.spec); stale['after']['sha256'] = '0'*64
        variants.append((stale, 'after changed'))
        for spec, reason in variants:
            with self.subTest(reason=reason):
                self.spec = spec
                with self.assertRaisesRegex(WorkflowError, reason):
                    self.record()

    def test_feedback_cannot_expand_scope_or_activate_itself(self):
        self.spec.update(status='active', scope={'workflow': 'all'}, company_preference=True)
        value = read_json(self.root / self.record()['path'])
        self.assertEqual(value['status'], 'candidate')
        self.assertEqual(value['scope']['source_sha256'], self.sha)
        self.assertFalse(value['company_preference'])

    def test_packet_drops_stale_probes_and_asks_about_style_audio_and_completeness(self):
        write_json(self.run / 'review/capture.json', {'video_sha256': 'old', 'review_probes': {'manifest': 'old'}})
        agenda = improvement.agenda(self.run)
        self.assertIsNone(agenda['whole_scene_probes'])
        self.assertTrue({'whole_scene', 'lettering', 'listening', 'delivery'} <= {q['id'] for q in agenda['questions']})
        self.assertEqual(agenda['max_revision_rounds'], 2)

    def test_incomplete_workspace_navigation_does_not_create_retry_authority(self):
        (self.root / 'config/workspace.json').unlink()
        agenda = improvement.agenda(self.run)
        self.assertIsNone(agenda['max_revision_rounds'])
        self.assertTrue(agenda['execution_requires_existing_policy'])

    def test_failed_intervention_is_exposed_in_next_work_packet(self):
        self.spec['outcome'] = 'no_improvement'
        self.record()
        guidance = improvement.agenda(self.run)['retry_guidance']
        self.assertEqual(guidance['state'], 'change_route_or_stop')
        self.assertEqual(guidance['failed_interventions'], [self.spec['intervention']])

    def test_earlier_candidate_probes_do_not_review_a_different_finalized_output(self):
        write_json(self.run / 'review/capture.json', {'video_sha256': self.spec['after']['sha256'],
            'review_probes': {'manifest': 'earlier-candidate'}})
        write_json(self.run / 'outputs/completion.json', {'video_sha256': 'different-finalized-video'})
        self.assertIsNone(improvement.agenda(self.run)['whole_scene_probes'])


class ProbeTests(unittest.TestCase):
    def test_sampling_is_bounded_and_keeps_opening_ending_and_high_risk_context(self):
        items = [{'id': f't{i:02}', 'start': i, 'end': i+.5, 'protected_regions': [[1, 1, 2, 2]] if i == 18 else []}
                 for i in range(20)]
        selected, omitted = review_probes.select_times({'text_instances': items,
            'shots': [{'id': str(i), 'start': i} for i in range(20)]}, 19.96)
        self.assertLessEqual(len(selected), review_probes.MAX_PAIRS)
        self.assertEqual(selected[0]['time'], 0)
        self.assertEqual(selected[-1]['time'], 19.96)
        self.assertTrue(any(c['time'] == 18.25 for c in selected))
        self.assertTrue(omitted)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_native_whole_scene_pairs_reuse_and_tamper_detection(self):
        with tempfile.TemporaryDirectory(dir=PROJECT / 'work/test-tmp') as temporary:
            run = Path(temporary) / 'runs/fixture'
            run.mkdir(parents=True)
            for name, color in [('source.mp4', 'blue'), ('after.mp4', 'yellow')]:
                media.ffmpeg(['-f', 'lavfi', '-i', f'color=c={color}:s=80x96:r=24:d=1',
                              '-c:v', 'libx264', '-pix_fmt', 'yuv420p', run / name])
            write_json(run / 'run.json', {'source': 'source.mp4', 'source_sha256': file_hash(run / 'source.mp4')})
            write_json(run / 'analysis/inventory.json', {'text_instances': [], 'shots': []})
            candidate = {'path': 'after.mp4', 'sha256': file_hash(run / 'after.mp4'), 'plan_id': 'fixture'}
            result = review_probes.generate(run, candidate)
            manifest = read_json(run / result['manifest'])
            self.assertFalse(result['automatic_pass'])
            self.assertEqual(len(manifest['pairs']), 5)
            self.assertAlmostEqual(manifest['pairs'][-1]['target_pts'], 23/24, places=5)
            with patch.object(media, 'ffmpeg', side_effect=AssertionError('Must not re-decode unchanged probes')):
                self.assertTrue(review_probes.generate(run, candidate)['reused'])
            media.ffmpeg(['-f', 'lavfi', '-i', 'color=c=green:s=80x96:r=24:d=1',
                          '-c:v', 'libx264', '-pix_fmt', 'yuv420p', run / 'revised.mp4'])
            revised = {'path': 'revised.mp4', 'sha256': file_hash(run / 'revised.mp4'), 'plan_id': 'fixture'}
            with patch.object(visual_audit, '_extract', wraps=visual_audit._extract) as extract:
                new_result = review_probes.generate(run, revised)
            self.assertEqual([call.args[0].name for call in extract.call_args_list], ['revised.mp4'])
            new_manifest = read_json(run / new_result['manifest'])
            self.assertEqual(new_manifest['binding']['video_sha256'], revised['sha256'])
            self.assertTrue(all(row['observation'] == 'pending' for row in new_manifest['pairs']))
            old_source = (run / result['manifest']).parent / manifest['pairs'][0]['source_image']
            new_source = (run / new_result['manifest']).parent / new_manifest['pairs'][0]['source_image']
            self.assertEqual(old_source.read_bytes(), new_source.read_bytes())
            frame = run / result['manifest']
            image = frame.parent / manifest['pairs'][0]['target_image']
            image.write_bytes(b'tampered fixture')
            with self.assertRaisesRegex(WorkflowError, 'evidence changed'):
                review_probes.generate(run, candidate)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_whole_scene_source_frames_reuse_within_request(self):
        with tempfile.TemporaryDirectory(dir=PROJECT / 'work/test-tmp') as temporary:
            root = Path(temporary)
            for name, color in [('source.mp4', 'blue'), ('after.mp4', 'yellow'), ('other.mp4', 'green')]:
                media.ffmpeg(['-f', 'lavfi', '-i', f'color=c={color}:s=80x96:r=24:d=1',
                              '-c:v', 'libx264', '-pix_fmt', 'yuv420p', root / name])

            def capture(name, requirement, target):
                run = root / 'runs' / name
                run.mkdir(parents=True)
                for filename in ('source.mp4', target):
                    shutil.copyfile(root / filename, run / filename)
                write_json(run / 'run.json',
                           {'source': 'source.mp4', 'source_sha256': file_hash(run / 'source.mp4')})
                write_json(run / 'inputs/fireplay.json', {'requirement_id': requirement})
                write_json(run / 'analysis/inventory.json', {'text_instances': [], 'shots': []})
                candidate = {'path': target, 'sha256': file_hash(run / target), 'plan_id': name}
                with patch.object(visual_audit, '_extract', wraps=visual_audit._extract) as extract:
                    result = review_probes.generate(run, candidate)
                manifest_path = run / result['manifest']
                manifest = read_json(manifest_path)
                return manifest_path, manifest, [call.args[0].name for call in extract.call_args_list]

            first, first_manifest, decoded = capture('de', 'request-a', 'after.mp4')
            self.assertEqual(decoded, ['source.mp4', 'after.mp4'])
            second, second_manifest, decoded = capture('fr', 'request-a', 'other.mp4')
            self.assertEqual(decoded, ['other.mp4'])
            self.assertNotEqual(first_manifest['binding']['video_sha256'], second_manifest['binding']['video_sha256'])
            self.assertEqual(first_manifest['omitted_probes'], second_manifest['omitted_probes'])
            self.assertFalse(second_manifest['automatic_pass'])
            for first_pair, second_pair in zip(first_manifest['pairs'], second_manifest['pairs']):
                self.assertEqual(first_pair['source_pts'], second_pair['source_pts'])
                self.assertEqual(second_pair['observation'], 'pending')
                self.assertTrue((first.parent / first_pair['source_image']).samefile(
                    second.parent / second_pair['source_image']))

            _, _, decoded = capture('ko', 'request-b', 'other.mp4')
            self.assertEqual(decoded, ['source.mp4', 'other.mp4'])
            source_frame = second.parent / second_manifest['pairs'][0]['source_image']
            source_frame.unlink()
            _, _, decoded = capture('ja', 'request-a', 'other.mp4')
            self.assertEqual(decoded, ['source.mp4', 'other.mp4'])
            self.assertTrue((first.parent / first_manifest['pairs'][0]['source_image']).is_file())
