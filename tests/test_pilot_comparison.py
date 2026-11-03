import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_localizer import batches, media, pilot_review
from video_localizer.common import WorkflowError, file_hash, object_hash, write_json


class PilotComparisonTests(unittest.TestCase):
    def test_segmented_demo_keeps_transition_at_source_time(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp) / 'runs/pilot-segment-demo'
            run.mkdir(parents=True)
            for name, color in [('source', 'gray'), ('neutral-a', 'red'), ('neutral-b', 'lime'), ('target', 'white')]:
                media.ffmpeg(['-f', 'lavfi', '-i', f'color={color}:s=32x32:r=4:d=2', run/(name+'.mp4')])
            write_json(run/'run.json', {'source': 'source.mp4', 'source_sha256': file_hash(run/'source.mp4')})
            write_json(run/'analysis/inventory.json', {'text_instances': [
                {'id': 'title', 'start': .5, 'end': 1.25, 'action': 'translate'}]})
            segments = []
            for start, filename in [(0, 'neutral-a.mp4'), (4, 'neutral-b.mp4')]:
                segments.append({'start_frame': start, 'end_frame': start+4, 'asset_start_frame': 2,
                                 'asset': {'path': filename, 'sha256': file_hash(run/filename)}})
            write_json(run/'plan.json', {'id': 'demo', 'restoration_base': {'segments': segments}})
            write_json(run/'outputs/candidate.json', {'plan_id': 'demo', 'sha256': file_hash(run/'target.mp4')})
            packet = pilot_review.compare(run, 'title', 'target.mp4')
            # Left/source and right/target stay fixed as the center changes at source frame 4.
            from PIL import Image
            for i, time in enumerate((.5, .75)):
                image = run/f'comparison-{i}.png'
                media.ffmpeg(['-ss', time, '-i', run/packet['clip']['path'], '-frames:v', 1, image])
                with Image.open(image) as picture:
                    self.assertEqual(picture.size, (96, 32))
                    red, green, _ = picture.getpixel((48, 16))[:3]
                    self.assertTrue(red > 200 and green < 40 if i == 0 else green > 200 and red < 40)

    def test_expansion_requires_current_review_even_for_best_available(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp) / 'runs/pilot'
            write_json(run/'analysis/inventory.json', {'text_instances': [{'id': 'cta', 'action': 'translate'}]})
            assets = {}
            for key in ('source', 'target', 'base', 'clip'):
                path = run/(key + '.mp4')
                path.write_bytes(key.encode())
                assets[key] = {'path': path.name, 'sha256': file_hash(path)}
            write_json(run/'run.json', {'source_sha256': assets['source']['sha256']})
            snapshot = {'video_sha256': assets['target']['sha256']}
            with self.assertRaisesRegex(WorkflowError, 'Before expansion'):
                pilot_review.release_check(run, snapshot, True)
            binding = {key: assets[key] for key in ('source', 'target', 'base')}
            binding.update(inventory_sha256=file_hash(run/'analysis/inventory.json'), instance='cta')
            manifest = run/'review/pilot-comparisons'/object_hash(binding)/'comparison.json'
            write_json(manifest, {'binding': binding, 'clip': assets['clip']})
            report = {'comparison': {'path': manifest.relative_to(run).as_posix(), 'sha256': file_hash(manifest)},
                      'reviewer': 'fixture', 'why_hardest': 'Outlined moving CTA',
                      'observations': {'residue': 'Yellow edge above CTA', 'subject': 'Arrow intact',
                                       'lettering': 'Target below source', 'timing': 'Both exit on cut'},
                      'decision': 'repair'}
            path = run/'review/pilot-review.json'
            write_json(path, report)
            with self.assertRaisesRegex(WorkflowError, 'Repair common'):
                pilot_review.release_check(run, snapshot, True)
            report['decision'] = 'clear'
            write_json(path, report)
            with self.assertRaisesRegex(WorkflowError, 'different inventory or video'):
                pilot_review.release_check(run, {'video_sha256': 'other'}, False)
            report['observations']['timing'] = ''
            write_json(path, report)
            with self.assertRaisesRegex(WorkflowError, 'four observations'):
                pilot_review.release_check(run, snapshot, False)
            report['observations']['timing'] = 'Both exit on cut'
            report.update(decision='best_available', limitation='Repair rounds exhausted; thin edge remains')
            write_json(path, report)
            with self.assertRaisesRegex(WorkflowError, 'Repair common'):
                pilot_review.release_check(run, snapshot, False)
            self.assertEqual(pilot_review.release_check(run, snapshot, True), file_hash(path))
            root = run.parent.parent
            child = root/'runs/child'
            write_json(root/'state/batches/demo.json', {'id': 'demo', 'pilot': 'pilot', 'members': ['pilot', 'child'],
                                                        'source_sha256': assets['source']['sha256'], 'state': 'pilot_pending'})
            write_json(child/'run.json', {'source_sha256': assets['source']['sha256']})
            write_json(child/'inputs/request.json', {'delivery_mode': 'fast'})
            completed = {**snapshot, 'scope': 'best_available', 'masters': []}
            with patch.object(batches, '_finalized_pilot_snapshot', side_effect=lambda *args: dict(completed)):
                result = batches.approve('demo', root, best_available=True)
                self.assertEqual(result['pilot_release']['pilot_review_sha256'], file_hash(path))
                batches.gate(child)
                report['observations']['subject'] = 'Revised observation'
                write_json(path, report)
                with self.assertRaisesRegex(WorkflowError, 'Pilot changed'):
                    batches.gate(child)
            (run/'base.mp4').write_bytes(b'replacement')
            with self.assertRaisesRegex(WorkflowError, 'evidence changed'):
                pilot_review.release_check(run, snapshot, True)
