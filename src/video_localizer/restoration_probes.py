"""Native source / pre-lettering base / encoded result evidence, never an OCR pass."""
import bisect
import html
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

from .common import file_hash, inside, object_hash, read_json, require, write_json


def _clock_tolerance(source_meta, base_meta):
    # Matroska commonly rounds native 30fps timestamps to millisecond ticks.
    # That is quantization, not a dropped/repeated/retimed source frame.
    def tick(meta):
        stream = next(s for s in meta['raw']['streams'] if s['codec_type'] == 'video')
        return float(Fraction(stream['time_base']))
    return max(.0002, min(.25/source_meta['fps'], tick(source_meta)+tick(base_meta)+.000001))


def _extract_sparse(path, numbers, region, destination):
    from . import media
    from .visual_audit import _selection
    # A linear sum of >100 isolated between() terms overflows FFmpeg's
    # expression parser even on an 80x96 fixture. Balance the expression tree;
    # do not silently drop instances or decode every frame into retained PNGs.
    def balanced(terms):
        if len(terms) == 1:
            return terms[0]
        middle = len(terms)//2
        return '('+balanced(terms[:middle])+'+'+balanced(terms[middle:])+')'
    selection = balanced(_selection(numbers).split('+'))
    destination.mkdir(parents=True, exist_ok=True)
    x,y,w,h = region
    media.ffmpeg(['-threads','2','-i',path,'-filter_threads','1','-vf',
                  f"select='{selection}',crop={w}:{h}:{x}:{y}:exact=1",
                  '-fps_mode','passthrough','-an','-threads','2',destination/'%06d.png'])
    files = sorted(destination.glob('*.png'))
    require(len(files) == len(set(numbers)), 'Restoration evidence extraction is incomplete')
    return dict(zip(sorted(set(numbers)),files))


def validate_base(run, base, assets):
    """The caller supplies the actual pre-lettering inputs, not the finished movie."""
    if base is None:
        return
    require(isinstance(base, dict), 'Restoration base must be an object')
    segments = base.get('segments', [])
    require(segments, 'Restoration base needs native-frame segments')
    cursor = 0
    for segment in segments:
        first, last, offset = (segment.get(k) for k in ('start_frame', 'end_frame', 'asset_start_frame'))
        require(all(type(n) is int for n in (first, last, offset))
                and first == cursor and last > first and offset >= 0,
                'Restoration base must cover a contiguous native timeline')
        asset = segment['asset']
        require(asset in assets and file_hash(inside(run, asset['path'])) == asset['sha256'],
                'Restoration base must bind actual recipe dependency bytes')
        cursor = last


def sample_frames(item, times):
    intervals = [item.get('source_interval', [item['start'], item['end']])]
    if item.get('source_ghost_interval'):
        intervals.append(item['source_ghost_interval'])
    selected = set()
    for start, end in intervals:
        first = bisect.bisect_left(times, start - .00001)
        last = bisect.bisect_left(times, end - .00001) - 1
        if 0 <= first <= last < len(times):
            # Inspect one actual frame outside both declared boundaries too:
            # inaccurate source intervals otherwise hide their own held tails.
            selected.update(n for n in (first-1, first, (first + last)//2, last, last+1)
                            if 0 <= n < len(times))
    require(selected, 'Restoration instance has no native source frames: ' + item['id'])
    return sorted(selected)


def generate(run, candidate, plan):
    from PIL import Image
    from .workflow import source_path
    from .visual_audit import _clock, _region
    from .text_restoration import items
    inventory_path = run / 'analysis/inventory.json'
    inventory = read_json(inventory_path)
    edited = items(inventory)
    base = plan.get('restoration_base')
    if not edited:
        return {'state': 'not_applicable', 'automatic_pass': False}
    if base is None:
        return {'state': 'missing_clean_base', 'automatic_pass': False,
                'next_action': 'Bind the actual pre-lettering base in the fast recipe; the target overlay is not erasure evidence.'}
    validate_base(run, base, plan['assets'])
    source, target = source_path(run), inside(run, candidate['path'])
    require(file_hash(target) == candidate['sha256'], 'Restoration candidate changed')
    binding = {'version': 1, 'source_sha256': file_hash(source), 'video_sha256': candidate['sha256'],
               'inventory_sha256': file_hash(inventory_path), 'plan_id': candidate['plan_id'], 'base': base,
               'implementation_sha256': file_hash(Path(__file__))}
    folder = run / 'review' / candidate['sha256'][:12] / ('restoration-' + object_hash(binding)[:16])
    manifest_path = folder / 'manifest.json'
    if manifest_path.exists():
        manifest = read_json(manifest_path)
        require(manifest['binding'] == binding, 'Restoration probe binding changed')
        for name, digest in manifest['files'].items():
            require(file_hash(inside(folder, name)) == digest, 'Restoration evidence changed')
        return {'state': 'captured', 'manifest': manifest_path.relative_to(run).as_posix(),
                'sha256': file_hash(manifest_path), 'reused': True, 'automatic_pass': False}
    from .visual_reuse import EvidenceCache
    reuse = EvidenceCache(run.parent.parent)
    clocks = {'_reuse': reuse}
    times, meta = _clock(source, clocks)
    target_times, target_meta = _clock(target, clocks)
    require(len(times) == len(target_times) and all(abs(a-b) < .0002 for a,b in zip(times, target_times))
            and (meta['width'], meta['height']) == (target_meta['width'], target_meta['height']),
            'Restoration evidence needs the actual native source/target timeline')
    require(base['segments'][-1]['end_frame'] == len(times), 'Restoration base does not cover the full source')
    rows = []
    for item in edited:
        # Include both source and target positions plus effect margin. A shifted
        # target can otherwise hide an unexamined source outline just outside it.
        geometry = dict(item)
        geometry['trajectory'] = list(item.get('trajectory', []))
        if item.get('source_effect_bbox'):
            geometry['trajectory'].append({'bbox': item['source_effect_bbox']})
        if item.get('display', {}).get('bbox'):
            geometry['trajectory'].append({'bbox': item['display']['bbox']})
        region = _region(geometry, meta['width'], meta['height'])
        for number in sample_frames(item, times):
            segment = next(s for s in base['segments'] if s['start_frame'] <= number < s['end_frame'])
            base_number = segment['asset_start_frame'] + number - segment['start_frame']
            base_path = inside(run, segment['asset']['path'])
            base_times, base_meta = _clock(base_path, clocks)
            require(base_number < len(base_times) and (meta['width'], meta['height']) ==
                    (base_meta['width'], base_meta['height']) and abs(meta['fps']-base_meta['fps']) < .001 and
                    abs((base_times[base_number] - base_times[segment['asset_start_frame']]) -
                        (times[number] - times[segment['start_frame']])) <= _clock_tolerance(meta, base_meta),
                    'Restoration base frame mapping changed')
            rows.append({'id': item['id'], 'source_frame': number, 'source_pts': times[number],
                         'base_frame': base_number, 'base_asset': segment['asset'], 'region': region,
                         'observation': 'pending'})
    folder.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.restoration-', dir=folder.parent) as temporary:
        staging = Path(temporary) / 'bundle'
        staging.mkdir()
        # Decode each movie once. Extraction scratch is temporary, not a second
        # retained copy of full frames; only native comparison strips survive.
        groups = {}
        for index, row in enumerate(rows):
            for role, movie, number in (('source', source, row['source_frame']),
                                       ('base', inside(run, row['base_asset']['path']), row['base_frame']),
                                       ('target', target, row['source_frame'])):
                groups.setdefault(movie, []).append((index, role, number))
        for movie, requests in groups.items():
            with TemporaryDirectory(dir=temporary) as scratch:
                frames = _extract_sparse(movie, [r[2] for r in requests],
                                  [0, 0, meta['width'], meta['height']], Path(scratch))
                for index, role, number in requests:
                    x,y,w,h = rows[index]['region']
                    with Image.open(frames[number]) as image:
                        image.crop((x,y,x+w,y+h)).save(staging / f'{index:04}-{role}.png')
        for index, row in enumerate(rows):
            paths = [staging / f'{index:04}-{role}.png' for role in ('source', 'base', 'target')]
            w,h = row['region'][2:]
            strip = Image.new('RGB', (w*3, h))
            for column, path in enumerate(paths):
                with Image.open(path) as image:
                    strip.paste(image, (column*w, 0))
                path.unlink()  # Scratch crops, already represented losslessly in strip.
            row['image'] = f'{index:04}.png'
            strip.save(staging / row['image'])
        body = ''.join('<p>'+html.escape(f"{r['id']} / frame {r['source_frame']} / {r['source_pts']:.4f}s")+
                       '</p><img src="'+r['image']+'">' for r in rows)
        (staging/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>去字三路对照</title>'
            '<style>body{background:#171717;color:white;font:16px sans-serif}img{max-width:100%}</style>'
            '<h1>原片 ｜ 实际写字前底片 ｜ 当前译片</h1><p>待人工审核；静帧不代表运动通过。</p>'+body, encoding='utf-8')
        manifest = {'binding': binding, 'rows': rows, 'automatic_pass': False,
                    'decode_reuse': reuse.stats,
                    'limitation': 'Native first/middle/last plus adjacent boundary guards for source/ghost intervals; sampling is not full playback or automatic text detection.',
                    'files': {p.name:file_hash(p) for p in staging.iterdir() if p.is_file()}}
        write_json(staging/'manifest.json', manifest)
        staging.rename(folder)
    return {'state': 'captured', 'manifest': manifest_path.relative_to(run).as_posix(),
            'sha256': file_hash(manifest_path), 'reused': False, 'automatic_pass': False}


def review_coverage(run, candidate, capture):
    """Return exact per-instance triptych assets; filenames alone cannot prove a pass."""
    reference = capture.get('restoration_probes') or {}
    require(reference.get('state') == 'captured', 'Actual pre-lettering base has not been captured')
    manifest_path = inside(run, reference['manifest'])
    require(file_hash(manifest_path) == reference['sha256'] and
            capture['files'].get(reference['manifest']) == reference['sha256'], 'Restoration manifest changed')
    manifest = read_json(manifest_path)
    require(manifest['binding']['video_sha256'] == candidate['sha256'] and
            manifest['binding']['plan_id'] == candidate['plan_id'] and
            manifest['binding']['inventory_sha256'] == file_hash(run/'analysis/inventory.json'),
            'Restoration evidence belongs to another candidate/input')
    coverage = {}
    for row in manifest['rows']:
        image = inside(manifest_path.parent, row['image'])
        name = image.relative_to(run).as_posix()
        digest = manifest['files'][row['image']]
        require(file_hash(image) == digest and capture['files'].get(name) == digest, 'Restoration strip changed')
        coverage.setdefault(row['id'], set()).add((name, digest))
    return coverage
