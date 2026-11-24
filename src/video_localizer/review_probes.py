"""Small, native-frame whole-scene comparisons; observations stay with the Agent."""
import bisect
import html
import os
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from .common import WorkflowError, file_hash, inside, lock, object_hash, read_json, require, write_json

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


def _previous_frames(run, decoder, digests):
    frames = {}
    for path in sorted((run / 'review').glob('*/whole-scene-*/manifest.json')):
        try:
            manifest = read_json(path)
            if manifest.get('frame_decoder') != decoder:
                continue
            for role, field in (('source', 'source_sha256'), ('target', 'video_sha256')):
                digest = manifest['binding'][field]
                if digest not in digests:
                    continue
                for row in manifest['pairs']:
                    relative = row[f'{role}_image']
                    image = inside(path.parent, relative)
                    if image.is_file():
                        frames.setdefault((digest, row[f'{role}_frame']),
                                          (image, manifest['files'][relative]))
        except (OSError, ValueError, WorkflowError, KeyError, TypeError, AttributeError):
            continue
    return frames


def _source_index(run, digest, decoder, region):
    root = run.parent.parent
    binding = run / 'inputs/fireplay.json'
    scope = {'kind': 'local'}
    if binding.exists() or binding.is_symlink():
        try:
            requirement = read_json(binding)['requirement_id']
            if not isinstance(requirement, str) or not requirement:
                return None
        except (OSError, ValueError, KeyError, TypeError):
            return None
        scope = {'kind': 'fireplay', 'requirement_id': requirement}
    key = object_hash({'version': VERSION, 'scope': scope, 'source': digest,
                       'decoder': decoder, 'region': region})
    return root / 'state/visual-decode-cache/whole-scene-source' / f'{key}.json'


def _read_source_index(index):
    try:
        record = read_json(index)
        frames = record['frames']
        if isinstance(frames, dict) and record['sha256'] == object_hash(frames):
            return frames
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return {}


def _shared_frames(root, index, digest, numbers):
    if index is None:
        return {}
    entries = _read_source_index(index)
    frames = {}
    for number in set(numbers):
        try:
            entry = entries[str(number)]
            path = inside(root, entry['path'])
            parts = path.relative_to(root).parts
            if (len(parts) == 7 and parts[0] == 'runs' and parts[2] == 'review'
                    and parts[4].startswith('whole-scene-') and parts[5] == 'source'
                    and path.suffix == '.png'):
                frames[digest, number] = (path, entry['sha256'])
        except (WorkflowError, OSError, ValueError, KeyError, TypeError):
            continue
    return frames


def _publish_source_frames(root, index, directory, source_frames, staging, manifest):
    if index is None:
        return
    entries = {}
    for number, path in source_frames.items():
        relative = path.relative_to(staging)
        entries[str(number)] = {'path': (directory / relative).relative_to(root).as_posix(),
                                'sha256': manifest['files'][relative.as_posix()]}
    try:
        with lock(index.with_suffix('.lock')):
            frames = {**_read_source_index(index), **entries}
            write_json(index, {'frames': frames, 'sha256': object_hash(frames)})
    except (OSError, WorkflowError):
        return


def _reuse_frame(cached, destination):
    source, digest = cached
    try:
        try:
            os.link(source, destination)
        except OSError:
            shutil.copyfile(source, destination)
        if file_hash(destination) == digest:
            return True
    except FileNotFoundError:
        pass
    destination.unlink(missing_ok=True)
    return False


def _frames(movie, digest, numbers, meta, staging, scratch, previous):
    from .visual_audit import _extract
    staging.mkdir(parents=True, exist_ok=True)
    frames, missing = {}, {}
    for position, number in enumerate(sorted(set(numbers)), 1):
        destination = staging / f'{position:06d}.png'
        frames[number] = destination
        cached = previous.get((digest, number))
        if not cached or not _reuse_frame(cached, destination):
            missing[number] = destination
    if missing:
        decoded = _extract(movie, list(missing), [0, 0, meta['width'], meta['height']], scratch)
        for number, image in decoded.items():
            image.rename(missing[number])
    return frames


def generate(run, candidate):
    from .workflow import source_path
    from .visual_audit import _clock
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
        # Source and candidate frame clocks are content-addressed observations,
        # shared with restoration evidence. Reuse their verified decoding only;
        # the per-candidate comparison and review remain independent.
        from .visual_reuse import EvidenceCache
        cache = EvidenceCache(run.parent.parent)
        clocks = {'_reuse': cache}
        decoder = object_hash(cache.engine)
        previous = _previous_frames(run, decoder, {binding['source_sha256'], binding['video_sha256']})
        source_times, source_meta = _clock(original, clocks)
        target_times, target_meta = _clock(target, clocks)
        selected, omitted = select_times(inventory, source_times[-1])
        pairs = [{**row, 'source_frame': _nearest(source_times, row['time']),
                  'target_frame': _nearest(target_times, row['time'])} for row in selected]
        source_numbers = [row['source_frame'] for row in pairs]
        root = run.parent.parent
        index = _source_index(run, binding['source_sha256'], decoder,
                              [0, 0, source_meta['width'], source_meta['height']])
        source_previous = {**_shared_frames(root, index, binding['source_sha256'], source_numbers),
                           **previous}
        directory.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix='.whole-scene-', dir=directory.parent) as temporary:
            scratch = Path(temporary)
            staging = scratch / 'bundle'
            source_frames = _frames(original, binding['source_sha256'], source_numbers,
                                    source_meta, staging / 'source', scratch / 'decode-source', source_previous)
            target_frames = _frames(target, binding['video_sha256'], [p['target_frame'] for p in pairs],
                                    target_meta, staging / 'target', scratch / 'decode-target', previous)
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
            manifest = {'binding': binding, 'pairs': pairs, 'omitted_probes': omitted, 'frame_decoder': decoder,
                        'automatic_pass': False, 'limitation': 'Bounded static probes; no proof of motion, audio or every frame.',
                        'files': {p.relative_to(staging).as_posix(): file_hash(p) for p in sorted(staging.rglob('*')) if p.is_file()}}
            write_json(staging / 'manifest.json', manifest)
            cache.verify_inputs()
            staging.rename(directory)
            _publish_source_frames(root, index, directory, source_frames, staging, manifest)
        reused = False
    return {'manifest': manifest_path.relative_to(run).as_posix(), 'sha256': file_hash(manifest_path),
            'viewer': (directory / 'index.html').relative_to(run).as_posix(), 'pairs': len(manifest['pairs']),
            'omitted_probes': len(manifest['omitted_probes']), 'reused': reused, 'automatic_pass': False}
