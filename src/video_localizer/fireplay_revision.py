"""Narrow review of quantity corrections without replacing funded production."""
from .common import file_hash, require, utc_now, write_json


def completed_repair_pending(previous, folder, root, video_indices=None):
    """Detect a full, newly finalized repair without reopening funding or writes.

    Used only with an explicit user repair decision. Settled prior receipts stay
    intact; missing/unchanged outputs and uncertain external operations do not
    qualify as a continuation of a completed requirement.
    """
    from .common import inside, read_json
    boxes = [read_json(p) for p in folder.glob('return-*.json')]
    if not boxes or any(b.get('state') != 'returned'
                        or b.get('operations', {}).get('bind', {}).get('state') != 'verified'
                        or any(op.get('state') != 'verified'
                               for op in b.get('operations', {}).values()) for b in boxes):
        return False
    prior = {(p['video_index'], p['locale']): p for b in boxes for p in b['packages']}
    expected = {(v['index'], locale) for v in previous.get('videos', []) for locale in v['targets']}
    if not expected or set(prior) != expected:
        return False
    requested = expected
    if video_indices is not None:
        if (not isinstance(video_indices, list) or not video_indices
                or any(not isinstance(i, int) or isinstance(i, bool) for i in video_indices)
                or len(set(video_indices)) != len(video_indices)
                or not set(video_indices) <= {v['index'] for v in previous['videos']}):
            return False
        requested = {key for key in expected if key[0] in video_indices}
    changed = set()
    for video in previous['videos']:
        for member in video.get('members', []):
            run = inside(root, 'runs/' + member)
            completion, request, final = (run / 'outputs/completion.json',
                                          run / 'inputs/request.json', run / 'outputs/final.mp4')
            if not all(p.is_file() for p in (completion, request, final)):
                continue
            done, req = read_json(completion), read_json(request)
            key = (video['index'], req.get('target_language'))
            if (key in expected and done.get('decode_passed') is True
                    and done.get('state') in {'delivered', 'delivered_with_issues'}
                    and done.get('source_sha256') == video.get('source', {}).get('sha256')
                    and done.get('video_sha256') != prior[key]['sha256']
                    and done.get('video_sha256') == file_hash(final)):
                changed.add(key)
    return changed == requested


def _unexecuted_quality_repair(old, grant, root, digest):
    """Host-attested unsent uploads can be archived, never presumed cancelled."""
    if grant.get('unexecuted_quality_repair') is not True:
        return False
    from .common import inside, read_json
    from . import bundles, quality_holds
    ref = grant.get('host_non_execution', {})
    evidence = inside(root, ref.get('path', ''))
    require(evidence.is_file() and file_hash(evidence) == ref.get('sha256'),
            'Unsent repair needs hash-bound host non-execution evidence')
    observed = read_json(evidence)
    operations = old.get('operations', {})
    require(observed.get('outbox_sha256') == digest and observed.get('reviewer')
            and observed.get('basis') and observed.get('external_call_executed') is False
            and observed.get('file_selected') is False,
            'The host must explicitly verify that no file or external call was sent')
    require(operations and set(observed.get('operation_ids', [])) == set(operations)
            and all(key.startswith('upload-') and op.get('state') == 'unknown'
                    and not any(op.get(k) for k in ('result', 'receipt_sha256', 'last_observed_receipt'))
                    for key, op in operations.items()),
            'Only unsent upload preparations without receipts/import/bind can be archived')
    for package in old.get('packages', []):
        manifest = bundles.verify(inside(root, package['package']))
        require(manifest['metadata']['video_sha256'] == package['sha256']
                and quality_holds.active(manifest['metadata']['source_sha256'], package['sha256'], root),
                'Unsent repair applies only to the exact rejected package')
    require(bool(old.get('packages')), 'Unsent repair needs rejected packages')
    return True


def return_revision(path, old, value, grant, root):
    """Archive a settled return before an explicitly requested, reviewed repair.

    This changes the active delivery record only. Previously bound platform
    materials and all of their receipts remain in the immutable archive.
    """
    require(grant.get('authority') == 'user' and grant.get('authorization_ref')
            and grant.get('source_quote') and grant.get('reason'),
            'Return revision needs the actual user repair instruction')
    digest = file_hash(path)
    require(grant.get('previous_outbox_sha256') == digest,
            'Return revision must bind the exact previous outbox')
    operations = old.get('operations', {})
    settled = (old.get('state') == 'returned' and operations.get('bind', {}).get('state') == 'verified')
    # A defect found after import must not force binding the rejected video just
    # to replace it. Reconcile every imported object first; never erase an
    # uncertain write or a dispatched binding with this pre-binding branch.
    unbound = (grant.get('unbound_reviewed_repair') is True and 'bind' not in operations
               and bool(old.get('packages'))
               and all(operations.get(f'{phase}-{i}', {}).get('state') == 'verified'
                       for i, _ in enumerate(old['packages'], 1)
                       for phase in ('upload', 'import', 'verify')))
    unsent = _unexecuted_quality_repair(old, grant, root, digest)
    require((settled or unbound or unsent)
            and (unsent or all(op.get('state') == 'verified' for op in operations.values())),
            'Settle all prior return operations before a repair revision')
    previous = {(p['video_index'], p['locale']): p for p in old['packages']}
    current = {(p['video_index'], p['locale']): p for p in value['packages']}
    require(previous.keys() <= current.keys(), 'Repair revision must retain every previously submitted locale')
    require(all(current[k]['sha256'] != p['sha256'] for k, p in previous.items()),
            'Repair revision requires new reviewed video bytes for every replaced locale')
    archive = path.parent / 'return-revisions' / f'{path.stem}-{digest}.json'
    if not archive.exists():
        write_json(archive, old)
    require(file_hash(archive) == digest, 'Prior return archive differs from the verified outbox')
    value['revision_history'] = [*old.get('revision_history', []), {
        'prior_outbox': str(archive.relative_to(root)), 'prior_outbox_sha256': digest,
        'authorization': grant, 'recorded_at': utc_now(),
        'boundary': 'New active repaired deliveries only; prior platform bindings are preserved, not deleted.'}]
    write_json(path, value)
    return value


def quantity_correction(previous, snap, decision, targets):
    if not decision.get('review_quantity_only') or previous.get('content_version') == snap['content_version']:
        return False
    before = previous.get('snapshot', {}).get('brief', {})
    after = snap['brief']
    keys = ('id', 'code', 'deptId', 'title', 'description', 'refText', 'assetType', 'locales', 'channels')
    require(previous.get('budget') and any(v.get('members') for v in previous.get('videos', []))
            and previous.get('decision', {}).get('quantity_mode') == 'one_per_locale'
            and decision.get('quantity_mode') == 'one_per_locale'
            and decision.get('reviewed_content_version') == previous.get('content_version')
            and decision.get('revision_reason') and previous.get('targets') == targets
            and all(before.get(k) == after.get(k) for k in keys)
            and before.get('quantity') != after.get('quantity')
            and after.get('quantity') == sum(len(v['targets']) for v in previous.get('videos', [])),
            'Quantity-only review needs unchanged funded source/language scope and the exact old version')
    return True


def append_reviewed_sources(previous, snap, sources, decision, targets, folder, root):
    """Append explicitly approved sources to an active, unsubmitted funded request.

    Existing source scopes, worker identities, chat, runs and all budget bytes stay
    intact. This function makes no model call, publication or budget mutation.
    """
    import copy
    import re
    from pathlib import Path
    from .common import inside, object_hash, read_json

    require(decision.get('review_source_addition') is True
            and decision.get('source_addition_authority') == 'user'
            and decision.get('reviewed_content_version') == previous.get('content_version')
            and decision.get('revision_reason'),
            'Source addition needs the exact previous version and explicit human review')
    require(snap['row'].get('id') == previous.get('requirement_id')
            and snap['row'].get('canBindMaterials') is True
            and snap['row'].get('status') == 'not_started',
            'Source addition is limited to the same writable, not-done requirement')
    require(previous.get('budget') and previous.get('chat', {}).get('state') == 'ready',
            'Preserve the existing funded owner chat')
    require(not list(folder.glob('return-*.json')),
            'Settle and explicitly review existing return batches before adding sources')
    old_sources = previous.get('videos') or []
    require(old_sources and len(sources) > len(old_sources)
            and targets == previous.get('targets'),
            'This review only appends sources with unchanged target languages')
    require(all((a['source_url'], a.get('youtube_video_id'), a['index'], a.get('targets'))
                == (b['source_url'], b.get('youtube_video_id'), b['index'], b.get('targets'))
                for a, b in zip(old_sources, sources)),
            'Existing source order, identity, index and languages must stay unchanged')
    added = sources[len(old_sources):]
    added_urls = [v['source_url'] for v in added]
    require(len(set(v['source_url'] for v in sources)) == len(sources)
            and decision.get('approved_source_urls') == added_urls
            and all(v.get('targets') == targets for v in added),
            'Human approval must cover exactly the distinct appended source URLs')

    authority = read_json(inside(root, decision['authorization_ref']))
    require(authority.get('authority') == 'user'
            and authority.get('source_quote') == decision.get('source_quote')
            and authority.get('requirement_id') == previous['requirement_id']
            and authority.get('approved_source_urls') == added_urls
            and authority.get('budget_id') == previous['budget'],
            'Bind the actual human source-addition receipt to this requirement and original budget')
    budget_path = inside(root, 'state/budgets/' + previous['budget'] + '.json')
    budget = read_json(budget_path)
    require(budget.get('state') == 'open'
            and decision.get('keep_credit_limit') == budget.get('credit_limit')
            and authority.get('credit_limit') == budget.get('credit_limit'),
            'Source addition must retain the original open shared credit limit')

    def clean_text(value, urls):
        text = str(value or '').replace('\\n', '\n')
        for url in sorted(urls, key=len, reverse=True):
            text = text.replace(url, '')
        return re.sub(r'\s+', ' ', text).strip()

    old_brief, new_brief = previous['snapshot']['brief'], snap['brief']
    urls = [v['source_url'] for v in sources]
    for key in ('title', 'description', 'refText'):
        require(clean_text(old_brief.get(key), urls) == clean_text(new_brief.get(key), urls),
                'This review cannot change non-source brief content: ' + key)
    for key in ('landingUrl', 'assetType', 'aiMode', 'bizLine', 'category', 'quantity',
                'locales', 'channels', 'priority', 'tags', 'requesterIds', 'dueDate'):
        require(old_brief.get(key) == new_brief.get(key),
                'This review cannot change other requirement fields: ' + key)
    require(previous['snapshot']['row'].get('assigneeIds') == snap['row'].get('assigneeIds'),
            'Review an assignee change separately from source addition')

    # Archive first; the caller holds request.json's lock and writes the new
    # current snapshot atomically after this return. Budget and worker registries
    # are never rewritten here.
    archive = folder / 'revisions' / (object_hash(previous) + '.json')
    write_json(archive, previous)
    result = copy.deepcopy(previous)
    for video in result['videos']:
        video.setdefault('source_scope_content_version', previous['content_version'])
    for video in added:
        result['videos'].append({**copy.deepcopy(video),
                                 'source_scope_content_version': snap['content_version']})
    result.setdefault('revision_history', []).append({
        'scope': 'append_only_sources_before_return',
        'content_version': previous['content_version'],
        'path': archive.relative_to(root).as_posix(),
        'reason': decision['revision_reason'], 'reviewed_at': utc_now(),
        'authority': {'path': decision['authorization_ref'],
                      'sha256': file_hash(inside(root, decision['authorization_ref']))},
        'added_source_urls': added_urls, 'budget_id': previous['budget'],
        'credit_limit_unchanged': budget['credit_limit']})
    result['content_version'] = snap['content_version']
    return result


def reviewed_download_metadata(root, video, metadata, local, reference):
    """Verify an attributed, byte-bound review of contradictory library metadata.

    Retain the raw lookup/detail claims. A verified resource URL, current source
    identity, downloaded bytes and actual visual evidence are all required;
    merely ignoring dimensions or supplying another local file is insufficient.
    """
    from .common import inside, object_hash, read_json
    report_path = inside(root, reference['path'])
    require(file_hash(report_path) == reference.get('sha256'), 'Source metadata review changed')
    report = read_json(report_path)
    resolved = video.get('resolved', {})
    detail = video.get('source_detail', {}).get('material', {})
    resources = [r for r in detail.get('resources', [])
                 if r.get('id') == resolved.get('source_resource_id')
                 and r.get('backupUrl') == resolved.get('video_r2_url')
                 and r.get('youtubeVideoId') == video.get('youtube_video_id')]
    require(detail.get('id') == resolved.get('material_id') and len(resources) == 1,
            'Metadata review needs the exact current library resource and YouTube identity')
    resource = resources[0]
    require(resource.get('fileSize') in (0, None, local.stat().st_size),
            'A contradictory nonzero resource byte size needs separate source reconciliation')
    require(report.get('reviewer') and report.get('reason')
            and report.get('decision') == 'use_verified_recorded_resource_bytes'
            and report.get('youtube_video_id') == video['youtube_video_id']
            and report.get('resource_id') == resource['id']
            and report.get('resource_url') == resource['backupUrl']
            and report.get('lookup_sha256') == object_hash(resolved)
            and report.get('material_detail_sha256') == object_hash(video['source_detail']),
            'Source metadata review must bind the actual raw lookup and material detail')
    require(report.get('source_sha256') == file_hash(local)
            and report.get('bytes') == local.stat().st_size
            and report.get('actual_dimensions') == [metadata['width'], metadata['height']]
            and report.get('reported_dimensions') == [resolved['width'], resolved['height']]
            and abs(report.get('actual_duration', -1) - metadata['duration']) < .001,
            'Source metadata review belongs to different downloaded bytes or dimensions')
    actual_ratio = metadata['width'] / metadata['height']
    reported_ratio = resolved['width'] / resolved['height']
    require(abs(actual_ratio - reported_ratio) < .002
            and abs(metadata['duration'] - resolved.get('duration', metadata['duration'])) < 1,
            'Source geometry or duration differs beyond a metadata resolution conflict')
    evidence = report.get('evidence')
    require(isinstance(evidence, list) and len(evidence) >= 2
            and {x.get('role') for x in evidence} >= {'actual_native_frame', 'platform_thumbnail'},
            'Inspect the actual source and platform thumbnail before reconciling metadata')
    for item in evidence:
        path = inside(root, item['path'])
        require(path.suffix.lower() in ('.png', '.jpg', '.jpeg')
                and path.is_file() and file_hash(path) == item.get('sha256'),
                'Source identity image evidence changed')
    return {'reason': report['reason'], 'method': 'attributed_exact_resource_byte_review',
            'review': reference, 'resource_id': resource['id'], 'bytes': local.stat().st_size,
            'reported_dimensions': report['reported_dimensions'],
            'actual_dimensions': report['actual_dimensions'],
            'original_resolution_claim': resource.get('extraInfo', {}).get('youtube', {}).get('resolution'),
            'material_detail_sha256': object_hash(video['source_detail']), 'reviewed_at': utc_now()}
