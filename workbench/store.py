"""Read-only projections of project records. Never imports the production executor.

All data is a recorded observation, not a fresh quality approval or provider poll.
Missing/corrupt records remain visible. Installed assets and credentials are excluded.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote


MEDIA = {'.mp4', '.webm', '.mov', '.wav', '.mp3', '.m4a', '.png', '.jpg', '.jpeg', '.webp'}
AREAS = {'runs', 'outputs', 'media', 'knowledge'}
STATES = {
    'created': ('已收件', '核对原片并建立实例清单'),
    'awaiting_agent_inventory': ('核对源内容', '补齐文字、人声与时间覆盖'),
    'needs_planning': ('待制定计划', '根据实例清单建立制作计划'),
    'planned': ('已有计划', '按现有计划继续，先核对已生成资产'),
    'awaiting_model': ('等待模型结果', '查询已有任务；供应商状态以最近回执为准'),
    'needs_reconciliation': ('提交状态待确认', '核对原任务与回执，避免重复付费提交'),
    'needs_review': ('候选待审', '查看实际成片，补齐适用模式的审核'),
    'needs_revision': ('有问题待处理', '按缺陷和剩余额度有界修正，保留完整译片'),
    'ready_to_deliver': ('质量记录通过', '交付入口仍会重新核验，页面不执行交付'),
    'delivered': ('已交付', '查看正式交付包及后续维护'),
    'delivered_with_issues': ('已输出 · 有瑕疵', '查看完整译片及瑕疵；质量与输出分别记录'),
    'historical_reference': ('历史参考', '仅供追溯，不代表当前质量通过'),
    'unavailable': ('记录需检查', '检查缺失或损坏的记录'),
}


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def clean(value):
    """Do not forward signed URLs, raw provider payloads or credential fields."""
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()
                if not re.search(r'key|token|secret|authorization|cookie|payload|source_url', k, re.I)}
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r'https?://[^\s<>"\]]+', '[远端地址已隐藏]', value)
        value = re.sub(r'(?i)bearer\s+[A-Za-z0-9._~+/=-]+', 'Bearer [已隐藏]', value)
        return re.sub(r'(?i)((?:api[_-]?key|token|secret)\s*[:=]\s*)[^\s,;]+', r'\1[已隐藏]', value)[:16000]
    return value


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self._lock = threading.RLock()
        self._hashes = {}

    def path(self, relative):
        if not isinstance(relative, str) or '\\' in relative or ':' in relative:
            raise ValueError('Invalid workspace path')
        parts = Path(relative).parts
        if not parts or '..' in parts or any(p.startswith('.') for p in parts):
            raise ValueError('Hidden or parent paths are not served')
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError('Path outside workspace')
        return path

    def read(self, relative, default=None, warnings=None):
        try:
            path = self.path(relative)
            if not path.exists():
                return {} if default is None else default
            if path.stat().st_size > 16 * 1024 * 1024:
                raise ValueError('Record exceeds read limit')
            return json.loads(path.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError, TypeError) as exc:
            if warnings is not None:
                warnings.append({'path': relative, 'message': type(exc).__name__})
            return {} if default is None else default

    def glob(self, relative, pattern):
        try:
            return [p.relative_to(self.root).as_posix()
                    for p in sorted(self.path(relative).glob(pattern))
                    if p.is_file() and p.resolve().is_relative_to(self.root)]
        except (OSError, ValueError):
            return []

    def sha(self, relative):
        path = self.path(relative)
        stat = path.stat()
        key = (str(path), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        with self._lock:
            if key not in self._hashes:
                h = hashlib.sha256()
                with path.open('rb') as stream:
                    for part in iter(lambda: stream.read(1024 * 1024), b''):
                        h.update(part)
                if len(self._hashes) > 2048:
                    self._hashes.clear()
                self._hashes[key] = h.hexdigest()
            return self._hashes[key]

    def media(self, relative):
        path = self.path(relative)
        if Path(relative).parts[0] not in AREAS or path.suffix.lower() not in MEDIA:
            raise ValueError('Not a permitted media file')
        if not path.is_file():
            raise FileNotFoundError(relative)
        return path

    def asset(self, relative, expected=None):
        try:
            path = self.media(relative)
            valid = expected is None or self.sha(relative) == expected
            return {'path': relative, 'url': '/api/media?path=' + quote(relative, safe=''),
                    'available': True, 'integrity': 'matched' if expected and valid else 'changed' if not valid else 'not_bound',
                    'bytes': path.stat().st_size}
        except (OSError, ValueError):
            return {'path': relative, 'url': None, 'available': False, 'integrity': 'missing'}

    def _holds(self, source, video):
        if not all(re.fullmatch('[0-9a-f]{64}', str(x or '')) for x in (source, video)):
            return False
        return self.path(f'knowledge/local/quality-holds/{source}/{video}').exists()

    def versions(self, warnings):
        rows = []
        catalog = self.read('outputs/index.json', warnings=warnings)
        for entry in catalog.get('entries', []):
            try:
                package = entry['package']
                if not package.startswith('outputs/'):
                    raise ValueError('Package outside outputs')
                manifest = self.read(package + '/manifest.json', warnings=warnings)
                meta = manifest.get('metadata', {})
                matches = manifest.get('kind') == 'delivery' and all(
                    meta.get(k) == entry.get(k) for k in ('video_sha256', 'source_sha256', 'target_language', 'origin_run_id', 'status'))
                matches = matches and self.sha(package + '/manifest.json') == entry.get('manifest_sha256')
                asset = self.asset(package + '/final.mp4', entry.get('video_sha256'))
                held = self._holds(entry.get('source_sha256'), entry.get('video_sha256'))
                rows.append({**{k: entry.get(k) for k in ('origin_run_id', 'source_sha256', 'target_language', 'video_sha256', 'status', 'archived_at')},
                             'package': package, 'media': asset, 'held': held, 'manifest_ok': bool(matches),
                             'technical_decision': meta.get('technical_decision'), 'quality_scope': meta.get('quality_scope'),
                             'usable': bool(matches and asset['available'] and asset['integrity'] == 'matched')})
            except (KeyError, ValueError, OSError, TypeError):
                warnings.append({'path': str(entry.get('package', 'outputs/index.json')), 'message': '交付包不可读取'})
        return sorted(rows, key=lambda e: e.get('archived_at') or '')

    def _base(self, task, versions):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,180}', task):
            raise ValueError('Invalid task ID')
        run = f'runs/{task}'
        if self.path(run + '/run.json').is_file():
            return run, False
        if versions:
            return versions[-1]['package'] + '/payload', True
        raise FileNotFoundError(task)

    def _task(self, task, versions, full=False):
        warnings = []
        base, archived = self._base(task, versions)
        def read(name):
            return self.read(base + '/' + name, warnings=warnings)
        record, request = read('run.json'), read('inputs/request.json')
        inv, plan = read('analysis/inventory.json'), read('plan.json')
        quality, candidate = read('outputs/quality.json'), read('outputs/candidate.json')
        completion, delivery = read('outputs/completion.json'), read('outputs/delivery.json')
        jobs = [self.read(p, warnings=warnings) for p in self.glob(base + '/jobs', '*.json')]
        jobs = [j for j in jobs if isinstance(j, dict) and j]
        latest = versions[-1] if versions else None
        # A new candidate in a still-active run must not inherit a previous
        # archived version's status or approval. Keep that version in history.
        recent_work = False
        if latest and not archived and candidate.get('sha256') != latest.get('video_sha256'):
            try:
                recent_work = bool(candidate and self.path(base + '/outputs/candidate.json').stat().st_mtime
                                   > datetime.fromisoformat(latest['archived_at']).timestamp())
            except (ValueError, OSError, TypeError):
                recent_work = bool(candidate)
        source_sha = record.get('source_sha256') or (latest or {}).get('source_sha256')
        source = self.asset(base + '/' + record['source'], source_sha) if record.get('source') else None
        if recent_work:
            output = self.asset(base + '/' + candidate['path'], candidate.get('sha256')) if candidate.get('path') else None
        elif latest:
            output = latest['media']
        elif delivery.get('video'):
            output = self.asset(base + '/' + delivery['video'], delivery.get('sha256'))
        elif candidate.get('path'):
            output = self.asset(base + '/' + candidate['path'], candidate.get('sha256'))
        else:
            output = None
        state = 'created'
        coverage = inv.get('coverage', {})
        if inv:
            state = 'needs_planning' if all(coverage.get(k, {}).get('status') == 'reviewed' for k in ('visual', 'speech', 'timeline')) else 'awaiting_agent_inventory'
        if plan:
            state = 'planned'
        if any(j.get('state') in {'submitted', 'waiting', 'queuing', 'generating'} for j in jobs):
            state = 'awaiting_model'
        if any(j.get('state') in {'preparing', 'submitting', 'ambiguous'} for j in jobs):
            state = 'needs_reconciliation'
        bound = bool(quality and candidate and quality.get('video_sha256') == candidate.get('sha256')
                     and quality.get('plan_id') == candidate.get('plan_id'))
        if candidate and state not in {'needs_reconciliation', 'awaiting_model'}:
            state = 'needs_review'
            if bound:
                state = 'ready_to_deliver' if quality.get('decision') == 'pass' else 'needs_revision'
        if delivery and bound and quality.get('decision') == 'pass':
            state = 'delivered'
        if completion.get('state') == 'delivered_with_issues':
            state = 'delivered_with_issues'
        if latest and not recent_work:
            state = latest['status']
        if not output and not record and not plan:
            state = 'unavailable'
        current_sha = candidate.get('sha256') if recent_work else (latest or {}).get('video_sha256') or completion.get('video_sha256') or candidate.get('sha256')
        held = self._holds(source_sha, current_sha)
        quality_state = 'not_reviewed'
        if state == 'delivered_with_issues':
            quality_state = 'issues'
        elif latest and not recent_work:
            quality_state = 'pass' if latest['status'] == 'delivered' and latest['technical_decision'] == 'pass' else 'reference'
        elif bound:
            quality_state = quality.get('decision', 'not_reviewed')
        elif quality:
            quality_state = 'stale'
        if held:
            quality_state = 'hold'
        stale = bool(plan and any(plan.get(key) and self.path(base + '/' + file).is_file()
                     and self.sha(base + '/' + file) != plan[key]
                     for key, file in [('inventory_sha256', 'analysis/inventory.json'), ('request_sha256', 'inputs/request.json')]))
        review_path = base + '/review/' + ('fast-review.json' if plan.get('mode') == 'fast' else 'review.json')
        if quality.get('review_sha256') and self.path(review_path).is_file() and self.sha(review_path) != quality['review_sha256']:
            stale = True
        if stale and (not latest or recent_work) and not held:
            quality_state = 'stale'
            state = 'needs_replanning'
        if output and output['integrity'] in {'changed', 'missing'} or latest and not recent_work and not latest['manifest_ok']:
            quality_state = 'invalid'
        maintenance = self.read(f'state/maintenance/{task}/latest.json', warnings=warnings)
        deferred = self.read(f'state/deferred-delivery/{task}.json', warnings=warnings)
        label, next_action = STATES.get(state, (state, '查看当前任务记录'))
        tracked = [base + '/' + p for p in ('run.json', 'analysis/inventory.json', 'plan.json', 'outputs/candidate.json',
                   'outputs/quality.json', 'outputs/delivery.json', 'outputs/completion.json')]
        times = [self.path(p).stat().st_mtime for p in tracked if self.path(p).is_file()]
        task_data = {'id': task, 'archived': archived, 'source_sha256': source_sha,
                     'target_language': request.get('target_language') or (latest or {}).get('target_language') or '—',
                     'brief': clean(request.get('brief', '')), 'mode': plan.get('mode') or request.get('delivery_mode') or '未记录',
                     'state': state, 'state_label': label, 'next_action': next_action,
                     'quality_state': quality_state, 'quality_scope': quality.get('scope') or (latest or {}).get('quality_scope'),
                     'output_available': bool(output and output['available']), 'held': held,
                     'updated_at': datetime.fromtimestamp(max(times), timezone.utc).isoformat() if times else (latest or {}).get('archived_at'),
                     'created_at': record.get('created_at'), 'versions_count': len(versions),
                     'jobs_count': len(jobs), 'job_states': dict(Counter(j.get('state', 'unknown') for j in jobs)),
                     'coverage': {k: coverage.get(k, {}).get('status', '未记录') for k in ('visual', 'speech', 'timeline')},
                     'maintenance': clean(maintenance), 'deferred': clean(deferred), 'warnings': warnings,
                     'source': source, 'output': output, 'quality_failures': clean(quality.get('failures', [])),
                     'limitations': clean(completion.get('limitations', [])), 'batch': clean(read('inputs/batch.json'))}
        if not full:
            return task_data
        spec = read(completion.get('spec') or 'review/finalization.json')
        if not task_data['limitations']:
            task_data['limitations'] = clean(spec.get('limitations', []))
        tasks = []
        for packet_path in self.glob(base + '/analysis/codex/packets', '*.json'):
            packet = self.read(packet_path, warnings=warnings)
            tasks.append({'path': packet_path, 'stage': packet.get('stage'), 'images': len(packet.get('images', [])),
                          'knowledge': clean(packet.get('knowledge', [])), 'state': '工作包已准备'})
        results = []
        for result_path in self.glob(base + '/analysis/codex/results', '*.json'):
            value = self.read(result_path, warnings=warnings)
            report = value.get('report', {})
            results.append({'path': result_path, 'stage': value.get('stage'), 'method': clean(report.get('method')),
                            'knowledge_read': clean(report.get('knowledge_read', [])),
                            'observations': clean(report.get('observations', [])), 'limitations': clean(report.get('limitations', [])),
                            'outputs': [self.asset(base + '/' + a['path'], a.get('sha256')) for a in value.get('outputs', []) if a.get('path')],
                            'state': value.get('state')})
        usage = []
        for pointer in self.glob(base + '/review/knowledge-use', '*.json'):
            ref = self.read(pointer, warnings=warnings)
            if ref.get('path'):
                value = self.read(ref['path'], warnings=warnings)
                usage.append({'path': ref['path'], 'integrity_ok': self.sha(ref['path']) == ref.get('sha256') if value else False,
                              'plan_id': value.get('plan_id'), 'video_sha256': value.get('video_sha256'),
                              'reviewed_by': clean(value.get('reviewed_by')), 'review_type': value.get('review_type'),
                              'uses': clean(value.get('uses', []))})
        # A retired run's pointer may have been preserved only in the independent knowledge store.
        known = {u['path'] for u in usage}
        for feedback_path in self.glob('knowledge/local/feedback/knowledge-use', '*/feedback.json'):
            value = self.read(feedback_path)
            if feedback_path not in known and value.get('video_sha256') == current_sha:
                usage.append({'path': feedback_path, 'integrity_ok': None, 'plan_id': value.get('plan_id'),
                              'video_sha256': value.get('video_sha256'), 'uses': clean(value.get('uses', [])),
                              'reviewed_by': clean(value.get('reviewed_by')), 'review_type': value.get('review_type')})
        items = []
        for item in inv.get('text_instances', []):
            items.append(clean({k: item.get(k) for k in ('id', 'source_text', 'target_text', 'start', 'end', 'bbox', 'action', 'text_role', 'reason', 'speech_id')}))
        observations = []
        for path in self.glob(base + '/review', '*notes.json') + self.glob(base + '/review', '*issue*.json'):
            observations.append({'path': path, 'data': clean(self.read(path, warnings=warnings))})
        evidence = []
        for pattern in ('*/manifest.json', '*/*/manifest.json'):
            for path in self.glob(base + '/inputs/visual-audit', pattern)[:30]:
                m = self.read(path)
                for row in m.get('instances', [])[:40]:
                    for page in row.get('pages', [])[:4]:
                        relative = page.get('path') or page.get('id')
                        if relative and Path(relative).suffix.lower() in MEDIA:
                            evidence.append({'instance': row.get('id'), 'frame': page.get('frame'), 'pts': page.get('pts'),
                                             'asset': self.asset(str(Path(path).parent / relative).replace('\\', '/'))})
        timing = [self.read(p) for p in self.glob(f'state/timing/{task}', '*.json')]
        stages = {}
        for event in timing:
            row = stages.setdefault(event.get('stage', 'unknown'), {'calls': 0, 'seconds': 0, 'failures': 0})
            row['calls'] += 1
            row['seconds'] += event.get('seconds', 0) or 0
            row['failures'] += event.get('status') != 'completed'
        task_data.update({'versions': versions, 'items': items, 'speech': clean(inv.get('speech_segments', [])),
                          'audio': clean(inv.get('audio', {})), 'media_info': clean(read('analysis/media.json')),
                          'plan': {'id': plan.get('id'), 'mode': plan.get('mode'), 'segments': clean(plan.get('segments', []))},
                          'knowledge': clean(plan.get('knowledge', [])), 'source_references': clean(plan.get('source_references', [])),
                          'knowledge_advisories': clean(plan.get('knowledge_advisories', [])),
                          'codex_packets': tasks, 'codex_results': results, 'knowledge_usage': usage,
                          'jobs': [clean({k: j.get(k) for k in ('id', 'state', 'task_id', 'model', 'estimated_credits', 'credits_consumed', 'error', 'created_at', 'updated_at')}) for j in jobs],
                          'review': clean(read('review/fast-review.json') or read('review/review.json')),
                          'quality': clean(quality), 'observations': observations, 'evidence': evidence,
                          'timing': stages, 'binding_note': '记录用于导航；页面不重新执行 quality 或签署验收。阶段耗时含嵌套，不能直接相加。'})
        task_data['revision'] = digest(task_data)
        return task_data

    def detail(self, task):
        warnings = []
        versions = [v for v in self.versions(warnings) if v['origin_run_id'] == task]
        value = self._task(task, versions, True)
        value['warnings'] += warnings
        return value

    def knowledge(self):
        entries = []
        for relative, kind in [('knowledge/index.json', 'method'), ('knowledge/cases/index.json', 'reference'),
                               ('knowledge/candidates/index.json', 'candidate')]:
            for entry in self.read(relative).get('entries', []):
                e = clean(entry)
                e['kind'] = kind
                e['key'] = kind + ':' + str(e.get('id') or e.get('path'))
                entries.append(e)
        return {'entries': entries, 'counts': dict(Counter(e['kind'] for e in entries)),
                'candidate_states': self.read('knowledge/candidates/index.json').get('counts', {})}

    def document(self, relative):
        path = self.path(relative)
        if Path(relative).parts[0] not in {'knowledge', 'agent'} or path.suffix.lower() not in {'.md', '.json'}:
            raise ValueError('Only project knowledge and contract text is available')
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError('Document exceeds read limit')
        text = path.read_text(encoding='utf-8-sig')
        if path.suffix.lower() == '.json':
            text = json.dumps(clean(json.loads(text)), ensure_ascii=False, indent=2)
        # Long bodies are returned as bounded plain text; never evaluated as HTML.
        return {'path': relative, 'sha256': self.sha(relative), 'text': clean(text)}

    def snapshot(self):
        warnings = []
        versions = self.versions(warnings)
        names = {v['origin_run_id'] for v in versions if v.get('origin_run_id')}
        names.update(Path(p).parent.name for p in self.glob('runs', '*/run.json'))
        tasks = []
        for task in sorted(names):
            try:
                tasks.append(self._task(task, [v for v in versions if v['origin_run_id'] == task]))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                tasks.append({'id': task, 'state': 'unavailable', 'state_label': '记录需检查', 'quality_state': 'invalid',
                              'next_action': '任务记录暂时无法读取；其他任务仍可查看', 'target_language': '—',
                              'warnings': [{'message': type(exc).__name__}], 'archived': False})
        tasks.sort(key=lambda r: r.get('updated_at') or '', reverse=True)
        budget_rows = []
        for path in self.glob('state/budgets', '*.json'):
            if path.endswith('/index.json'):
                continue
            b = self.read(path, warnings=warnings)
            if not b.get('id'):
                continue
            reservations = b.get('reservations', {})
            rows = list(reservations.values()) if isinstance(reservations, dict) else reservations
            budget_rows.append({'id': b['id'], 'limit': b.get('credit_limit'),
                                'reserved_or_billed': sum(r.get('reserved_credits', 0) or 0 for r in rows),
                                'unknown': sum(r.get('actual_credits') is None for r in rows),
                                'scope': clean(b.get('scope')), 'path': path})
        locks = []
        for path in self.glob('state/resources', '*.lock'):
            try:
                locks.append({'name': Path(path).name, 'owner': self.path(path).read_text()[:80]})
            except OSError:
                pass
        knowledge = self.knowledge()
        settings = self.read('config/resources.local.json')
        value = {'tasks': tasks, 'stats': {'tasks': len(tasks), 'outputs': sum(bool(t.get('output_available')) for t in tasks),
                 'needs_attention': sum(t['quality_state'] in {'issues', 'revise', 'hold', 'invalid', 'stale'} or bool(t.get('warnings')) for t in tasks),
                 'active_records': sum(not t.get('archived') for t in tasks)},
                 'knowledge_counts': knowledge['counts'], 'budgets': budget_rows,
                 'resources': {'max_heavy_jobs': settings.get('max_heavy_jobs', 1), 'locks': locks,
                               'scope': '锁只表示记录中的占用，不证明进程存活；资源忙不等于已排队。'},
                 'routing': clean(self.read('config/model-routing.json')),
                 'policy': {k: self.read('config/workspace.json').get(k) for k in ('default_delivery_mode', 'output_policy')},
                 'maintenance_policy': clean(self.read('config/maintenance.json')),
                 'warnings': warnings, 'read_only': True, 'refresh_seconds': 5,
                 'scope': '本地记录自动刷新；不查询供应商、不执行制作、不改写任务或账本。'}
        value['revision'] = digest(value)
        value['read_at'] = now()
        return value
