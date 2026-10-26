import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_localizer import media, visual_audit as audit, render_cache, production, learning_evidence
from video_localizer.common import WorkflowError, file_hash, read_json, write_json

PROJECT = Path(__file__).resolve().parents[1]


class EvidenceReuseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=PROJECT / 'work/test-tmp')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.run = self.root / 'runs/fixture'
        self.run.mkdir(parents=True)
        for name, color in [('source', 'blue'), ('master', 'black'), ('candidate', 'green')]:
            media.ffmpeg(['-f', 'lavfi', '-i', f'color=c={color}:s=64x48:r=10:d=0.6',
                          '-c:v', 'ffv1', self.run / (name + '.mkv')])
        self.source = self.run / 'source.mkv'
        sha = file_hash(self.source)
        write_json(self.run / 'run.json', {'source': 'source.mkv', 'source_sha256': sha,
                                         'visual_storage': 'comparisons-v3'})
        write_json(self.run / 'inputs/request.json', {'target_language': 'es'})
        write_json(self.run / 'analysis/media.json', media.probe(self.source))
        asset = {'path': 'master.mkv', 'sha256': file_hash(self.run / 'master.mkv')}
        write_json(self.run / 'preparation.json', {'source_sha256': sha, 'target_language': None,
                   'contains_target_typography': False, 'output': asset,
                   'inputs': [{'path': 'source.mkv', 'sha256': sha}]})
        self.inventory = {'content_features': ['animated_text'],
            'shots': [{'id': 's1', 'start': 0, 'end': .6, 'prepared_video': {
                **asset, 'record': 'preparation.json', 'record_sha256': file_hash(self.run / 'preparation.json')}}],
            'text_instances': [{'id': 't1', 'source_text': 'Test', 'target_text': 'Prueba',
                'action': 'solid_overlay', 'start': .1, 'end': .5, 'bbox': [20, 20, 20, 10]}]}
        write_json(self.run / 'analysis/inventory.json', self.inventory)
        self.revision(1)

    def revision(self, number, candidate='candidate.mkv'):
        write_json(self.run / 'plan.json', {'id': f'plan-{number}'})
        write_json(self.run / 'outputs/candidate.json', {'path': candidate,
            'sha256': file_hash(self.run / candidate), 'plan_id': f'plan-{number}'})

    def manifest(self, result):
        return read_json(self.run / result['manifest'])

    def test_unchanged_layers_skip_decoding_but_never_copy_reviews(self):
        from video_localizer.crop_stream import CropStream
        first = audit.generate(self.run)
        old_path = self.run / first['manifest']
        old_hash = file_hash(old_path)
        failed_page = self.manifest(first)['instances'][0]['pages'][2]['id']
        write_json(old_path.parent / 'observations/failed.json', {'checks': {'erasure': {
            'status': 'fail', 'observation': 'Fixture residual letter at this actual frame',
            'evidence_pages': [failed_page]}}})
        old_files = {p: file_hash(p) for p in old_path.parent.rglob('*') if p.is_file()}
        self.revision(2)
        with patch('video_localizer.crop_stream.CropStream', wraps=CropStream) as decoder, \
             patch.object(audit, '_timestamps', wraps=audit._timestamps) as clock, \
             patch('PIL.Image.Image.crop', side_effect=AssertionError('Unchanged page was decomposed')):
            second = audit.generate(self.run)
        self.assertEqual(decoder.call_count, 0)
        self.assertEqual(clock.call_count, 0)
        self.assertEqual(second['decode_reuse']['layer_frames_reused'], 18)
        self.assertEqual(second['decode_reuse']['pages_reused_before_composition'], 6)
        self.assertEqual(self.manifest(first)['instances'], self.manifest(second)['instances'])
        self.assertEqual(file_hash(old_path), old_hash)
        self.assertTrue((old_path.parent / 'observations/failed.json').exists())
        self.assertEqual(old_files, {p: file_hash(p) for p in old_files})
        selected = learning_evidence.select(self.run, history=True)
        self.assertIn(old_path.parent / failed_page, selected)
        self.assertIn(old_path.parent / 'observations/failed.json', selected)
        folder = (self.run / second['manifest']).parent
        self.assertEqual(read_json(folder / 'reviews.json'), {})
        template = read_json(next((folder / 'templates').glob('*.json')))
        self.assertEqual({v['status'] for v in template['checks'].values()}, {'pending'})
        with self.assertRaisesRegex(WorkflowError, 'pending or incomplete'):
            audit.verify_final(self.run)

    def test_changed_target_decodes_only_changed_layer_and_matches_uncached_pixels(self):
        from video_localizer.crop_stream import CropStream
        audit.generate(self.run)
        media.ffmpeg(['-f', 'lavfi', '-i', 'testsrc2=s=64x48:r=10:d=0.6',
                      '-c:v', 'ffv1', self.run / 'changed.mkv'])
        before = file_hash(self.run / 'changed.mkv')
        self.revision(2, 'changed.mkv')
        with patch('video_localizer.crop_stream.CropStream', wraps=CropStream) as decoder:
            warm = audit.generate(self.run)
        self.assertEqual([Path(c.args[0]).name for c in decoder.call_args_list], ['changed.mkv'])
        self.assertEqual(warm['decode_reuse']['layer_frames_reused'], 12)
        self.assertEqual(warm['decode_reuse']['layer_frames_decoded'], 6)
        self.revision(3, 'changed.mkv')
        cold = audit.generate(self.run, reuse_decode=False)
        a, b = self.manifest(warm), self.manifest(cold)
        self.assertEqual(a['instances'], b['instances'])
        self.assertEqual(a['files'], b['files'])
        self.assertEqual(file_hash(self.run / 'changed.mkv'), before)

    def test_local_pixel_change_reuses_other_pages_only_after_decoding_new_target(self):
        from video_localizer.visual_reuse import EvidenceCache
        from video_localizer.crop_stream import CropStream
        audit.generate(self.run)
        media.ffmpeg(['-i', self.run / 'candidate.mkv', '-vf',
                      "drawbox=x=25:y=25:w=4:h=4:color=red:t=fill:enable='eq(n,2)'",
                      '-c:v', 'ffv1', self.run / 'repair.mkv'])
        self.revision(2, 'repair.mkv')
        loads = []
        original = EvidenceCache.load
        def tracked(cache, entry, size):
            loads.append(entry['path'])
            return original(cache, entry, size)
        with patch.object(EvidenceCache, 'load', new=tracked), \
             patch('video_localizer.crop_stream.CropStream', wraps=CropStream) as decoder:
            warm = audit.generate(self.run)
        self.assertEqual([Path(c.args[0]).name for c in decoder.call_args_list], ['repair.mkv'])
        self.assertEqual(warm['decode_reuse']['layer_frames_decoded'], 6)
        self.assertEqual(warm['decode_reuse']['pages_reused_before_composition'], 5)
        self.assertEqual(len(loads), 2)
        self.revision(3, 'repair.mkv')
        cold = audit.generate(self.run, reuse_decode=False)
        self.assertEqual(self.manifest(warm)['instances'], self.manifest(cold)['instances'])
        self.assertEqual(self.manifest(warm)['files'], self.manifest(cold)['files'])

    def test_missing_cached_pages_rebuild_but_corruption_is_rejected(self):
        first = audit.generate(self.run)
        folder = (self.run / first['manifest']).parent
        for p in folder.rglob('compare-*.png'):
            p.unlink()
        self.revision(2)
        second = audit.generate(self.run)
        self.assertEqual(second['decode_reuse']['layer_frames_decoded'], 18)
        manifest = self.manifest(second)
        page = (self.run / second['manifest']).parent / manifest['instances'][0]['pages'][0]['id']
        page.write_bytes(b'corrupt')
        self.revision(3)
        with self.assertRaisesRegex(WorkflowError, 'cache changed'):
            audit.generate(self.run)
        self.assertFalse((self.run / 'review/review.json').exists())

    def test_region_change_does_not_reuse_wrong_crops(self):
        audit.generate(self.run)
        self.inventory['text_instances'][0]['bbox'] = [0, 0, 4, 4]
        write_json(self.run / 'analysis/inventory.json', self.inventory)
        self.revision(2)
        warm = audit.generate(self.run)
        self.assertEqual(warm['decode_reuse']['layer_frames_decoded'], 18)
        self.revision(3)
        cold = audit.generate(self.run, reuse_decode=False)
        self.assertEqual(self.manifest(warm)['instances'], self.manifest(cold)['instances'])

    def test_transparent_layer_reuse_matches_original_alpha_composition(self):
        layer = self.run / 'type.mov'
        media.ffmpeg(['-f', 'lavfi', '-i', 'color=c=red@0.35:s=64x48:r=10:d=0.6,format=argb',
                      '-c:v', 'qtrle', layer])
        self.inventory['shots'][0]['surface_typography'] = {'path': layer.name, 'sha256': file_hash(layer)}
        write_json(self.run / 'analysis/inventory.json', self.inventory)
        first = audit.generate(self.run)
        self.revision(2)
        warm = audit.generate(self.run)
        self.assertEqual(warm['decode_reuse']['layer_frames_reused'], 24)
        self.revision(3)
        cold = audit.generate(self.run, reuse_decode=False)
        self.assertEqual(self.manifest(first)['instances'], self.manifest(warm)['instances'])
        self.assertEqual(self.manifest(cold)['files'], self.manifest(warm)['files'])

    def test_changed_frame_rate_reuses_actual_source_indices_without_dropping_pages(self):
        audit.generate(self.run)
        media.ffmpeg(['-f', 'lavfi', '-i', 'testsrc2=s=64x48:r=20:d=0.6',
                      '-c:v', 'ffv1', self.run / 'fast.mkv'])
        self.revision(2, 'fast.mkv')
        warm = audit.generate(self.run)
        self.revision(3, 'fast.mkv')
        cold = audit.generate(self.run, reuse_decode=False)
        self.assertEqual(self.manifest(warm)['instances'], self.manifest(cold)['instances'])
        self.assertEqual(self.manifest(warm)['files'], self.manifest(cold)['files'])
        self.assertGreater(len(self.manifest(warm)['instances'][0]['pages']), 6)

    def test_partial_cache_miss_decodes_only_missing_frames(self):
        from video_localizer.crop_stream import CropStream
        first = audit.generate(self.run)
        # Every frame in this solid-color fixture shares bytes, but has its own
        # bound page path. Removing one name must not discard the other frames.
        manifest = self.manifest(first)
        ((self.run / first['manifest']).parent / manifest['instances'][0]['pages'][2]['id']).unlink()
        self.revision(2)
        with patch('video_localizer.crop_stream.CropStream', wraps=CropStream) as decoder:
            result = audit.generate(self.run)
        self.assertEqual(result['decode_reuse']['layer_frames_decoded'], 3)
        self.assertEqual(result['decode_reuse']['layer_frames_reused'], 15)
        self.assertEqual([c.args[1] for c in decoder.call_args_list], [[2], [2], [2]])

    def test_cache_indexes_do_not_make_new_evidence_depend_on_old_run(self):
        first = audit.generate(self.run)
        other = self.root / 'runs/other'
        shutil.copytree(self.run, other, ignore=shutil.ignore_patterns('review'))
        write_json(other / 'plan.json', {'id': 'other-plan'})
        result = audit.generate(other)
        self.assertEqual(result['decode_reuse']['layer_frames_reused'], 18)
        folder = (other / result['manifest']).parent
        self.assertTrue(self.run.resolve().is_relative_to(self.root.resolve()))
        shutil.rmtree(self.run)
        audit._verify_files(folder, read_json(folder / audit.MANIFEST))
        self.assertEqual(read_json(folder / 'reviews.json'), {})

    def test_clock_cache_corruption_is_not_silently_trusted(self):
        audit.generate(self.run)
        record = next((self.root / 'state/visual-decode-cache/clocks').glob('*.json'))
        value = read_json(record)
        value['value']['times'][0] = 100
        write_json(record, value)
        self.revision(2)
        with self.assertRaisesRegex(WorkflowError, 'decode cache changed'):
            audit.generate(self.run)

    def test_unrelated_code_does_not_invalidate_render_dependencies(self):
        code = self.root / 'code'
        shutil.copytree(PROJECT / 'src/video_localizer', code / 'src/video_localizer',
                        ignore=shutil.ignore_patterns('__pycache__'))
        with patch.object(render_cache, 'CODE_ROOT', code):
            before = render_cache.implementation_signature()
            plan = {'source_sha256': file_hash(self.source)}
            fingerprint = production._fingerprint(self.run, plan)
            (code / 'src/video_localizer/retention.py').write_text('# unrelated cleanup change\n')
            self.assertEqual(before, render_cache.implementation_signature())
            self.assertEqual(fingerprint, production._fingerprint(self.run, plan))
            (code / 'src/video_localizer/media.py').write_text('# changed renderer\n')
            self.assertNotEqual(before, render_cache.implementation_signature())
            self.assertNotEqual(fingerprint, production._fingerprint(self.run, plan))


class CacheBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=PROJECT / 'work/test-tmp')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_link_fallback_reports_copy_without_altering_pixels(self):
        from PIL import Image
        from video_localizer.visual_storage import PageStore
        im = Image.new('RGB', (24, 24), 'red')
        original, duplicate = self.root / 'old.png', self.root / 'new.png'
        store = PageStore(self.root)
        store.save(im, original)
        store.commit()
        store = PageStore(self.root)
        with patch('video_localizer.visual_storage.os.link', side_effect=OSError(18, 'cross-device')):
            store.save(im, duplicate)
        self.assertEqual(store.stats['copied'], 1)
        self.assertEqual(store.stats['linked'], 0)
        self.assertEqual(file_hash(original), file_hash(duplicate))
        original.unlink()
        with Image.open(duplicate) as actual:
            self.assertEqual(actual.tobytes(), im.tobytes())

    def test_metadata_publication_merges_concurrent_snapshots_and_preserves_previous_on_failure(self):
        from video_localizer.visual_reuse import EvidenceCache
        first, second = EvidenceCache(self.root), EvidenceCache(self.root)
        first.pending['fixture'] = {'0': {'path': 'first.png'}}
        second.pending['fixture'] = {'1': {'path': 'second.png'}}
        first.commit()
        second.commit()
        record = first.directory / 'tiles/fixture.json'
        self.assertEqual(set(read_json(record)['value']), {'0', '1'})
        before = file_hash(record)
        first.pending['fixture'] = {'2': {'path': 'third.png'}}
        with patch('video_localizer.visual_reuse.write_json', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):
                first.commit()
        self.assertEqual(file_hash(record), before)

    def test_source_changed_during_probe_does_not_publish_clock_cache(self):
        from video_localizer.visual_reuse import EvidenceCache
        source = self.root / 'source.mkv'
        source.write_bytes(b'original')
        cache = EvidenceCache(self.root)
        def loader():
            source.write_bytes(b'changed')
            return [0], {'width': 1}
        with self.assertRaisesRegex(WorkflowError, 'input changed'):
            cache.clock(source, loader)
        self.assertFalse(list(cache.directory.rglob('*.json')))

    def test_memory_tiles_are_bounded_copied_and_still_detect_file_tampering(self):
        from PIL import Image
        from video_localizer.visual_reuse import EvidenceCache
        path = self.root / 'page.png'
        Image.new('RGB', (20, 20), 'red').save(path)
        cache = EvidenceCache(self.root)
        cache.max_image_bytes = 20 * 20 * 3
        entry = {'path': path.name, 'sha256': file_hash(path), 'box': [0, 0, 20, 20]}
        first = cache.load(entry, (20, 20))
        first.putpixel((0, 0), (0, 0, 0))
        with patch('PIL.Image.open', side_effect=AssertionError('Repeated PNG decode')):
            self.assertEqual(cache.load(entry, (20, 20)).getpixel((0, 0)), (255, 0, 0))
        other = self.root / 'other.png'
        Image.new('RGB', (20, 20), 'blue').save(other)
        cache.load({'path': other.name, 'sha256': file_hash(other), 'box': [0, 0, 20, 20]}, (20, 20))
        self.assertLessEqual(cache.image_bytes, cache.max_image_bytes)
        self.assertEqual(len(cache.images), 1)
        path.write_bytes(b'changed')
        with self.assertRaisesRegex(WorkflowError, 'cache changed'):
            cache.load(entry, (20, 20))

    def test_render_signature_does_not_make_optional_pillow_mandatory(self):
        with patch.dict(sys.modules, {'PIL': None}):
            self.assertIsNone(render_cache.implementation_signature()['pillow'])


if __name__ == '__main__':
    unittest.main()
