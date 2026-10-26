"""Concise human/agent input; expand identifiers, never invent observations or passes."""
from . import visual_audit as audit
from .common import (WorkflowError, file_hash, guarded, inside, object_hash, read_json,
                     require, utc_now, write_json)


def _frames(values, row):
    require(isinstance(values, list), 'Explicit frame numbers or inclusive [start,end] ranges required')
    available = {page['frame']: page['id'] for page in row['pages']}
    selected = set()
    for value in values:
        if type(value) is int:
            numbers = [value]
        else:
            require(isinstance(value, list) and len(value) == 2
                    and all(type(n) is int for n in value), 'Invalid frame range')
            start, end = value
            require(start <= end and end-start <= len(available), 'Invalid or oversized frame range')
            numbers = range(start, end+1)
        require(set(numbers) <= available.keys(), 'Frame is not in this instance evidence')
        selected.update(numbers)
    return [available[n] for n in sorted(selected)]


def _expand(packet, note, row, binding):
    require(isinstance(note, dict), 'One concrete observation per instance required')
    require(isinstance(note.get('source_appearance', {}), dict), 'Source appearance must be an object')
    require(all(isinstance(note.get(key, ''), str) for key in
                ('target_requirements', 'route_limitations', 'playback_observation')), 'Observation text must be a string')
    record = {'binding_id': object_hash(binding), 'instance_id': row['id'],
              'reviewer': packet['reviewer'], 'review_type': packet['review_type'],
              'reviewed_at': utc_now(), 'reviewed_pages': _frames(note.get('reviewed_frames', []), row),
              **{key: note.get(key, {} if key == 'source_appearance' else '') for key in
                 ('source_appearance', 'target_requirements', 'route_limitations', 'playback_observation')},
              'checks': {}}
    keys = audit.CHECKS if binding['stage'] == 'final' else audit.CHECKS[:2]+audit.CHECKS[3:]
    issue = note.get('issue')
    if issue is not None:
        require(isinstance(issue, dict) and issue.get('check') in keys
                and audit._meaningful(issue.get('observation')), 'Issue needs a check and concrete observation')
        cited = _frames(issue.get('frames', []), row)
        require(cited, 'Issue needs observed evidence frames')
        record['reviewed_pages'] = cited
        record['checks'][issue['check']] = {'status': 'fail', 'observation': issue['observation'], 'evidence_pages': cited}
        return record
    checks = note.get('checks', {})
    require(isinstance(checks, dict) and set(checks) <= set(keys), 'Unknown visual check')
    for key, check in checks.items():
        require(isinstance(check, dict) and check.get('status') in ('pass', 'fail', 'pending', 'not_applicable'),
                'Every submitted check needs its own explicit status')
        record['checks'][key] = {'status': check['status'], 'observation': check.get('observation', ''),
                                 'evidence_pages': _frames(check.get('frames', []), row)}
    return record


@guarded
def submit(run, manifest_relative, notes_relative):
    path = inside(run, manifest_relative)
    require(path.name == audit.MANIFEST, 'Select a visual evidence manifest')
    manifest = read_json(path)
    packet = read_json(inside(run, notes_relative))
    require(isinstance(packet, dict) and packet.get('manifest_sha256') == file_hash(path), 'Stale visual notes manifest')
    require(isinstance(packet.get('reviewer'), str) and packet['reviewer'].strip()
            and packet.get('review_type') in ('same_agent', 'independent', 'human'), 'Explicit reviewer attribution required')
    notes = packet.get('instances')
    require(isinstance(notes, list) and notes and all(isinstance(n, dict) for n in notes), 'Individual instance notes required')
    ids = [n.get('instance_id') for n in notes]
    require(all(isinstance(n, str) for n in ids) and len(ids) == len(set(ids)), 'Duplicate or invalid instance IDs')
    rows = {row['id']: row for row in manifest['instances']}
    require(set(ids) <= rows.keys(), 'Unknown visual instance')
    # Validate input first, then hash evidence once for this locked submission.
    records = [_expand(packet, note, rows[note['instance_id']], manifest['binding']) for note in notes]
    audit._verify_files(path.parent, manifest)
    index = read_json(path.parent/'reviews.json')
    results = []
    for record in records:
        identity = record['instance_id']
        relative = 'observations/'+object_hash(record)+'.json'
        destination = inside(path.parent, relative)
        if destination.exists():
            require(read_json(destination) == record, 'Stored immutable observation changed')
        else:
            write_json(destination, record)
        index[identity] = {'path': relative, 'sha256': file_hash(destination)}
        try:
            audit._review_valid(record, rows[identity], manifest['binding'])
            result = {'instance': identity, 'state': 'reviewed'}
        except WorkflowError as exc:
            result = {'instance': identity, 'state': 'pending_or_failed', 'reason': str(exc)}
        results.append(result)
    # Atomic index publication: an interruption leaves old checkpoint + harmless orphan records.
    write_json(path.parent/'reviews.json', index)
    return {'results': results, 'automatic_pass': False,
            'scope': 'Recorded individual observations; release/delivery still verify all evidence and reject duplicated boilerplate'}


@guarded
def pages(run, manifest_relative, instance_id, max_height=1600, layer='all', after_frame=None, limit=None, columns=1):
    """Lossless native-pixel gallery; disposable views are outside the evidence manifest."""
    from PIL import Image, ImageDraw
    path = inside(run, manifest_relative)
    require(path.name == audit.MANIFEST, 'Select a visual evidence manifest')
    manifest = read_json(path)
    row = next((r for r in manifest['instances'] if r['id'] == instance_id), None)
    require(row is not None, 'Unknown visual instance')
    require(type(max_height) is int and 128 <= max_height <= 4096, 'Gallery height must be 128..4096')
    require(type(columns) is int and 1 <= columns <= 4, 'Gallery columns must be 1..4')
    require(limit is None or type(limit) is int and 1 <= limit <= 4, 'Return at most four gallery pages per batch')
    require(after_frame is None or type(after_frame) is int and after_frame >= 0, 'Invalid frame cursor')
    selected = [p for p in row['pages'] if after_frame is None or p['frame'] >= after_frame]
    require(selected, 'Frame cursor is past this instance')
    require(layer == 'all' or all(layer in p['layers'] for p in selected), 'Selected layer is not available')
    identity = object_hash({'run': str(run.resolve()), 'manifest': file_hash(path),
                            'instance': instance_id, 'height': max_height, 'layer': layer,
                            'after': after_frame, 'limit': limit, 'columns': columns, 'version': 3})[:24]
    folder = run.parent.parent/'work/visual-pages'/identity
    index_path = folder/'index.json'
    # Only the selected canonical strips are needed for this view; production gates still hash the full bundle.
    for page in selected:
        source = inside(path.parent, page['id'])
        require(source.is_file() and file_hash(source) == manifest['files'].get(page['id']), 'Visual comparison evidence missing or changed')
    if index_path.exists():
        saved = read_json(index_path)
        if all(inside(folder, p['path']).is_file() and file_hash(inside(folder, p['path'])) == p['sha256'] for p in saved['pages']):
            return {**saved, 'reused': True}
    folder.mkdir(parents=True, exist_ok=True)
    groups, group, height, row_height = [], [], 0, 0
    for page in selected:
        with Image.open(inside(path.parent, page['id'])) as image:
            size = image.size
            if layer != 'all':
                size = (size[0] // len(page['layers']), size[1])
        if len(group) % columns == 0:
            if group and height+size[1]+24 > max_height:
                groups.append(group); group, height = [], 0
            row_height = size[1]+24
            height += row_height
        group.append((page, size))
    if group:
        groups.append(group)
    more = groups[limit:] if limit is not None else []
    groups = groups[:limit] if limit is not None else groups
    output = []
    for number, group in enumerate(groups):
        cell_width = max(size[0] for _, size in group)
        cell_height = max(size[1]+24 for _, size in group)
        image = Image.new('RGB', (cell_width*min(columns,len(group)),
                                 cell_height*((len(group)+columns-1)//columns)), '#777777')
        draw, tiles = ImageDraw.Draw(image), []
        for index, (page, size) in enumerate(group):
            left, top = (index % columns)*cell_width, (index // columns)*cell_height
            draw.text((left+3, top+4), f"frame {page['frame']} PTS {page['pts']:.6f}", fill='white')
            top += 24
            with Image.open(inside(path.parent, page['id'])) as source:
                source = source.convert('RGB')
                if layer != 'all':
                    # Canonical strips use page.layers order, NOT binding.layers order.
                    position = list(page['layers']).index(layer)
                    width = source.width // len(page['layers'])
                    source = source.crop((position*width, 0, (position+1)*width, source.height))
                image.paste(source, (left, top))
            tiles.append({'id': page['id'], 'frame': page['frame'], 'left': left, 'top': top})
        destination = folder/f'{number:04}.png'
        image.save(destination)
        output.append({'path': str(destination.resolve()), 'sha256': file_hash(destination), 'tiles': tiles,
                       'width': image.width, 'height': image.height})
    result = {'instance': instance_id, 'manifest_sha256': file_hash(path), 'layer': layer, 'columns': columns,
              'next_frame': more[0][0][0]['frame'] if more else None,
              'pages': output, 'automatic_pass': False,
              'scope': 'Native pixels, no resizing; inspect at original resolution and play video separately. Frame numbers are not sample ordinals.'}
    write_json(index_path, result)
    progress = run.parent.parent / 'state/review-progress' / run.name / (file_hash(path)[:24]+'.json')
    saved = read_json(progress) if progress.exists() else {}
    saved[instance_id] = {'layer': layer, 'next_frame': result['next_frame'],
                          'presented_frames': [tile['frame'] for page in output for tile in page['tiles']],
                          'status': 'presented_only_not_reviewed'}
    write_json(progress, saved)
    return result
