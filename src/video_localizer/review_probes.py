"""Small, native-frame whole-scene comparisons; observations stay with the Agent."""
import bisect
import html
from pathlib import Path
from tempfile import TemporaryDirectory

from .common import file_hash, inside, object_hash, read_json, require, write_json

MAX_PAIRS = 12
VERSION = 1


def select_times(inventory, last_pts):
    require(last_pts >= 0, 'Whole-scene evidence needs a decoded timeline')
    choices = []
    def add(timestamp, reason):
        value = round(max(0, min(last_pts, timestamp)), 6)
        existing = next((c for c in choices if c['time'] == value), None)
        if existing:
            existing['reasons'].append(reason)
        else:
            choices.append({'time': value, 'reasons': [reason]})
    add(0, 'opening')
    add(last_pts, 'ending / CTA / matching publisher identity')
    items = inventory.get('text_instances', [])
    # High-risk instances before uniform coverage. Sampling is deliberately bounded;
    # the manifest reports omitted probes instead of pretending exhaustive review.
    ranked = sorted(items, key=lambda i: (not bool(i.get('protected_regions') or i.get('trajectory')
                    or i.get('text_role') in {'title', 'cta'}), i['start'], i['id']))
    for item in ranked[:5]:
        add((item['start'] + item['end']) / 2, 'whole scene around ' + item['id'])
    for fraction in (.25, .5, .75):
        add(last_pts * fraction, 'timeline coverage')
    for shot in inventory.get('shots', [])[1:]:
        add(shot['start'], 'shot boundary ' + shot['id'])
    for item in ranked[5:]:
        add((item['start'] + item['end']) / 2, 'whole scene around ' + item['id'])
    return sorted(choices[:MAX_PAIRS], key=lambda c: c['time']), choices[MAX_PAIRS:]


def _nearest(times, value):
    position = bisect.bisect_left(times, value)
    return min({max(0, position - 1), min(len(times) - 1, position)},
               key=lambda n: (abs(times[n] - value), n))


def generate(run, candidate):
    from .workflow import source_path
    from .visual_audit import _clock, _extract
    original = source_path(run)
    target = inside(run, candidate['path'])
    require(file_hash(target) == candidate['sha256'], 'Whole-scene candidate changed')
    inventory_path = run / 'analysis/inventory.json'
    inventory = read_json(inventory_path)
    binding = {'version': VERSION, 'source_sha256': file_hash(original),
               'video_sha256': candidate['sha256'], 'inventory_sha256': file_hash(inventory_path),
               'plan_id': candidate['plan_id'], 'max_pairs': MAX_PAIRS}
    directory = run / 'review' / candidate['sha256'][:12] / ('whole-scene-' + object_hash(binding)[:16])
    manifest_path = directory / 'manifest.json'
    if manifest_path.exists():
        manifest = read_json(manifest_path)
        require(manifest['binding'] == binding, 'Whole-scene binding changed')
        for name, digest in manifest['files'].items():
            require(file_hash(inside(directory, name)) == digest, 'Whole-scene evidence changed')
        reused = True
    else:
        clocks = {}
        source_times, source_meta = _clock(original, clocks)
        target_times, target_meta = _clock(target, clocks)
        selected, omitted = select_times(inventory, source_times[-1])
        pairs = [{**row, 'source_frame': _nearest(source_times, row['time']),
                  'target_frame': _nearest(target_times, row['time'])} for row in selected]
        directory.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix='.whole-scene-', dir=directory.parent) as temporary:
            staging = Path(temporary) / 'bundle'
            source_frames = _extract(original, [p['source_frame'] for p in pairs],
                [0, 0, source_meta['width'], source_meta['height']], staging / 'source')
            target_frames = _extract(target, [p['target_frame'] for p in pairs],
                [0, 0, target_meta['width'], target_meta['height']], staging / 'target')
            for row in pairs:
                row.update(source_pts=source_times[row['source_frame']], target_pts=target_times[row['target_frame']],
                           source_image=source_frames[row['source_frame']].relative_to(staging).as_posix(),
                           target_image=target_frames[row['target_frame']].relative_to(staging).as_posix(),
                           observation='pending')
            rows = ''.join('<section><p>' + html.escape(str(row['time']) + 's: ' + ', '.join(row['reasons'])) +
                '</p><div><figure><figcaption>原片</figcaption><img src="' + row['source_image'] +
                '"></figure><figure><figcaption>当前成片</figcaption><img src="' + row['target_image'] +
                '"></figure></div></section>' for row in pairs)
            (staging / 'index.html').write_text('<!doctype html><meta charset="utf-8"><title>整幅画面对照</title>'
                '<style>body{background:#171717;color:#eee;font:16px sans-serif}section{border-bottom:1px solid #666}'
                'div{display:flex;gap:12px}figure{width:48%;margin:0}img{max-width:100%;height:auto}</style>'
                '<h1>整幅画面对照：待实际审核</h1><p>看主体、背景、文字风格和片尾；抽帧不能代替完整播放和听审。</p>' + rows,
                encoding='utf-8')
            manifest = {'binding': binding, 'pairs': pairs, 'omitted_probes': omitted,
                        'automatic_pass': False, 'limitation': 'Bounded static probes; no proof of motion, audio or every frame.',
                        'files': {p.relative_to(staging).as_posix(): file_hash(p) for p in sorted(staging.rglob('*')) if p.is_file()}}
            write_json(staging / 'manifest.json', manifest)
            staging.rename(directory)
        reused = False
    return {'manifest': manifest_path.relative_to(run).as_posix(), 'sha256': file_hash(manifest_path),
            'viewer': (directory / 'index.html').relative_to(run).as_posix(), 'pairs': len(manifest['pairs']),
            'omitted_probes': len(manifest['omitted_probes']), 'reused': reused, 'automatic_pass': False}
