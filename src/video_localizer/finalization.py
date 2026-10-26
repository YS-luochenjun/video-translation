"""Deliver a usable translated result without falsely approving its quality."""
import shutil
import json

from .common import file_hash, guarded, inside, object_hash, read_json, require, utc_now, write_json
from . import media


@guarded
def compose(run):
    """Compose existing per-shot plates/layers even when cosmetic review failed.

    Codex supplies translated layers. This function never invents translations,
    calls a model, or upgrades an unapproved plate to a reusable master.
    """
    from .workflow import source_path
    source = source_path(run)
    inv = read_json(run / 'analysis/inventory.json')
    meta = media.probe(source)
    counted = json.loads(media.command(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0',
        '-show_entries', 'stream=nb_read_frames', '-of', 'json', source]).stdout)
    total = int(counted['streams'][0]['nb_read_frames'])
    folder = run / 'outputs/best-available'
    folder.mkdir(parents=True, exist_ok=True)
    assets, clips, cursor = [], [], 0
    def asset(path):
        return {'path': path.relative_to(run).as_posix(), 'sha256': file_hash(path)}
    for n, shot in enumerate(inv['shots']):
        first = round(shot['start'] * meta['fps'])
        last = min(total, round(shot['end'] * meta['fps']))
        require(first == cursor and last > first, 'Best composition needs contiguous source-frame coverage')
        cursor = last
        plate = shot.get('prepared_video')
        layer = shot.get('surface_typography')
        require(layer, 'Codex must prepare an actual translated transparent layer for each shot')
        for item in [x for x in (plate, layer) if x]:
            require(file_hash(inside(run, item['path'])) == item['sha256'], 'Composition asset changed')
            assets.append({'path': item['path'], 'sha256': item['sha256']})
        base = inside(run, plate['path']) if plate else source
        for path in (base, inside(run, layer['path'])):
            current = media.probe(path)
            require((current['width'], current['height']) == (meta['width'], meta['height'])
                    and abs(current['fps'] - meta['fps']) < .001,
                    'Normalize existing assets to source dimensions/frame timing before composition')
        start = 0 if plate else first
        out = folder / f'shot-{n:03d}.mp4'
        graph = (f'[0:v]trim=start_frame={start}:end_frame={start+last-first},setpts=PTS-STARTPTS[b];'
                 '[1:v]setpts=PTS-STARTPTS[t];[b][t]overlay=0:0:shortest=1:format=auto,format=yuv420p[v]')
        media.ffmpeg(['-i', base, '-i', inside(run, layer['path']), '-filter_complex', graph,
                      '-map', '[v]', '-an', '-c:v', 'libx264', '-crf', '18', '-preset', 'fast', out])
        count = json.loads(media.command(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0',
            '-show_entries', 'stream=nb_read_frames', '-of', 'json', out]).stdout)
        require(int(count['streams'][0]['nb_read_frames']) == last-first, 'Prepared layer/plate does not cover the shot')
        clips.append(out)
    require(cursor == total, 'Best composition does not cover the full video')
    listing = folder / 'concat.txt'
    listing.write_text('\n'.join("file '" + p.name + "'" for p in clips), encoding='utf-8')
    track = inv.get('audio', {}).get('replacement_path')
    soundtrack = inside(run, track) if track else source
    assets.append(asset(soundtrack))
    output = run / 'outputs/translated-best.mp4'
    media.ffmpeg(['-f', 'concat', '-safe', '0', '-i', listing, '-i', soundtrack,
                  '-map', '0:v:0', '-map', '1:a:0?', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
                  '-t', meta['duration'], '-movflags', '+faststart', output])
    recipe = {'source_sha256': file_hash(source), 'inventory_sha256': file_hash(run / 'analysis/inventory.json'),
              'assets': assets, 'output': asset(output), 'quality_passed': False, 'frames': total}
    write_json(folder / 'recipe.json', recipe)
    template = {'source_sha256': recipe['source_sha256'], 'inventory_sha256': recipe['inventory_sha256'],
                'request_sha256': file_hash(run / 'inputs/request.json'), 'video': recipe['output'],
                'reviewer': '', 'reason': '',
                'text_ids': [t['id'] for t in inv.get('text_instances', []) if t.get('action') != 'preserve'],
                'speech_ids': [s['id'] for s in inv.get('speech_segments', []) if s.get('action') != 'preserve'],
                'speech_mode': 'dubbed' if track else 'subtitled' if inv.get('speech_segments') else 'no_speech',
                'evidence': [], 'assets': [asset(folder / 'recipe.json'), *assets], 'limitations': []}
    write_json(run / 'review/finalization-template.json', template)
    return {'state': 'needs_finalization_review', 'video': recipe['output'],
            'recipe': 'outputs/best-available/recipe.json', 'template': 'review/finalization-template.json',
            'next_action': 'Observe the encoded translation coverage; complete review/finalization.json and finalize.',
            'new_paid_tasks': 0}


def validate_completion(run, spec):
    from .workflow import source_path
    require(spec['source_sha256'] == file_hash(source_path(run)), 'Finalization source changed')
    require(spec['inventory_sha256'] == file_hash(run / 'analysis/inventory.json'), 'Finalization inventory changed')
    require(spec['request_sha256'] == file_hash(run / 'inputs/request.json'), 'Finalization request changed')
    inv = read_json(run / 'analysis/inventory.json')
    require(spec.get('reviewer') and spec.get('reason'), 'Explain the selected result and reviewer')
    for field, collection in [('text_ids', 'text_instances'), ('speech_ids', 'speech_segments')]:
        expected = {x['id'] for x in inv.get(collection, []) if x.get('action') != 'preserve'}
        require(set(spec.get(field, [])) == expected, 'Finalization translation coverage incomplete: ' + field)
    require(spec.get('speech_mode') in ('dubbed', 'subtitled', 'no_speech'), 'Explain actual speech translation mode')
    require(not spec.get('speech_ids') or spec['speech_mode'] != 'no_speech', 'Source speech needs translation')
    request = read_json(run / 'inputs/request.json')
    if request.get('routing_contract_version', 0) >= 1:
        from .routing import validate as validate_routing
        validate_routing(inv, request, run)
    require(not request.get('require_target_audio') or not spec.get('speech_ids')
            or spec['speech_mode'] == 'dubbed',
            'Target audio is required; subtitles cannot complete this request. Report the audio blocker.')
    require(isinstance(spec.get('limitations'), list) and spec['limitations'], 'Disclose unresolved quality/review limits')
    require(spec.get('evidence'), 'Use actual encoded-result evidence')
    for asset in [spec['video'], *spec['evidence'], *spec.get('assets', [])]:
        require(file_hash(inside(run, asset['path'])) == asset['sha256'], 'Finalization asset changed')
    return inside(run, spec['video']['path'])


@guarded
def finish(run, relative='review/finalization.json'):
    """Explicit output completion; scores and quality holds remain historical facts."""
    root = run.parent.parent
    require(read_json(root / 'config/workspace.json').get('output_policy') == 'best_available_required',
            'Best-available output is not selected by this workspace')
    spec_path = inside(run, relative)
    spec = read_json(spec_path)
    video = validate_completion(run, spec)
    prior_path = run / 'outputs/completion.json'
    if prior_path.exists() and (run / 'outputs/final.mp4').exists():
        prior = read_json(prior_path)
        if (prior.get('spec_sha256') == file_hash(spec_path)
                and prior.get('video_sha256') == file_hash(run / 'outputs/final.mp4')):
            from .library import find
            matches = [p for p in find(spec['source_sha256'], root=root)
                       if p['video_sha256'] == prior['video_sha256'] and p['availability'] == 'available'
                       and p['status'] == 'delivered_with_issues' and p['origin_run_id'] == run.name]
            if matches:
                return {'state': 'delivered_with_issues', 'final': matches[-1]['package'] + '/final.mp4',
                        'sha256': prior['video_sha256'], 'limitations': prior['limitations'],
                        'quality_passed': False, 'reused': True, 'new_paid_tasks': 0}
    from .workflow import source_path
    original, actual = media.probe(source_path(run)), media.probe(video)
    require(abs(original['duration'] - actual['duration']) <= .25, 'Complete the full source timeline before finalizing')
    require((original['width'], original['height']) == (actual['width'], actual['height']), 'Finalization dimensions changed')
    require(abs(original['fps'] - actual['fps']) < .001, 'Restore source frame rate before finalizing')
    require(not original['has_audio'] or actual['has_audio'], 'Restore the soundtrack before finalizing')
    require(spec['speech_mode'] != 'dubbed' or actual['has_audio'], 'Dubbed output needs an actual audio stream')
    media.command(['ffmpeg', '-v', 'error', '-xerror', '-i', video, '-f', 'null', '-'])
    output = run / 'outputs/final.mp4'
    output.parent.mkdir(parents=True, exist_ok=True)
    digest = file_hash(video)
    selection_asset = None
    request = read_json(run / 'inputs/request.json')
    if request.get('routing_contract_version', 0) >= 1:
        from .knowledge import context_for, retrieve, source_references
        from .knowledge_advisories import retrieve as advisories
        from .routing import validate as validate_routing
        from .fast_delivery import _freeze_knowledge
        inventory = read_json(run / 'analysis/inventory.json')
        context = context_for(request, inventory, root)
        knowledge = retrieve(context, root=root)
        references = source_references(context, root=root)
        selection = {'scope': 'finalization_selection_only', 'source_sha256': spec['source_sha256'],
                     'request_sha256': spec['request_sha256'], 'inventory_sha256': spec['inventory_sha256'],
                     'video_sha256': digest, 'knowledge_context': context,
                     'knowledge': knowledge, 'source_references': references,
                     'knowledge_advisories': advisories(context, root),
                     'routing_assessment': validate_routing(inventory, request, run, knowledge + references, original['duration'])}
        selection['id'] = object_hash(selection)[:16]
        _freeze_knowledge(run, selection)
        path = run / 'plans' / selection['id'] / 'plan.json'
        selection_asset = {'path': path.relative_to(run).as_posix(), 'sha256': file_hash(path)}
    if video.resolve() != output.resolve() and not (output.exists() and video.samefile(output)):
        shutil.copyfile(video, output)
    write_json(run / 'outputs/completion.json', {
        'state': 'delivered_with_issues', 'video_sha256': digest,
        'source_sha256': spec['source_sha256'], 'inventory_sha256': spec['inventory_sha256'],
        'request_sha256': spec['request_sha256'],
        'spec': relative, 'spec_sha256': file_hash(spec_path), 'reviewer': spec['reviewer'],
        'speech_mode': spec['speech_mode'], 'limitations': spec['limitations'],
        'knowledge_selection': selection_asset,
        'decode_passed': True, 'quality_passed': False, 'user_acceptance': False,
        'completed_at': utc_now()})
    write_json(run / 'outputs/delivery.json', {
        'video': 'outputs/final.mp4', 'sha256': digest, 'scope': 'best_available',
        'completion_record': 'outputs/completion.json',
        'completion_sha256': file_hash(run / 'outputs/completion.json'), 'delivered_at': utc_now()})
    write_json(run / 'outputs/reuse-assets.json', {
        'source_sha256': spec['source_sha256'],
        'assets': [{'path': relative, 'sha256': file_hash(spec_path)}, *spec.get('assets', [])]})
    from .library import export
    package = export(run, root=root)
    from .delivery_index import refresh
    refresh(root)
    write_json(root / 'state/deferred-delivery' / (run.name + '.json'), {
        'run': run.name, 'video_sha256': digest, 'status': 'pending',
        'tasks': ['reflect', 'source-save'], 'created_at': utc_now()})
    return {'state': 'delivered_with_issues', 'final': package['package'] + '/final.mp4',
            'sha256': digest, 'limitations': spec['limitations'], 'quality_passed': False,
            'package': package, 'new_paid_tasks': 0}
