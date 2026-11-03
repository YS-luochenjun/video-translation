"""Source-bound, full-frame comparison before reusing a pilot across languages."""
import math

from . import media, workflow
from .common import file_hash, run_operation, inside, object_hash, read_json, require, write_json

CHECKS = ('residue', 'subject', 'lettering', 'timing')


def instances(inventory):
    return [item for item in inventory.get('text_instances', [])
            if item.get('action') not in ('keep', 'preserve') and item.get('text_role') != 'preserve']


def _asset(run, path):
    return {'path': path.relative_to(run).as_posix(), 'sha256': file_hash(path)}


def compare(run, instance_id, video, base=None, base_limit=None):
    with run_operation(run, resume=False):
        return _compare(run, instance_id, video, base, base_limit)


def _compare(run, instance_id, video, base, base_limit):
    require(not (base and base_limit) and (base_limit is None or base_limit.strip()),
            'Provide the actual base or a concrete best-available limitation')
    inv = run / 'analysis/inventory.json'
    item = next((i for i in instances(read_json(inv)) if i['id'] == instance_id), None)
    require(item, 'Select a translated instance from the pilot inventory')
    source = workflow.source_path(run)
    target = inside(run, video)
    paths = [source, inside(run, base), target] if base else [source, target]
    require(len(set(paths)) == len(paths), 'Supply distinct source/base/target paths')
    meta = [media.probe(p) for p in paths]
    original = meta[0]
    frame = 1 / original['fps']
    require(all((m['width'], m['height']) == (original['width'], original['height'])
                and abs(m['duration'] - original['duration']) <= max(frame, .08)
                and abs(m['fps'] - original['fps']) < .01 for m in meta),
            'Comparison requires full-length source-aligned inputs of matching geometry and frame rate')
    start = max(0, item['start'] - .25)
    end = min(original['duration'], item['end'] + .25)
    require(end > start, 'Selected interval is outside the video')
    binding = {'source': _asset(run, source), 'base': _asset(run, paths[1]) if base else None,
               'base_limitation': base_limit, 'target': _asset(run, target), 'instance': instance_id,
               'inventory_sha256': file_hash(inv), 'start': start, 'end': end}
    require(binding['source']['sha256'] == read_json(run / 'run.json')['source_sha256'], 'Pilot source changed')
    pieces = []
    if not base and not base_limit:
        plan = read_json(run/'plan.json')
        segments = (plan.get('restoration_base') or {}).get('segments', [])
        require(segments, 'No registered restoration base; supply --base or explain --base-limit')
        candidate = read_json(run/'outputs/candidate.json')
        require(candidate['plan_id'] == plan['id'] and candidate['sha256'] == binding['target']['sha256'],
                'Registered base belongs to another candidate')
        first, last = math.ceil(start * original['fps']), math.ceil(end * original['fps'])
        last = min(last, segments[-1]['end_frame'])
        for seg in segments:
            lo, hi = max(first, seg['start_frame']), min(last, seg['end_frame'])
            if hi > lo:
                asset = seg['asset']
                require(file_hash(inside(run, asset['path'])) == asset['sha256'], 'Registered base changed')
                offset = seg['asset_start_frame'] + lo - seg['start_frame']
                piece_meta = media.probe(inside(run, asset['path']))
                require((piece_meta['width'], piece_meta['height']) == (original['width'], original['height'])
                        and abs(piece_meta['fps'] - original['fps']) < .01
                        and (offset + hi-lo) * frame <= piece_meta['duration'] + .001,
                        'Registered base segment cannot cover the requested source frames')
                pieces.append({'asset': asset, 'start_frame': offset, 'frames': hi-lo})
        require(pieces and sum(p['frames'] for p in pieces) == last-first, 'Incomplete base coverage')
        binding.update(registered_plan=plan['id'], pieces=pieces)
    folder = run / 'review/pilot-comparisons' / object_hash(binding)
    folder.mkdir(parents=True, exist_ok=True)
    manifest = folder / 'comparison.json'
    if not manifest.exists():
        clip = folder / 'comparison.mp4'
        args = []
        for path in paths:
            args += ['-ss', start, '-i', path]
        inputs = ''.join(f'[{i}:v]' for i in range(len(paths)))
        graph = inputs + f'hstack=inputs={len(paths)}[v]'
        if pieces:
            chains = []
            for i, piece in enumerate(pieces):
                args += ['-i', inside(run, piece['asset']['path'])]
                lo = piece['start_frame']
                chains.append(f'[{i+2}:v]trim=start_frame={lo}:end_frame={lo+piece["frames"]},setpts=PTS-STARTPTS[b{i}]')
            labels = ''.join(f'[b{i}]' for i in range(len(pieces)))
            chains += [labels + f'concat=n={len(pieces)}:v=1:a=0[base]', '[0:v][base][1:v]hstack=inputs=3[v]']
            graph = ';'.join(chains)
        media.ffmpeg([*args, '-t', end-start, '-filter_complex', graph,
                      '-map', '[v]', '-an', '-c:v', 'libx264', '-crf', '16', '-preset', 'veryfast', clip])
        write_json(manifest, {'binding': binding, 'clip': _asset(run, clip)})
    data = read_json(manifest)
    require(data['binding'] == binding and file_hash(inside(run, data['clip']['path'])) == data['clip']['sha256'],
            'Comparison evidence changed')
    return {'comparison': _asset(run, manifest), 'clip': data['clip'], 'interval': [start, end],
            'order': ['source', 'base', 'target'] if base or pieces else ['source', 'target'],
            'next': 'Play the full comparison and fill review/pilot-review.json before batch-approve.',
            'report_template': {'comparison': _asset(run, manifest), 'reviewer': '', 'why_hardest': '',
                                'observations': dict.fromkeys(CHECKS, ''), 'decision': 'pending'}}


def release_check(run, snapshot, best_available):
    inv = run / 'analysis/inventory.json'
    if not instances(read_json(inv)):
        return None
    report = run / 'review/pilot-review.json'
    require(report.is_file(), 'Before expansion run pilot-compare on the hardest visual instance and record review/pilot-review.json')
    data = read_json(report)
    ref = data.get('comparison')
    require(isinstance(ref, dict) and ref.get('path') and ref.get('sha256'), 'Missing comparison manifest reference')
    manifest = inside(run, ref['path'])
    require(file_hash(manifest) == ref['sha256'], 'Pilot comparison manifest changed')
    comparison = read_json(manifest)
    b = comparison['binding']
    require(manifest == run/'review/pilot-comparisons'/object_hash(b)/'comparison.json', 'Invalid comparison binding')
    require(b['inventory_sha256'] == file_hash(inv) and b['target']['sha256'] == snapshot['video_sha256'],
            'Pilot comparison is for a different inventory or video')
    require(b['source']['sha256'] == read_json(run/'run.json')['source_sha256'], 'Pilot comparison source mismatch')
    plan_path = run / 'plan.json'
    candidate_path = run / 'outputs/candidate.json'
    pieces = b.get('pieces', [])
    if pieces:
        require(read_json(plan_path)['id'] == b['registered_plan'], 'Pilot base plan changed')
    if b['base'] and plan_path.exists() and candidate_path.exists():
        plan = read_json(plan_path)
        candidate = read_json(candidate_path)
        if candidate.get('sha256') == b['target']['sha256'] and candidate.get('plan_id') == plan.get('id'):
            segments = (plan.get('restoration_base') or {}).get('segments', [])
            if segments:
                frame_rate = media.probe(inside(run, b['source']['path']))['fps']
                covered = [seg for seg in segments if seg['start_frame'] < b['end'] * frame_rate
                           and seg['end_frame'] > b['start'] * frame_rate]
                require(covered and all(seg['asset']['sha256'] == b['base']['sha256'] and
                                        seg['asset_start_frame'] == seg['start_frame'] for seg in covered),
                        'Comparison base differs from the registered base for this interval')
    for asset in (b['source'], b['target'], b['base'], comparison['clip'], *(piece['asset'] for piece in pieces)):
        if asset:
            require(file_hash(inside(run, asset['path'])) == asset['sha256'], 'Pilot comparison evidence changed')
    fields = [data.get('why_hardest'), data.get('reviewer'), *(data.get('observations', {}).get(k) for k in CHECKS)]
    require(all(isinstance(v, str) and v.strip() for v in fields), 'Describe the actual four observations and why this shot is hardest')
    clear = data.get('decision') == 'clear' and bool(b['base'] or pieces)
    disclosed = (best_available and data.get('decision') == 'best_available'
                 and isinstance(data.get('limitation'), str) and data['limitation'].strip())
    require(clear or disclosed,
            'Repair common defects before expansion, or document bounded best-available limitations on the finalized pilot')
    return file_hash(report)
