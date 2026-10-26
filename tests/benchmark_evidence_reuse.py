"""Opt-in, isolated two-layer audit benchmark; never edits the supplied run.

Usage: python tests/benchmark_evidence_reuse.py SOURCE TARGET INVENTORY --report PATH
This measures evidence generation, not rendering, paid inference or acceptance.
"""
import argparse
import copy
import json
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'src'))
from video_localizer import media, visual_audit
from video_localizer.common import file_hash, read_json, require, write_json


def benchmark(source, target, inventory_path, seed_target=None, repetitions=2):
    seed_target = seed_target or target
    require(1 <= repetitions <= 3, 'Choose one to three benchmark repetitions')
    originals = {p: file_hash(p) for p in (source, target, inventory_path, seed_target)}
    records = []
    with tempfile.TemporaryDirectory(prefix='reuse-benchmark-', dir=PROJECT / 'work/test-tmp') as temp:
        root = Path(temp).resolve()
        require(root.is_relative_to((PROJECT / 'work/test-tmp').resolve()), 'Isolated benchmark required')
        run = root / 'runs/fixture'
        run.mkdir(parents=True)
        source_copy = run / ('source' + source.suffix)
        target_copy = run / ('candidate' + target.suffix)
        shutil.copyfile(source, source_copy)
        shutil.copyfile(target, target_copy)
        seed_copy = target_copy
        if seed_target != target:
            seed_copy = run / ('seed' + seed_target.suffix)
            shutil.copyfile(seed_target, seed_copy)
        inventory = copy.deepcopy(read_json(inventory_path))
        for shot in inventory['shots']:
            shot.pop('prepared_video', None)
            shot.pop('surface_typography', None)
        write_json(run / 'run.json', {'source': source_copy.name, 'source_sha256': originals[source],
                                    'visual_storage': 'comparisons-v3'})
        write_json(run / 'inputs/request.json', {'target_language': 'en'})
        write_json(run / 'analysis/media.json', media.probe(source_copy))
        write_json(run / 'analysis/inventory.json', inventory)
        expected = None
        # Seed separately; compare repeated uncached/warm work with the same
        # pixel store so existing PNG deduplication cannot explain the speedup.
        for n, enabled in enumerate([True] + [False, True] * repetitions):
            selected = seed_copy if n == 0 else target_copy
            write_json(run / 'plan.json', {'id': f'benchmark-{n}'})
            write_json(run / 'outputs/candidate.json', {'path': selected.name,
                'sha256': originals[seed_target if n == 0 else target], 'plan_id': f'benchmark-{n}'})
            started = time.perf_counter()
            result = visual_audit.generate(run, reuse_decode=enabled)
            elapsed = time.perf_counter() - started
            manifest = read_json(run / result['manifest'])
            actual = {'instances': manifest['instances'], 'files': manifest['files']}
            if n > 0 or seed_target == target:
                if expected is None:
                    expected = actual
                require(actual == expected, 'Cached evidence differs from fresh decoding')
            records.append({'mode': 'seed' if n == 0 else 'warm' if enabled else 'uncached',
                            'seconds': round(elapsed, 6), 'decode_reuse': result['decode_reuse'],
                            'pixel_storage': result['pixel_storage']})
            print(json.dumps({'iteration': n, 'mode': records[-1]['mode'],
                              'seconds': round(elapsed, 3)}), flush=True)
        pages = sum(len(i['pages']) for i in expected['instances'])
        cache_bytes = sum(p.stat().st_size for p in (root / 'state/visual-decode-cache').rglob('*') if p.is_file())
    require(all(file_hash(p) == digest for p, digest in originals.items()), 'Original inputs changed')
    medians = {mode: statistics.median(r['seconds'] for r in records if r['mode'] == mode)
               for mode in ('uncached', 'warm')}
    return {'scope': 'Isolated source/target evidence only; no video rendering or acceptance claim',
            'source_sha256': originals[source], 'target_sha256': originals[target],
            'seed_target_sha256': originals[seed_target], 'repetitions': repetitions,
            'instances': len(expected['instances']), 'pages_per_version': pages,
            'identical_files_and_frame_mappings': True, 'original_inputs_unchanged': True,
            'cache_metadata_bytes': cache_bytes, 'additional_cached_media_bytes': 0,
            'medians_seconds': medians,
            'warm_reduction_percent': round(100 * (1 - medians['warm'] / medians['uncached']), 2),
            'runs': records}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('target', type=Path)
    parser.add_argument('inventory', type=Path)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--seed-target', type=Path)
    parser.add_argument('--repetitions', type=int, default=2)
    args = parser.parse_args()
    result = benchmark(args.source.resolve(), args.target.resolve(), args.inventory.resolve(),
                       args.seed_target.resolve() if args.seed_target else None, args.repetitions)
    if args.report:
        report = args.report.resolve()
        require(report.is_relative_to(PROJECT) and not report.exists(), 'Select a new report inside the project')
        write_json(report, result)
    print(json.dumps(result, indent=2))
