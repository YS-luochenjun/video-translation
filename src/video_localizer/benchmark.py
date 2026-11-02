"""Prospective, evidence-only benchmarks. No production imports or provider calls.

Request wall time, executor occupancy and explicit waits are different measures.
Missing instrumentation is unknown time, never inferred Agent work or model compute.
"""
from __future__ import annotations

import json
import math
import subprocess
from statistics import median

from .ledger import now, packed, seconds

KEY = 'benchmark:activation'
PREFIX = 'benchmark:sample:'
DEFAULTS = {'profile_version': 'prospective-v1', 'p90_min_samples': 20,
            'minimum_exploratory_samples': 6, 'duration_bands_seconds': [30, 60]}


def read_object(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def revision(root):
    try:
        value = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, capture_output=True,
                               text=True, timeout=3, check=True).stdout.strip()
        return value if len(value) == 40 and all(c in '0123456789abcdef' for c in value) else None
    except (OSError, subprocess.SubprocessError):
        return None


def update(ledger):
    """Called after reconciliation. Establish baseline once, never enroll old work."""
    with ledger.connection(True) as db:
        requirements = [json.loads(r['data']) for r in db.execute('SELECT data FROM requirements')]
        row = db.execute('SELECT value FROM meta WHERE key=?', (KEY,)).fetchone()
        if not row:
            settings = read_object(ledger.root / 'config/ledger.json').get('benchmark', {})
            if not isinstance(settings, dict):
                raise ValueError('ledger.benchmark must be an object')
            settings = {**DEFAULTS, **settings}
            bands = settings['duration_bands_seconds']
            if (not isinstance(bands, list) or len(bands) != 2 or
                    any(not isinstance(n, (int, float)) or isinstance(n, bool) or not math.isfinite(n) or n <= 0 for n in bands) or bands[0] >= bands[1] or
                    any(not isinstance(settings[k], int) or isinstance(settings[k], bool) or settings[k] < 1 for k in ('p90_min_samples', 'minimum_exploratory_samples')) or
                    not isinstance(settings['profile_version'], str) or not settings['profile_version']):
                raise ValueError('Invalid benchmark grouping or sample thresholds')
            activation = {'started_at': now(), 'baseline_ids': sorted(r['id'] for r in requirements),
                          'settings': {**DEFAULTS, **settings}}
            db.execute('INSERT INTO meta VALUES(?,?)', (KEY, packed(activation)))
            return activation
        activation = json.loads(row['value'])
        start = seconds(activation['started_at'])
        for req in requirements:
            key = PREFIX + req['id']
            old = db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
            sample = json.loads(old['value']) if old else None
            received = seconds(req.get('received_at'))
            if not sample:
                if (req['id'] in activation['baseline_ids'] or not req.get('countable') or
                        received is None or not start < received <= seconds(now()) or
                        (seconds(req.get('first_started_at')) or received) < start or
                        (seconds(req.get('first_complete_at')) or received) < start):
                    continue
                sample = {'requirement_id': req['id'], 'code': req['code'], 'scope_id': req['scope_id'],
                          'received_at': req['received_at'], 'enrolled_at': now(),
                          'profile_version': activation['settings']['profile_version'],
                          'code_revision': revision(ledger.root), 'first_output': None}
            same_scope = sample['scope_id'] == req['scope_id'] and not sample.get('tracking_ended_at')
            sample['scope_changed'] = not same_scope
            if same_scope:
                sample['external_receipts'] = req.get('external', [])
                sample['run_ids'] = sorted({run for t in db.execute('SELECT data FROM tasks WHERE requirement_id=?', (req['id'],))
                                           for run in json.loads(t['data']).get('runs', [])})
            elif not sample.get('tracking_ended_at'):
                sample['tracking_ended_at'] = now()
            if same_scope and not sample['first_output']:
                sample.update(sources=req.get('benchmark_sources', []), video_count=req.get('video_count', 0),
                              task_count=req.get('task_count', 0), locale_count=len({t for v in req.get('scope', []) for t in v['targets']}),
                              budget_ids=req.get('budget_ids', []), evidence=req.get('evidence', []))
                complete = seconds(req.get('scope_first_complete_at'))
                if complete is not None and not received <= complete <= seconds(now()):
                    sample['invalid_first_output_at'] = req['scope_first_complete_at']
                if complete is not None and received <= complete <= seconds(now()):
                    tasks = [json.loads(t['data']) for t in db.execute('SELECT data FROM tasks WHERE requirement_id=?', (req['id'],))]
                    scope = {(v['video_id'], t) for v in req['scope'] for t in v['targets']}
                    first_versions = []
                    for task in tasks:
                        if (task['video_id'], task['locale']) not in scope:
                            continue
                        versions = sorted(task.get('versions', []), key=lambda v: seconds(v.get('at')) or math.inf)
                        if versions:
                            first_versions.append({'video_id': task['video_id'], 'locale': task['locale'], **versions[0]})
                    sample['first_output'] = {'at': req['scope_first_complete_at'], 'versions': first_versions,
                                              'quality_pass_count': sum(v.get('quality') == 'pass' for v in first_versions),
                                              'quality_evidence_complete': len(first_versions) == len(scope)}
            db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', (key, packed(sample)))
        return activation


def merge(intervals, lower, upper):
    result = []
    for start, end in sorted((max(a, lower), min(b, upper)) for a, b in intervals if a is not None and b is not None and b > a):
        if end <= start:
            continue
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(end, result[-1][1]))
        else:
            result.append((start, end))
    return result


def total(intervals):
    return round(sum(b-a for a, b in intervals), 3)


def timing(sample, events, clock):
    clock = min(clock, seconds(sample.get('tracking_ended_at')) or clock)
    lower = seconds(sample['received_at'])
    first = seconds((sample.get('first_output') or {}).get('at'))
    intervals, activity, waits, opened, running = [], [], [], None, 0
    for event in sorted(events, key=lambda e: (seconds(e['occurred_at']) or seconds(e['recorded_at']) or 0, e.get('id', ''))):
        data, kind = event['data'], event['kind']
        if event.get('run_id') and event['run_id'] not in sample.get('run_ids', []):
            continue
        at = seconds(event['occurred_at']) or seconds(event['recorded_at'])
        if at is None or at < lower or at > clock or (data.get('scope_id') and data['scope_id'] != sample['scope_id']):
            continue
        if kind == 'stage_recorded' and not data.get('parent_id'):
            a, b = seconds(data.get('started_at')), seconds(data.get('ended_at'))
            if a is not None and b is not None and lower <= a <= b <= clock:
                intervals.append((a, b))
                activity.extend([a, b])
            elif data.get('status') == 'running':
                running += 1
        elif kind in {'claim', 'stage', 'heartbeat', 'executor.started', 'executor.finished', 'executor.failed', 'executor.heartbeat'}:
            activity.append(at)
        if kind == 'block':
            # Replacing a reason continues the same wait; no double counting.
            if opened is None:
                opened = at
        elif kind == 'resume' and opened is not None:
            waits.append((opened, at))
            opened = None
    if opened is not None:
        waits.append((opened, clock))
    begin = min(activity, default=None)
    end = first if first is not None else clock
    first_intervals = merge(intervals, lower, end)
    first_wait = merge(waits, lower, end)
    occupied = merge(first_intervals + first_wait, lower, end)
    latest = max(activity + ([first] if first is not None else []), default=lower)
    rework = merge(intervals, first or clock, clock)
    return {'first_round_complete': first is not None,
            'received_to_first_output_seconds': first-lower if first is not None else None,
            'first_production_span_seconds': first-begin if first is not None and begin is not None and begin <= first else None,
            'recorded_first_executor_seconds': total(first_intervals) if first_intervals else None,
            'recorded_first_wait_seconds': total(first_wait) if first_wait else None,
            'unclassified_first_seconds': max(0, round(end-lower-total(occupied), 3)),
            'recorded_rework_executor_seconds': total(rework) if rework else None,
            'recorded_rework_wait_seconds': total(merge(waits, first or clock, clock)) or None,
            'rework_observed_span_seconds': latest-first if first is not None and latest > first else None,
            'open_wait': opened is not None, 'unfinished_timing_records': running,
            'timing_records': len(intervals)}


def describe(sample, settings):
    sources = sample.get('sources') or []
    durations = [s.get('duration_seconds') for s in sources]
    known = len(durations) == sample.get('video_count') and bool(durations) and all(isinstance(d, (int, float)) and math.isfinite(d) and d > 0 for d in durations)
    longest = max(durations) if known else None
    bands = settings['duration_bands_seconds']
    band = 'unknown' if longest is None else f'≤{bands[0]}s' if longest <= bands[0] else f'{bands[0]}–{bands[1]}s' if longest <= bands[1] else f'>{bands[1]}s'
    features_known = bool(sources) and all(s.get('content_features') for s in sources)
    features = sorted({f for s in sources for f in (s.get('content_features') or [])})
    complexity = ('motion/dialogue' if set(features) & {'animated_text', 'foreground_occlusion', 'multi_character_dialogue', 'overlapping_speech', 'moving_watermark'}
                  else 'styled/surface' if set(features) & {'artistic_typography', 'surface_typography', 'filmed_phone_ui'}
                  else 'observed_other') if features_known else 'unknown'
    return {'longest_source_seconds': longest, 'total_source_seconds': sum(durations) if known else None,
            'duration_band': band, 'complexity': complexity, 'content_features': features,
            'video_count': sample.get('video_count'), 'locale_count': sample.get('locale_count'),
            'task_count': sample.get('task_count'), 'profile_version': sample['profile_version'],
            'code_revision': sample.get('code_revision')}


def costs(root, sample):
    values, unknown, missing = [], 0, not bool(sample.get('budget_ids'))
    for budget in sorted(set(sample.get('budget_ids', []))):
        # IDs are data, never filesystem traversal.
        if not isinstance(budget, str) or '/' in budget or '\\' in budget or budget.startswith('.'):
            missing = True
            continue
        record = read_object(root / 'state/budgets' / (budget + '.json'))
        rows = record.get('reservations')
        if not isinstance(rows, (dict, list)) or not rows:
            missing = True
            continue
        for row in rows.values() if isinstance(rows, dict) else rows:
            credit = row.get('actual_credits') if isinstance(row, dict) else None
            if (not isinstance(credit, (int, float)) or isinstance(credit, bool) or not math.isfinite(credit) or credit < 0
                    or row.get('state') not in {'success', 'fail', 'failed', 'response_received', 'response_invalid'}):
                unknown += 1
            else:
                values.append(credit)
    return {'known_actual_credits': sum(values) if values else None,
            'unknown_reservations': unknown, 'complete': not missing and not unknown,
            'scope': 'current_request_budget_including_rework; not first_round_cost'}


def report(ledger, rows=None, at=None):
    """Read-only report over durable samples; filters select requests, not baseline."""
    moment = at or now()
    clock = seconds(moment)
    if clock is None:
        raise ValueError('Benchmark time requires a timezone')
    allowed = {r['id'] for r in rows} if rows is not None else None
    with ledger.connection() as db:
        row = db.execute('SELECT value FROM meta WHERE key=?', (KEY,)).fetchone()
        if not row:
            return {'enabled': False, 'samples': [], 'cohorts': [], 'completed_samples': 0, 'pending_samples': 0}
        activation = json.loads(row['value'])
        records = [json.loads(r['value']) for r in db.execute('SELECT value FROM meta WHERE key LIKE ?', (PREFIX+'%',))]
        result = []
        for sample in records:
            if allowed is not None and sample['requirement_id'] not in allowed:
                continue
            events = [{**dict(e), 'data': json.loads(e['data'])} for e in db.execute('SELECT * FROM events WHERE requirement_id=?', (sample['requirement_id'],))]
            result.append({**sample, 'dimensions': describe(sample, activation['settings']),
                           'timing': timing(sample, events, clock), 'cost': costs(ledger.root, sample)})
    groups = {}
    for sample in result:
        # A scope change before initial completion is not a comparable first round.
        if not sample['first_output']:
            continue
        d = sample['dimensions']
        key = packed(d | {'longest_source_seconds': None, 'total_source_seconds': None, 'content_features': None})
        groups.setdefault(key, {'dimensions': d, 'samples': []})['samples'].append(sample)
    cohorts = []
    for group in groups.values():
        samples = group['samples']
        cycles = sorted(s['timing']['received_to_first_output_seconds'] for s in samples)
        production = [s['timing']['first_production_span_seconds'] for s in samples if s['timing']['first_production_span_seconds'] is not None]
        cohorts.append({'dimensions': group['dimensions'], 'n': len(samples),
                        'median_first_cycle_seconds': median(cycles),
                        'median_first_production_seconds': median(production) if production else None,
                        'production_samples': len(production),
                        'p90_first_cycle_seconds': cycles[math.ceil(.9*len(cycles))-1] if len(cycles) >= activation['settings']['p90_min_samples'] else None,
                        'exploratory': len(cycles) < activation['settings']['minimum_exploratory_samples']})
    return {'enabled': True, 'started_at': activation['started_at'], 'baseline_excluded': len(activation['baseline_ids']),
            'settings': activation['settings'], 'samples': sorted(result, key=lambda s: s['received_at'], reverse=True),
            'completed_samples': sum(bool(s['first_output']) for s in result),
            'pending_samples': sum(not s['first_output'] and not s['scope_changed'] for s in result),
            'stopped_samples': sum(not s['first_output'] and s['scope_changed'] for s in result), 'cohorts': cohorts,
            'note': '首轮截至全部原片/目标语首次完整输出；之后为返工。执行器占用非模型计算或Agent总工时；明确等待可能与并行执行重叠，不能相加。未分类保留未知；质量、当前费用、外部受理各自核验。不回放历史需求，不自动校准ETA。'}
