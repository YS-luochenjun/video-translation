"""Read-only production evidence for historical reuse, independent of media retention."""
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

from . import fireplay, fireplay_reuse
from .common import ROOT, file_hash, read_json
from .fireplay_submission import _canonical_materials


def _outcome(decision):
    if decision['prepared_reuse_locales']:
        return 'partial_reuse' if decision['production_locales'] else 'full_reuse'
    if decision.get('fallback'):
        return decision['fallback']['kind']
    states = {search['state'] for search in decision['searches']}
    if states & {'no_visible_match', 'no_quick_match'}:
        return 'platform_no_match'
    if states == {'cached_no_match'}:
        return 'cached_no_match'
    if states == {'no_search_identity'}:
        return 'no_search_identity'
    return 'no_eligible_candidate'


def _bound_reuse(code, record, video, root):
    path = fireplay._folder(code, root) / f"return-{video['index']}.json"
    box = read_json(path) if path.is_file() else {}
    if (box.get('requirement_id'), box.get('content_version'), box.get('video_index')) != (
            record['requirement_id'], record['content_version'], video['index']):
        return set()
    verified = {(item['locale'], item['sha256']) for item in
                _canonical_materials(box, include_prior_binding=True, require_bound_ids=True)}
    return {item['locale'] for _, item in fireplay._active_packages(box)
            if item.get('historical_reuse') and (item['locale'], item['sha256']) in verified}


def _source(code, record, video, root):
    bound = _bound_reuse(code, record, video, root)
    result = {'code': code, 'video_index': video['index'], 'outcome': 'not_recorded',
              'bound_reuse_locales': sorted(bound), 'verified_skip_and_bind_locales': []}
    if fireplay_reuse.is_linked_rework(record):
        return {**result, 'outcome': 'linked_rework'}
    if not video.get('source'):
        return {**result, 'outcome': 'source_not_registered'}
    scope = fireplay_reuse._scope(record, video)
    preflight = fireplay_reuse._preflight_path(code, scope, root)
    if not preflight.is_file():
        return {**result, 'outcome': 'bound_without_preflight' if bound else 'not_recorded'}
    decision = read_json(preflight)
    if (any(decision.get(key) != value for key, value in scope.items())
            or decision.get('targets') != video['targets']):
        return {**result, 'outcome': 'preflight_scope_changed'}
    result.update(outcome=_outcome(decision), timing=decision.get('timing', {}),
                  fallback=(decision.get('fallback') or {}).get('kind'),
                  preflight=preflight.relative_to(root).as_posix())
    digest = file_hash(preflight)
    batch_path = Path(root) / 'state/batches' / f"{video['title']}.json"
    reuse_only = preflight.with_name(f'reuse-only-start-{digest}.json')
    start = batch_path if batch_path.is_file() else reuse_only
    if not start.is_file():
        return result
    value = read_json(start)
    if (value.get('reuse_preflight_sha256') != digest
            or (start == batch_path and value.get('source_sha256') != scope['source_sha256'])):
        return result
    skipped = set(value.get('historical_reuse_locales', [])) & set(decision['prepared_reuse_locales'])
    skipped -= set(value.get('targets', []))
    for locale in tuple(skipped):
        member = f"{video['title']}-{video['targets'].index(locale) + 1:02d}"
        if member in value.get('members', []) or (Path(root) / 'runs' / member / 'run.json').is_file():
            skipped.remove(locale)
    result.update(start=start.relative_to(root).as_posix(),
                  verified_skip_and_bind_locales=sorted(skipped & bound))
    return result


def audit(code, index=None, root=ROOT):
    root = Path(root)
    all_requests = code == 'ALL'
    paths = sorted((root / 'state/fireplay').glob('*/request.json')) if all_requests else [
        fireplay._folder(code, root) / 'request.json']
    sources = []
    for path in paths:
        record = read_json(path)
        videos = record['videos'] if index is None else [fireplay._video(record, index)]
        sources.extend(_source(path.parent.name, record, video, root) for video in videos)
    timings = defaultdict(lambda: defaultdict(list))
    for source in sources:
        for key in ('local_lookup_ms', 'platform_ms', 'preflight_ms'):
            value = source.get('timing', {}).get(key)
            if value is not None:
                timings[source['outcome']][key].append(value)
    return {'scope': 'Local receipt audit only; no platform calls or writes',
            'source_count': len(sources), 'outcomes': dict(Counter(source['outcome'] for source in sources)),
            'sources_with_verified_skip_and_bind': sum(bool(source['verified_skip_and_bind_locales']) for source in sources),
            'timing_by_outcome': {outcome: {key: {'samples': len(values), 'median_ms': median(values)}
                                          for key, values in metrics.items()} for outcome, metrics in timings.items()},
            'sources': sources}
