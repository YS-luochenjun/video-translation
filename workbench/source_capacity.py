"""Read the production slot journal and the monitor's dispatch candidates."""
from collections import Counter

from video_localizer.common import WorkflowError, utc_now
from video_localizer.fireplay_monitor import dispatch_queue
from video_localizer.fireplay_parallel import active_sources, capacity, policy


def project_capacity(root):
    if not (root / 'config/fireplay-parallel.json').is_file():
        return {'state': 'unconfigured'}
    try:
        active = active_sources(root)
        limits = capacity(root, active)
        per_requirement = policy(root)['max_active_sources_per_requirement']
    except (WorkflowError, OSError, ValueError, KeyError, TypeError, AttributeError):
        return {'state': 'unavailable'}
    result = {'state': 'ready', **limits, 'observed_at': utc_now(), 'queue': None}
    if not (root / 'state/fireplay/monitor/state.json').is_file():
        return result
    try:
        candidates = dispatch_queue(root)
    except (WorkflowError, OSError, ValueError, KeyError, TypeError, AttributeError):
        return result
    available = limits['available_source_slots']
    allocated = Counter(requirement_id for requirement_id, _ in active)
    queue = {'ready': 0, 'waiting': 0, 'preparing': 0, 'legacy_requirements': 0, 'sources': []}
    for entry in candidates:
        if 'sources' not in entry:
            queue['legacy_requirements'] += 1
            continue
        for source in entry['sources']:
            requirement_id, index = entry['id'], source['video_index']
            if (requirement_id, index) in active:
                continue
            if not source['source_registered'] or source['state'] in {'reserved', 'unknown'}:
                state = 'preparing'
            elif available == 0 or (per_requirement is not None and allocated[requirement_id] >= per_requirement):
                state = 'waiting'
            else:
                state = 'ready'
                allocated[requirement_id] += 1
                if available is not None:
                    available -= 1
            queue[state] += 1
            queue['sources'].append({'code': entry['code'], 'video_index': index, 'state': state})
    return {**result, 'queue': queue}
