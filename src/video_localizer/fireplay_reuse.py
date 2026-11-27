"""Host-mediated discovery and publication evidence for existing Fireplay translations."""
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import md5
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from urllib.error import URLError
from urllib.parse import urlsplit

from . import bundles, delivery_layout, fireplay, languages, media
from .common import ROOT, WorkflowError, file_hash, inside, lock, object_hash, read_json, require, utc_now, write_json
from .fireplay_publication import publication_decision, require_clear


PACKAGE_KIND = 'fireplay_translation_reuse'
OBSERVATIONS = ('same_original_version', 'target_language', 'complete_translation',
                'required_voice_and_audio', 'specifications_and_watchability')


def is_linked_rework(record):
    if record.get('repair_continuity'):
        return True
    brief = record.get('snapshot', {}).get('brief', {})
    title = (brief.get('title') or '').strip()
    description = brief.get('description') or ''
    return title.startswith(('【驳回返工】', '[驳回返工]')) or bool(re.search(
        r'(?m)^[ \t]*基于原需求[ \t]+[A-Z0-9]+-\d{8}-\d+[^\r\n]*驳回返工[。.]?[ \t\r]*$',
        description))


def _require_reuse_allowed(record):
    require(not is_linked_rework(record), 'Linked rework cannot submit an unchanged historical video')


def _scope(record, video):
    require(video.get('source'), 'Confirm and hash the current original before looking for history')
    return {'requirement_id': record['requirement_id'], 'content_version': record['content_version'],
            'video_index': video['index'], 'source_sha256': video['source']['sha256']}


def _state(code, scope, root):
    return fireplay._folder(code, root) / 'historical-translations' / object_hash(scope)


def _fresh(response):
    try:
        observed = datetime.fromisoformat(response['serverTime'].replace('Z', '+00:00'))
        age = (datetime.now(timezone.utc) - observed).total_seconds()
    except (KeyError, TypeError, ValueError, AttributeError):
        age = float('inf')
    require(-60 <= age <= 600, 'Historical discovery requires a fresh requirement read')


def _queries(video, material_usage=None):
    queries = {}
    video_id = video.get('youtube_video_id')
    material_id = (video.get('resolved') or {}).get('material_id')
    material_ids = {material_id} if fireplay._uuid(material_id) else set()
    if material_usage is not None:
        require(video_id, 'Exact YouTube material lookup needs the current video ID')
        items = [row for row in fireplay.payload(material_usage).get('items', [])
                 if row.get('videoId') == video_id]
        require(len(items) == 1, 'Material lookup must include the exact YouTube ID')
        records = items[0].get('materialRecords', [])
        require(items[0].get('materialCount') == len(records),
                'Material lookup returned an incomplete set of records')
        for material in records:
            require(fireplay._uuid(material.get('materialId'))
                    and fireplay.youtube_id(material.get('resourceUrl') or '') == video_id,
                    'Material lookup returned a record for a different YouTube video')
            material_ids.add(material['materialId'])
    if material_ids:
        queries['material'] = {'material_ids': sorted(material_ids)}
    if video_id:
        queries['youtube'] = {'youtube_urls': [f'https://youtu.be/{video_id}']}
        queries['keyword'] = {'keyword': video_id}
    return {kind: {'scope': 'all', 'view': 'summary', 'asset_type': 'video', 'limit': 20, **args}
            for kind, args in queries.items()}


def _tags(values, root):
    result = set()
    for value in values:
        if isinstance(value, str) and value.strip():
            try:
                result.add(languages.resolve(value.strip().lower(), root)['target_language'])
            except WorkflowError:
                continue
    return result


def _candidates(record, video, trace, queries, root):
    hits = {}
    incomplete = list(queries.keys() - trace.get('searches', {}).keys())
    for kind, entry in trace.get('searches', {}).items():
        require(kind in queries and entry.get('arguments') == queries[kind],
                'Search receipt does not match this original and its supported lookup arguments')
        if entry.get('error'):
            incomplete.append(kind)
            continue
        response = fireplay.payload(entry['response'])
        _fresh(response)
        meta = response.get('query_meta', {})
        filters = meta.get('filters_applied', {})
        field = {'youtube': 'youtube_video_ids', 'material': 'material_ids', 'keyword': 'keyword'}[kind]
        expected = [video['youtube_video_id']] if kind == 'youtube' else queries[kind][field]
        require(response.get('view') == 'summary' and filters.get(field) == expected,
                'Search response does not echo the exact source filter')
        if (response.get('next_offset') is not None or response.get('next_cursor')
                or meta.get('source_limit_reached') or meta.get('total_exact') is False):
            incomplete.append(kind)
        for row in response.get('items', []):
            if row.get('id') == record['requirement_id'] or not fireplay._uuid(row.get('id')):
                continue
            relations = [] if kind == 'keyword' else row.get('matched_relations', [])
            if kind == 'keyword' or set(relations).intersection({'source', 'reference', 'delivery'}):
                hits.setdefault(row['id'], {})[kind] = relations
    candidates, historical_deliveries, selection, read = [], [], [], set()
    unverified_delivery_ids, rejected_requirements = set(), []
    for raw in trace.get('deliveries', []):
        response = fireplay.payload(raw)
        _fresh(response)
        require(response.get('view') == 'delivery', 'Use the delivery view to inspect historical materials')
        for row in response.get('items', []):
            require(row.get('id') in hits and row['id'] not in read,
                    'Delivery rows must be unique and come from the source search')
            read.add(row['id'])
            if row.get('materialSelection', {}).get('status') == 'waiting_selection':
                selection.append({'requirement_id': row['id'], **row['materialSelection']})
                continue
            original_links = fireplay._text_sources(row, ('description', 'refText', 'title'))
            rejected = row.get('status') in {'rejected', 'ai_rejected'}
            if rejected:
                rejected_requirements.append({'requirement_id': row['id'], 'requirement_code': row['code'],
                                              'status': row['status']})
            video_id = video.get('youtube_video_id')
            relations_by_query = hits[row['id']]
            has_source_relation = any('source' in relations for relations in relations_by_query.values())
            has_exact_link = video_id and any(link.get('youtube_video_id') == video_id for link in original_links)
            has_brief_hit = 'keyword' in relations_by_query or any(
                'reference' in relations for relations in relations_by_query.values())
            eligible_for_candidate_search = has_source_relation or (has_exact_link and has_brief_hit)
            matched_delivery = any('delivery' in relations for relations in relations_by_query.values())
            if matched_delivery:
                unverified_delivery_ids.add(row['id'])
            matched_material_ids = queries.get('material', {}).get('material_ids', [])
            fireplay._code(row['code'])
            for material in row.get('materials', []):
                if material.get('type') != 'video' or not fireplay._uuid(material.get('id')):
                    continue
                delivery_video_id = fireplay.youtube_id(material.get('videoUrl') or '')
                same_youtube_video = bool(video_id and delivery_video_id == video_id)
                same_material = ('delivery' in relations_by_query.get('material', [])
                                 and material['id'] in matched_material_ids
                                 and (not delivery_video_id or not video_id or same_youtube_video))
                if matched_delivery and (same_youtube_video or same_material):
                    unverified_delivery_ids.discard(row['id'])
                    historical_deliveries.append({
                        'requirement_id': row['id'], 'requirement_code': row['code'],
                        'material_id': material['id'], 'youtube_video_id': delivery_video_id,
                        'tags': material.get('tagNames', []),
                        'requirement_status': row.get('status'),
                        'brief_source_links': [link for link in original_links
                                               if not video_id or link.get('youtube_video_id') != video_id],
                    })
                if rejected or not eligible_for_candidate_search:
                    continue
                tags = _tags(material.get('tagNames', []), root)
                matched = [locale for locale in video['targets'] if locale in tags]
                candidate = {'old_requirement_id': row['id'], 'old_requirement_code': row['code'],
                             'material_id': material['id'], 'name': material.get('name'),
                             'locales_from_tags': matched, 'tags': material.get('tagNames', []),
                             'relations': hits[row['id']], 'historical_brief': {
                                 key: row.get(key) for key in ('title', 'description', 'refText', 'attachments')}}
                candidates.append({'id': object_hash(candidate), **candidate})
    original_candidates = []
    for delivery in historical_deliveries:
        if delivery['requirement_status'] in {'rejected', 'ai_rejected'}:
            continue
        for link in delivery['brief_source_links']:
            original_id = link['youtube_video_id']
            if not original_id or original_id == delivery['youtube_video_id']:
                continue
            candidate = {'origin': 'upstream_original', 'old_requirement_id': delivery['requirement_id'],
                         'old_requirement_code': delivery['requirement_code'],
                         'input_material_id': delivery['material_id'], 'source_youtube_id': original_id,
                         'source_url': link['source_url'],
                         'material_lookup': {'tool': 'material_query_youtube_usage',
                                             'arguments': {'urls': [link['source_url']]}}}
            original_candidates.append({'id': object_hash(candidate), **candidate})
    candidates.sort(key=lambda candidate: (not bool(candidate['locales_from_tags']),
                                          candidate['old_requirement_code'], candidate['material_id']))
    return {'candidates': candidates, 'historical_deliveries': historical_deliveries,
            'original_candidates': original_candidates,
            'unread_requirement_ids': sorted(hits.keys() - read),
            'unverified_delivery_requirement_ids': sorted(unverified_delivery_ids),
            'failed_or_truncated_searches': sorted(set(incomplete)),
            'platform_selection': selection, 'rejected_requirements': rejected_requirements}


def search(code, spec=None, index=1, root=ROOT):
    record = fireplay._record(code, root)
    if is_linked_rework(record):
        return {'requirement_id': record['requirement_id'], 'content_version': record['content_version'],
                'video_index': index, 'state': 'skipped_linked_rework', 'queries': {},
                'next': 'Repair the requested versions from the rejection reasons and selected materials'}
    video = fireplay._video(record, index)
    scope = _scope(record, video)
    trace = fireplay.payload(spec) if spec is not None else {}
    queries = _queries(video, trace.get('material_usage'))
    result = {**scope, 'targets': video['targets'], 'tool': 'requirement_list', 'queries': queries,
              'state': 'search_ready' if queries else 'no_search_identity'}
    if video.get('youtube_video_id'):
        result['material_usage_query'] = {'tool': 'material_query_youtube_usage',
                                          'arguments': {'urls': queries['youtube']['youtube_urls']}}
    if spec is None or (trace.get('material_usage') is not None and 'searches' not in trace):
        return result
    require(trace.get('searches'), 'Record at least one actual lookup response or error')
    report = _candidates(record, video, trace, queries, root)
    folder = _state(code, scope, root)
    digest = object_hash(trace)
    write_json(folder / f'{digest}.json', {'scope': scope, 'trace': trace, 'report': report})
    unresolved = any(report[key] for key in ('unread_requirement_ids', 'unverified_delivery_requirement_ids',
                                             'failed_or_truncated_searches', 'platform_selection'))
    state = ('historical_delivery_found' if report['historical_deliveries'] else
             'candidates' if report['candidates'] else
             'lookup_incomplete' if unresolved else
             'rejected_history_only' if report['rejected_requirements'] else 'no_visible_match')
    return {**result, **report, 'state': state, 'search_sha256': digest}


def _digest(value):
    require(isinstance(value, str) and len(value) == 64 and set(value) <= set('0123456789abcdef'),
            'Expected a recorded SHA256')
    return value


def _is_storage_mp4(url):
    parsed = urlsplit(url)
    return (parsed.scheme == 'https' and parsed.netloc == fireplay.ATTACHMENT_HOST
            and parsed.path.startswith('/materials/') and parsed.path.endswith('.mp4'))


def _resource(detail, material_id):
    material = fireplay.payload(detail).get('material', {})
    access = material.get('access') or material
    require(material.get('id') == material_id and material.get('type') == 'video'
            and access.get('canUse') is True and material.get('status') in {'available', 'deployed'}
            and not material.get('isInfringed') and not material.get('deletedAt'),
            'Historical material is unavailable or current caller cannot use it')
    resource_id = material.get('currentVideoResourceId') or material.get('videoResourceId')
    rows = [row for row in material.get('resources', []) if row.get('id') == resource_id]
    require(fireplay._uuid(resource_id) and len(rows) == 1, 'No exact current video resource')
    resource = rows[0]
    url = resource.get('backupUrl') or resource.get('url') or ''
    require(_is_storage_mp4(url) and material.get('videoR2Url') == url and resource.get('mimeType') == 'video/mp4'
            and resource.get('status') == 'normal' and resource.get('storageStatus') == 'r2',
            'Historical material requires the current Fireplay R2 MP4')
    checksum = resource.get('md5')
    require((type(resource.get('fileSize')) is int and resource['fileSize'] > 0) or checksum,
            'Historical resource needs byte identity evidence')
    ingest = (resource.get('extraInfo') or {}).get('youtubeUpload', {}).get('sourceUrl') or ''
    return {key: resource.get(key) for key in ('id', 'fileSize', 'md5', 'duration')} | {
        'url': url, 'ingest_url': ingest if checksum and ingest != url and _is_storage_mp4(ingest) else None}


def _download_resource(resource, movie):
    from .kie import download

    failures = []
    for url in (resource.get('ingest_url'), resource['url']):
        if not url:
            continue
        try:
            download(url, movie, fixed_https_origin=fireplay.ATTACHMENT_HOST)
            size = movie.stat().st_size
            if resource['md5']:
                digest = md5(usedforsecurity=False)
                with movie.open('rb') as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(chunk)
                checksum = digest.hexdigest()
                require(checksum == resource['md5'].lower(), 'Historical MP4 does not match resource MD5')
                return {'url': url, 'bytes': size, 'md5': checksum, 'verified_by': 'md5'}
            require(size == resource['fileSize'], 'Historical MP4 does not match resource size')
            return {'url': url, 'bytes': size, 'verified_by': 'fileSize'}
        except (WorkflowError, URLError) as error:
            failures.append(str(error))
            movie.unlink(missing_ok=True)
    raise WorkflowError('; '.join(failures))


def _bind_upstream_original(candidate, detail):
    material = detail.get('material', {})
    material_id = material.get('id')
    require(fireplay._uuid(material_id) and material_id != candidate['input_material_id'],
            'Select the upstream original material, not the supplied translation')
    resource_id = material.get('currentVideoResourceId') or material.get('videoResourceId')
    resource = next((row for row in material.get('resources', []) if row.get('id') == resource_id), {})
    video_ids = {value for value in (
        resource.get('youtubeVideoId'),
        fireplay.youtube_id(resource.get('url') or ''),
        fireplay.youtube_id(material.get('currentVideoUrl') or material.get('videoUrl') or ''),
    ) if value}
    require(video_ids == {candidate['source_youtube_id']},
            'Current video resource does not match the upstream YouTube ID')
    return {**candidate, 'material_id': material_id,
            'tags': [tag.get('name') for tag in material.get('tags', []) if isinstance(tag, dict)]}


def _capture_ends(video, label, folder, metadata):
    evidence = {}
    for edge, start in (('head', 0), ('tail', max(0, metadata['duration'] - 3))):
        still = folder / f'{label}-{edge}.jpg'
        media.ffmpeg(['-ss', str(min(start + 0.1, metadata['duration'] / 2) if edge == 'head' else start),
                      '-i', video, '-map', '0:v:0', '-frames:v', '1', still])
        evidence[still.name] = file_hash(still)
        if metadata['has_audio']:
            audio = folder / f'{label}-{edge}.wav'
            media.ffmpeg(['-ss', str(start), '-i', video, '-map', '0:a:0', '-t', '3', audio])
            evidence[audio.name] = file_hash(audio)
    return evidence


@contextmanager
def _scratch_operation(root, folder):
    with lock(inside(root, f'runs/.locks/{folder.name}.lock')):
        require(not inside(root, 'state/project-storage.lock').exists(),
                'Project storage maintenance is active; resume after its receipt completes')
        yield


def capture(code, spec, index=1, root=ROOT):
    spec = fireplay.payload(spec)
    record = fireplay._record(code, root)
    _require_reuse_allowed(record)
    video = fireplay._video(record, index)
    scope = _scope(record, video)
    state = _state(code, scope, root)
    trace = read_json(state / f"{_digest(spec['search_sha256'])}.json")
    require(trace['scope'] == scope and object_hash(trace['trace']) == spec['search_sha256'],
            'Historical search receipt changed')
    report = trace['report']
    candidates = [row for row in (*report['candidates'], *report.get('original_candidates', []))
                  if row['id'] == spec['candidate_id']]
    require(len(candidates) == 1, 'Select an exact historical candidate')
    candidate = candidates[0]
    require(candidate['id'] == object_hash({key: value for key, value in candidate.items() if key != 'id'}),
            'Historical candidate evidence changed')
    detail = fireplay.payload(spec['material_detail'])
    if candidate.get('origin') == 'upstream_original':
        candidate = _bind_upstream_original(candidate, detail)
    resource = _resource(detail, candidate['material_id'])
    capture_key = {'scope': scope, 'candidate_id': candidate['id'], 'resource': resource}
    if candidate.get('origin') == 'upstream_original':
        capture_key['material_id'] = candidate['material_id']
    capture_id = object_hash(capture_key)
    folder = inside(Path(root) / 'work/runs', f"{video['title']}-historical-{capture_id[:16]}")
    original = inside(root, video['source']['path'])
    require(file_hash(original) == scope['source_sha256'], 'Current original changed before comparison')
    with _scratch_operation(root, folder):
        marker = folder / 'capture.json'
        if marker.exists():
            value = read_json(marker)
            _verify_capture(value, folder, scope)
            return _capture_result(value, marker, root)
        scratch = inside(root, f'state/maintenance/{folder.name}/scratch.json')
        write_json(scratch, {'files': {}, 'owner': scope, 'rebuild': 'Capture the exact authorized historical material again'})
        folder.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=folder) as temporary:
            temporary = Path(temporary)
            movie = temporary / 'final.mp4'
            byte_identity = _download_resource(resource, movie)
            metadata = media.probe(movie)
            if resource['duration']:
                require(abs(metadata['duration'] - resource['duration']) < 1,
                        'Historical MP4 does not match resource duration')
            media.command(['ffmpeg', '-v', 'error', '-xerror', '-i', movie, '-map', '0:v:0',
                           '-map', '0:a?', '-f', 'null', '-'])
            evidence = _capture_ends(original, 'source', temporary, media.probe(original))
            evidence.update(_capture_ends(movie, 'delivery', temporary, metadata))
            video_digest = file_hash(movie)
            require_clear(code, scope['source_sha256'], video_digest, root)
            require_clear(candidate['old_requirement_code'], scope['source_sha256'], video_digest, root)
            value = {'id': capture_id, 'scope': scope, 'candidate': candidate, 'resource': resource,
                     'byte_identity': byte_identity,
                     'video_sha256': video_digest, 'metadata': {key: metadata[key] for key in
                                                              ('duration', 'width', 'height', 'has_audio')},
                     'decode_passed': True, 'evidence': evidence, 'captured_at': utc_now()}
            for asset in ('final.mp4', *evidence):
                (temporary / asset).replace(folder / asset)
            write_json(folder / 'material-detail.json', detail)
            value['material_detail_sha256'] = file_hash(folder / 'material-detail.json')
            write_json(marker, value)
        return _capture_result(value, marker, root)


def _capture_result(value, marker, root):
    return {**value, 'capture': marker.relative_to(root).as_posix(),
            'video': (marker.parent / 'final.mp4').relative_to(root).as_posix()}


def _verify_capture(value, folder, scope):
    require(value['scope'] == scope and value['decode_passed'] is True
            and file_hash(folder / 'final.mp4') == value['video_sha256']
            and file_hash(folder / 'material-detail.json') == value['material_detail_sha256']
            and all(file_hash(inside(folder, name)) == digest for name, digest in value['evidence'].items()),
            'Historical capture, evidence or original scope changed')


def _review(spec, captured, video, root):
    locale = spec['locale']
    require(locale in video['targets'] and spec.get('video_sha256') == captured['video_sha256'],
            'Review needs this actual candidate hash and current target locale')
    require(isinstance(spec.get('reviewer'), str) and spec['reviewer'].strip(),
            'Attribute the actual visual and audio reviewer')
    checks = spec.get('observations', {})
    require(all(isinstance(checks.get(key), str) and checks[key].strip() for key in OBSERVATIONS),
            'Record actual original/version, language, translation, audio and specification observations')
    edges = spec.get('head_tail_audio', {})
    for edge in ('head', 'tail'):
        observation = edges.get(edge, {})
        require(observation.get('decision') == 'pass'
                and all(isinstance(observation.get(key), str) and observation[key].strip()
                        for key in ('original', 'delivery', 'original_language_residue', 'target_speech_completeness')),
                'Record both actual audio edges, source-language residue and target speech completeness')
    require(type(spec.get('target_voice_needed')) is bool and
            (not spec['target_voice_needed'] or captured['metadata']['has_audio']),
            'A required target voice needs actual decoded audio')
    require(spec.get('decision') == 'eligible', 'Only current, actually reviewed eligible historical videos can be reused')
    require(spec.get('target_language_observed') == locale, 'Actual language must match the requested locale')
    tags = _tags(captured['candidate']['tags'], root) & set(video['targets'])
    if tags != {locale}:
        require(isinstance(spec.get('language_tag_resolution'), str) and spec['language_tag_resolution'].strip(),
                'Explain the missing or conflicting language tags using the actual content')
    return {'locale': locale, 'video_sha256': spec['video_sha256'], 'reviewer': spec['reviewer'],
            'observations': {key: checks[key] for key in OBSERVATIONS}, 'head_tail_audio': edges,
            'target_voice_needed': spec['target_voice_needed'], 'target_language_observed': locale,
            'language_tag_resolution': spec.get('language_tag_resolution'),
            **({'clear_audio_decision': 'pass'} if spec.get('clear_audio_decision') == 'pass' else {}),
            'decision': 'eligible'}


def package(code, spec, index=1, root=ROOT):
    from .library import register_package

    spec = fireplay.payload(spec)
    record = fireplay._record(code, root)
    _require_reuse_allowed(record)
    video = fireplay._video(record, index)
    scope = _scope(record, video)
    marker = inside(root, spec['capture'])
    require(marker.name == 'capture.json' and marker.is_relative_to(inside(root, 'work/runs')),
            'Use the recorded local capture in work/runs')
    captured = read_json(marker)
    folder = marker.parent
    with _scratch_operation(root, folder):
        _verify_capture(captured, folder, scope)
        review = _review(spec, captured, video, root)
        video_digest = captured['video_sha256']
        require_clear(code, scope['source_sha256'], video_digest, root)
        require_clear(captured['candidate']['old_requirement_code'], scope['source_sha256'], video_digest, root)
        version = object_hash({'capture': captured['id'], 'review': review})
        review_path = folder / f'{version}-review.json'
        write_json(review_path, review)
        policy = delivery_layout.settings(root)
        managed = policy.get('enabled', False)
        package_root = policy['package_root'] if managed else 'outputs'
        output = inside(root, f"{package_root}/{code}/{review['locale']}/reuse-{version[:16]}")
        existed = (output / 'manifest.json').exists()
        sources = {'final.mp4': folder / 'final.mp4', 'evidence/capture.json': marker,
                   'evidence/review.json': review_path, 'evidence/material-detail.json': folder / 'material-detail.json'}
        sources.update({f'evidence/{name}': inside(folder, name) for name in captured['evidence']})
        manifest = bundles.create(output, PACKAGE_KIND, video_digest, sources, {
            **scope, 'target_language': review['locale'], 'video_sha256': video_digest,
            'old_requirement_code': captured['candidate']['old_requirement_code'],
            'old_material_id': captured['candidate']['material_id'], 'technical_decision': 'pass',
            'reuse_origin': captured['candidate'].get('origin', 'historical_delivery'),
            'status': 'reviewed_historical_translation', 'origin_run_id': folder.name,
            'quality_passed': False, 'package_mode': 'lean', 'restoration_eligible': False})
        result = {'video_index': index, 'locale': review['locale'], 'package': output.relative_to(root).as_posix()}
        eligibility(code, record, video, result, output, manifest, root)
        identity = {'requirement_name': code, 'target_language': review['locale'],
                    'task_name': f'原片-{index}', 'keep_multiple_versions': False}
        register_package(root, output, manifest, identity, managed, existed)
        return result


def eligibility(code, record, video, item, folder, manifest, root):
    _require_reuse_allowed(record)
    meta = manifest['metadata']
    scope = _scope(record, video)
    captured = read_json(folder / 'evidence/capture.json')
    review = read_json(folder / 'evidence/review.json')
    files = {entry['path']: entry['sha256'] for entry in manifest['files']}
    require(all(meta.get(key) == value for key, value in scope.items()) and captured['scope'] == scope
            and captured['decode_passed'] is True and captured['video_sha256'] == meta['video_sha256']
            and files.get('final.mp4') == meta['video_sha256']
            and files.get('evidence/material-detail.json') == captured['material_detail_sha256']
            and all(files.get(f'evidence/{name}') == digest for name, digest in captured['evidence'].items()),
            'Reuse package is missing the original, reviewed video or capture evidence')
    validated_review = _review(review, captured, video, root)
    require(validated_review['locale'] == item['locale'] == meta['target_language']
            and meta['old_requirement_code'] == captured['candidate']['old_requirement_code']
            and meta['old_material_id'] == captured['candidate']['material_id']
            and meta.get('reuse_origin', 'historical_delivery') ==
            captured['candidate'].get('origin', 'historical_delivery'),
            'Reuse package language or historical identity changed')
    require_clear(code, scope['source_sha256'], meta['video_sha256'], root)
    require_clear(meta['old_requirement_code'], scope['source_sha256'], meta['video_sha256'], root)
    require(publication_decision(meta['old_requirement_code'], meta['video_sha256'], root)
            != 'blocked_major_or_incomplete', 'Historical video has an unresolved major or incomplete publication review')
    specs = record.get('delivery_specifications', {})
    if specs.get('aspect_ratio'):
        width, height = specs['aspect_ratio']
        require(captured['metadata']['width'] * height == captured['metadata']['height'] * width,
                'Historical video does not meet the required aspect ratio')
    if specs.get('clear_audio'):
        require(captured['metadata']['has_audio'] and validated_review.get('clear_audio_decision') == 'pass',
                'Clarified clear-audio delivery needs a hash-bound passing audio review')
    provenance = {'mode': PACKAGE_KIND, 'old_requirement_code': meta['old_requirement_code'],
                  'old_material_id': meta['old_material_id'], 'review_sha256': files['evidence/review.json']}
    if meta.get('reuse_origin') == 'upstream_original':
        provenance['reuse_origin'] = meta['reuse_origin']
    return provenance


def prepared_locales(code, record, video, root):
    if is_linked_rework(record):
        return []
    path = fireplay._folder(code, root) / f"return-{video['index']}.json"
    if not path.exists():
        return []
    outbox = read_json(path)
    if outbox.get('content_version') != record['content_version']:
        return []
    locales = []
    hashes = {}
    for _, item in fireplay._active_packages(outbox):
        if item.get('historical_reuse'):
            fireplay._verify_frozen_package(code, record, item, root, hashes)
            locales.append(item['locale'])
    return locales
