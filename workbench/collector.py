"""Evidence-only project adapter and resident local collector.

Never queries providers, changes production records, wakes chats or spends credits.
Only ledger state is written. Run/batch membership and source hashes anchor links.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from video_localizer.ledger import Ledger, digest, now, seconds, stamp
from store import Store, clean

CODE = re.compile(r'(?<![A-Za-z0-9])([A-Za-z]{2,8}-\d{8}-\d{3})(?!\d)')
UUID = re.compile(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}')


def minimum(values):
    return min((v for v in map(stamp, values) if v), key=seconds, default=None)


def maximum(values):
    return max((v for v in map(stamp, values) if v), key=seconds, default=None)


def collect(store, ledger):
    snapshot = store.snapshot()
    warnings = list(snapshot['warnings'])
    cache, source_records = ledger.cached_records(), []
    def read_record(path):
        value = store.read(path, warnings=warnings)
        if not isinstance(value, dict) or not value:
            if path in cache:
                warnings.append({'path':path,'message':'使用上次有效快照，当前来源缺失或损坏'})
            return cache.get(path, {})
        # Persist only fields used by the ledger, without provider payloads/URLs.
        if path.startswith('state/fireplay/'):
            snap = value.get('snapshot', {})
            safe = {k:value.get(k) for k in ('code','requirement_id','content_version','targets','created_at','budget','refreshed_at','blockers','chat')}
            safe['snapshot'] = {'row': {k:snap.get('row',{}).get(k) for k in ('createdAt','status','title')}, 'brief':{'title':snap.get('brief',{}).get('title')}}
            safe['videos'] = [{k:v.get(k) for k in ('index','title','source','targets','members','chat','batch')} for v in value.get('videos',[])]
        elif path.startswith('state/budgets/'):
            safe = {k:value.get(k) for k in ('id','created_at','authorization_ref','runs')}
        else:
            safe = {k:value.get(k) for k in ('id','source_sha256','request_budget','targets','members','created_at')}
        source_records.append((path,safe))
        return value
    versions = store.versions(warnings)
    by_run = {t['id']: t for t in snapshot['tasks']}
    packages = defaultdict(list)
    for version in versions:
        packages[version['origin_run_id']].append(version)
    facts = {}
    for run, task in by_run.items():
        try:
            base, _ = store._base(run, packages[run])
            facts[run] = {'base': base, 'request': store.read(base+'/inputs/request.json'),
                          'fireplay': store.read(base+'/inputs/fireplay.json'),
                          'completion': store.read(base+'/outputs/completion.json'),
                          'delivery': store.read(base+'/outputs/delivery.json')}
        except (OSError, ValueError):
            facts[run] = {}
    budgets = {}
    def paths(area, pattern):
        return sorted(set(store.glob(area,pattern)) | {p for p in cache if p.startswith(area+'/')})
    for path in paths('state/budgets', '*.json'):
        value = read_record(path)
        if value.get('id'):
            budgets[value['id']] = value
    batches = [read_record(p) for p in paths('state/batches', '*.json')]
    reqs, tasks, run_links, source_links = {}, {}, defaultdict(set), defaultdict(set)
    threads = store.read('state/ledger/threads.json')
    thread_rows = threads.get('threads', [])
    folder_names = store.read('state/delivery-folders.json').get('sources', {})

    def request(identifier, code, evidence, **kwargs):
        if identifier not in reqs:
            reqs[identifier] = {'id': identifier, 'code': code, 'title': code, 'countable': True,
                                'origin': 'local', 'received_at': None, 'accepted_at': None,
                                'platform_created_at': None, 'blockers': [], 'evidence': [], 'budget_ids': [],
                                'videos': [], 'threads': [], 'platform_status': None, 'external': [], **kwargs}
        r = reqs[identifier]
        if evidence not in r['evidence']: r['evidence'].append(evidence)
        return r

    def add_video(req, identifier, sha, title, targets, thread=None, evidence=None):
        mapped_title = folder_names.get(sha)
        if mapped_title and mapped_title.upper().startswith(req['code'].upper()):
            title = mapped_title
        video = next((v for v in req['videos'] if v['id'] == identifier), None)
        if video is None:
            video = {'id': identifier, 'source_sha256': sha, 'title': title, 'targets': sorted(set(targets)),
                     'thread': thread, 'evidence': evidence}
            req['videos'].append(video)
        else:
            video['targets'] = sorted(set(video['targets']) | set(targets))
        if sha:
            source_links[(req['id'], sha)].add(identifier)
        # Exact titles are a secondary association, never a production heartbeat.
        if not video.get('thread'):
            exact = [t for t in thread_rows if t.get('title', '').upper() == title.upper()]
            if len(exact) == 1:
                video['thread'] = {**exact[0], 'threadId': exact[0]['id'], 'evidence': 'state/ledger/threads.json'}
        if video.get('thread'):
            tid = video['thread'].get('threadId') or video['thread'].get('id')
            if tid and not any(t.get('threadId') == tid for t in req['threads']):
                req['threads'].append({**video['thread'], 'threadId': tid})
        for locale in video['targets']:
            key = req['id'] + '|' + identifier + '|' + locale
            tasks.setdefault(key, {'id': key, 'requirement_id': req['id'], 'video_id': identifier,
                                    'locale': locale, 'source_sha256': sha, 'runs': [], 'versions': []})
        return video

    def link(run, req, video_id, locale, evidence):
        key = req['id']+'|'+video_id+'|'+locale
        if key not in tasks:
            return
        task = by_run.get(run)
        dest = tasks[key]
        if task and (task.get('source_sha256') != dest.get('source_sha256') or task.get('target_language') != locale):
            warnings.append({'path': run, 'message': '成员源哈希或语言不匹配，未关联'})
            return
        if run not in dest['runs']:
            dest['runs'].append(run)
            run_links[run].add(key)
        dest.setdefault('link_evidence', []).append(evidence)

    for manual in ledger.registrations():
        r=request('manual:'+manual['code'],manual['code'],'ledger_registration',origin='manual',
                  title=manual.get('title') or manual['code'],received_at=manual.get('received_at'),
                  accepted_at=manual.get('registered_at'))
        for index,v in enumerate(manual['videos'],1):
            add_video(r,'video:'+str(index),v['source_sha256'],v.get('title') or manual['code']+'-'+str(index),v['targets'],evidence=manual['reason'])

    # Registered Fireplay scope is authoritative even before production exists.
    fireplay_by_code = {}
    for path in paths('state/fireplay', '*/request.json'):
        f = read_record(path)
        if not f.get('requirement_id') or not f.get('code'):
            continue
        row = f.get('snapshot', {}).get('row', {})
        brief = f.get('snapshot', {}).get('brief', {})
        r = request('fireplay:'+f['requirement_id'], f['code'], path, origin='fireplay',
                    title=brief.get('title') or row.get('title') or f['code'],
                    platform_created_at=stamp(row.get('createdAt')), received_at=stamp(f.get('created_at')),
                    platform_refreshed_at=stamp(f.get('refreshed_at')), platform_status=row.get('status'),
                    blockers=f.get('blockers', []), content_version=f.get('content_version'))
        fireplay_by_code[f['code'].upper()] = r
        if f.get('budget'):
            r['budget_ids'].append(f['budget'])
            r['accepted_at'] = stamp(budgets.get(f['budget'], {}).get('created_at'))
        for v in f.get('videos', []):
            source = v.get('source') or {}
            video_id = 'video:'+str(v['index'])
            thread = v.get('chat') or f.get('chat')
            add_video(r, video_id, source.get('sha256'), v.get('title') or f['code'], v.get('targets', f.get('targets', [])), thread, path)
            for run, locale in zip(v.get('members') or [], v.get('targets') or f.get('targets') or []):
                link(run, r, video_id, locale, path)
        for outbox_path in store.glob(str(Path(path).parent), '**/outbox.json'):
            outbox = store.read(outbox_path, warnings=warnings)
            r['external'].append({'path': outbox_path, 'state': outbox.get('state'),
                                  'operations': [{k: op.get(k) for k in ('id', 'phase', 'state', 'dispatched_at')}
                                                 for op in outbox.get('operations', {}).values()]})

    # Historical batches use a separate explicit authorization and source binding.
    # A filename resembling a requirement is insufficient on its own.
    for batch in batches:
        budget = budgets.get(batch.get('request_budget'), {})
        matches = {m.upper() for m in CODE.findall(str(budget.get('authorization_ref') or ''))}
        named = CODE.match(str(batch.get('id') or ''))
        confirmed = named and named.group(1).upper() in matches and len(matches) == 1
        code = named.group(1).upper() if confirmed else None
        identifier = ('local:'+code) if code else 'budget:'+str(batch.get('request_budget') or batch.get('id'))
        bound = [r for r in reqs.values() if batch.get('request_budget') in r['budget_ids']]
        r = bound[0] if len(bound)==1 else (fireplay_by_code.get(code) if code else None)
        r = r or request(identifier, code or batch.get('id', identifier), 'state/batches/'+str(batch.get('id'))+'.json',
                         title=code or batch.get('id', identifier), received_at=stamp(budget.get('created_at')),
                         accepted_at=stamp(budget.get('created_at')),
                         association='batch+budget_authorization+source' if confirmed else 'budget+batch_membership')
        if batch.get('request_budget') and batch['request_budget'] not in r['budget_ids']:
            r['budget_ids'].append(batch['request_budget'])
        r['received_at'] = minimum([r.get('received_at'), budget.get('created_at')])
        sha = batch.get('source_sha256')
        existing = source_links.get((r['id'], sha), set())
        if len(existing) > 1:
            warnings.append({'path': batch.get('id'), 'message': '同需求多个原片具有相同哈希，需人工关联批次'})
            continue
        video_id = next(iter(existing)) if existing else 'source:'+str(sha)
        scope_video=next((v for v in r['videos'] if v['id']==video_id),None)
        targets = scope_video['targets'] if r['origin']=='fireplay' and scope_video else batch.get('targets', [])
        add_video(r, video_id, sha, batch.get('id') or r['code'], targets, evidence='state/batches/'+str(batch.get('id'))+'.json')
        for run, locale in zip(batch.get('members', []), batch.get('targets', [])):
            link(run, r, video_id, locale, 'batch_membership:'+str(batch.get('id')))

    # Budget's exact run->source map associates retry runs without name guessing.
    for r in list(reqs.values()):
        for bid in r['budget_ids']:
            budget = budgets.get(bid, {})
            r['accepted_at'] = minimum([r.get('accepted_at'), budget.get('created_at')])
            for run, sha in (budget.get('runs') or {}).items():
                choices = source_links.get((r['id'], sha), set())
                if len(choices) == 1 and run in by_run:
                    video = next(iter(choices))
                    link(run, r, video, by_run[run].get('target_language'), 'budget_runs:'+bid)

    # Explicit run pointers and management links precede orphan classification.
    for run, f in facts.items():
        pointer = f.get('fireplay', {})
        if pointer.get('requirement_id'):
            r = reqs.get('fireplay:'+pointer['requirement_id'])
            if r:
                link(run, r, 'video:'+str(pointer.get('video_index')), by_run[run].get('target_language'), f.get('base','')+'/inputs/fireplay.json')
    for entry in ledger.links():
        r = reqs.get(entry['requirement_id'])
        conflicts = [tasks[k]['requirement_id'] for k in run_links.get(entry['run_id'],[]) if tasks[k]['requirement_id']!=entry['requirement_id']]
        if conflicts:
            warnings.append({'path':entry['run_id'],'message':'人工关联与现有明确归属冲突，未重复计数'})
        elif r:
            link(entry['run_id'], r, entry['video_id'], entry['locale'], entry['evidence'])
    # Existing user-confirmed delivery naming plus the verified manifest is an
    # independent binding for archived repair runs absent from old budget maps.
    for run,t in by_run.items():
        if run_links.get(run): continue
        mapped = folder_names.get(t.get('source_sha256'))
        if not mapped: continue
        verified = [v for v in packages.get(run,[]) if v['usable'] and v['package'].startswith('outputs/'+mapped+'/')]
        if not verified: continue
        matches = [(r,vid) for r in reqs.values() for vid in source_links.get((r['id'],t.get('source_sha256')),set())
                   if r['code'].upper()==mapped.upper() or mapped.upper().startswith(r['code'].upper()+'-')]
        if len(matches)==1:
            r,vid=matches[0]
            link(run,r,vid,t.get('target_language'),'state/delivery-folders.json + verified delivery manifest:'+verified[-1]['package'])
    for run, t in by_run.items():
        if run_links.get(run): continue
        r = request('unlinked:'+run, run, 'run_or_delivery:'+run, countable=False, origin='unlinked')
        v = add_video(r, 'unlinked', t.get('source_sha256'), run, [t.get('target_language', 'unknown')])
        link(run, r, v['id'], t.get('target_language', 'unknown'), 'unresolved')

    # Evidence-gated completed versions; merely having a candidate is not output.
    for task in tasks.values():
        states, created = [], []
        eligible_versions = []
        for run in task['runs']:
            t, f = by_run.get(run, {}), facts.get(run, {})
            states.append(t)
            created.append(t.get('created_at'))
            for version in packages.get(run, []):
                if not version['usable'] or version['status'] not in {'delivered', 'delivered_with_issues'}:
                    continue
                base = version['package']+'/payload'
                req = store.read(base+'/inputs/request.json')
                completion = store.read(base+'/outputs/completion.json')
                inv = store.read(base+'/analysis/inventory.json')
                if req.get('require_target_audio') is True and inv.get('audio', {}).get('has_speech') is True and completion.get('speech_mode') not in {'dubbed', 'translated'}:
                    # Strict delivery without finalization has its evidence in narration plan/quality.
                    if version['status'] != 'delivered': continue
                delivered = store.read(base+'/outputs/delivery.json')
                at = stamp(completion.get('completed_at')) or stamp(delivered.get('delivered_at')) or stamp(version.get('archived_at'))
                eligible_versions.append({'run_id': run, 'sha256': version['video_sha256'], 'at': at,
                                          'package': version['package'], 'held': version['held'],
                                          'status': version['status'], 'quality': 'hold' if version['held'] else 'pass' if version['status']=='delivered' and version['technical_decision']=='pass' else 'issues',
                                          'url': version['media']['url']})
        eligible_versions.sort(key=lambda v: seconds(v['at']) or 0)
        current = eligible_versions[-1] if eligible_versions else None
        task.update(versions=eligible_versions, created_at=minimum(created),
                    complete_at=current['at'] if current else None,
                    first_complete_at=eligible_versions[0]['at'] if eligible_versions else None,
                    quality=current['quality'] if current else 'not_reviewed',
                    current=current, states=[{'run_id': s.get('id'), 'state': s.get('state'), 'quality': s.get('quality_state')} for s in states],
                    last_activity_at=maximum([s.get('updated_at') for s in states]))
        # Any later in-progress run/candidate keeps this language open while its
        # earlier completed milestone remains inspectable.
        if current:
            newer = [s for s in states if s.get('state') not in {'delivered', 'delivered_with_issues', 'historical_reference'}
                     and seconds(s.get('updated_at')) and seconds(s['updated_at']) > seconds(current['at'])]
            if newer:
                task.update(complete_at=None, quality='not_reviewed', active_revision=True)

    for r in reqs.values():
        own = [t for t in tasks.values() if t['requirement_id'] == r['id']]
        r['scope'] = sorted([{'video_id': v['id'], 'source_sha256': v['source_sha256'], 'targets': sorted(v['targets'])} for v in r['videos']], key=lambda v:v['video_id'])
        r['scope_id'] = digest([r.get('content_version'), r['scope']])
        r.update(task_count=len(own), output_count=sum(bool(t['complete_at']) for t in own),
                 quality_count=sum(t['quality']=='pass' and bool(t['complete_at']) for t in own),
                 issue_count=sum(t['quality'] in {'issues','hold'} for t in own),
                 run_count=sum(len(t['runs']) for t in own), video_count=len(r['videos']),
                 complete_at=maximum([t['complete_at'] for t in own]) if own and all(t['complete_at'] for t in own) else None,
                 first_scope_output_at=maximum([t['first_complete_at'] for t in own]) if own and all(t['first_complete_at'] for t in own) else None,
                 first_started_at=minimum([t['created_at'] for t in own]),
                 last_activity_at=maximum([t['last_activity_at'] for t in own]))
        r['state'] = 'complete' if r['complete_at'] else 'partial' if r['output_count'] else 'needs_info' if r['blockers'] else 'executing' if any(t['runs'] for t in own) else 'queued' if r.get('accepted_at') else 'discovered'
        r['stage_counts'] = {}
        for task in own:
            stage = task['states'][-1]['state'] if task['states'] else 'not_started'
            r['stage_counts'][stage] = r['stage_counts'].get(stage,0)+1
        r['source_present'] = True
    signatures, events = [], []
    known = ledger.signatures()
    # Incremental timing import. Do not sum nested durations in dashboard KPIs.
    for area, pattern, is_timing in [('state/timing', '*/*.json', True), ('state/ledger/inbox', '*.json', False)]:
        for path in store.glob(area, pattern):
            stat = store.path(path).stat()
            signature = f'{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ctime_ns}'
            if known.get(path) == signature: continue
            value = store.read(path, warnings=warnings)
            if not value.get('id'): continue
            run = value.get('run') if is_timing else value.get('run_id')
            keys = run_links.get(run, set())
            task = tasks[next(iter(keys))] if len(keys)==1 else {}
            data = ({k:value.get(k) for k in ('stage','status','started_at','ended_at','seconds','parent_id')} if is_timing else value.get('data', {}))
            events.append({'identifier': ('timing:' if is_timing else 'runtime:')+value['id'],
                           'kind': 'stage_recorded' if is_timing else value.get('kind', 'executor_activity'),
                           'data': clean({**data, 'evidence': path}), 'requirement': task.get('requirement_id'),
                           'task': task.get('id'), 'run': run,
                           'occurred': value.get('ended_at') if is_timing else value.get('occurred_at')})
            signatures.append((path, signature))
    health = {'last_success_at': now(), 'scope': 'registered_local_requests_batches_runs_outputs',
              'complete': not warnings, 'warnings': warnings[:100], 'warning_count': len(warnings),
              'fireplay_mode': 'registered_snapshots',
              'fireplay_last_snapshot_at': maximum([r.get('platform_refreshed_at') for r in reqs.values()]),
              'threads_observed_at': threads.get('observed_at'), 'tasks_scanned': len(by_run),
              'requirements_imported': sum(r['countable'] for r in reqs.values()),
              'unlinked_runs': sum(not r['countable'] for r in reqs.values())}
    return list(reqs.values()), list(tasks.values()), health, events, signatures, source_records


class Collector:
    def __init__(self, root, store=None, interval=15):
        self.root = Path(root).resolve()
        self.store = store or Store(root)
        self.ledger = Ledger(root)
        self.interval = interval
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.thread = None
        self.error = None
        self.last_tick = None

    def sync(self, preview=False):
        with self.lock:
            rows, tasks, health, events, signatures, source_records = collect(self.store, self.ledger)
            if not preview:
                self.ledger.reconcile(rows, tasks, health, events, signatures, source_records)
                self.estimate(rows, tasks)
                self.last_tick, self.error = now(), None
            return {'requirements': rows, 'tasks': tasks, 'health': health, 'events': len(events), 'preview': preview}

    def estimate(self, requirements, tasks):
        settings = self.store.read('config/ledger.json')
        if settings.get('auto_eta') is not True:
            return
        current = {r['id']: r for r in self.ledger.view()['requirements']}
        for source in requirements:
            req = current[source['id']]
            if not req.get('countable') or req.get('complete_at') or not req.get('accepted_at') or req.get('block_reason') or req.get('blockers') or not all(v.get('source_sha256') for v in req['videos']):
                continue
            unfinished = [t for t in tasks if t['requirement_id']==req['id'] and not t['complete_at']]
            targets = [('*', unfinished, req.get('latest_eta'))]
            targets.extend((v['id'],[t for t in unfinished if t['video_id']==v['id']],v.get('latest_eta')) for v in req['videos'])
            for video_id,own,prior in targets:
                if not own: continue
                signature = digest([[t['id'],t['complete_at'],sorted(s['state'] or '' for s in t['states'])] for t in own])
                if prior and (prior['data'].get('basis')!='rule_estimate' or prior['data'].get('progress_signature')==signature):
                    continue
                low,high=settings.get('queue_allowance_minutes',[0,60])
                sources=set()
                for task in own:
                    review_only=any(s['state'] in {'needs_review','ready_to_deliver'} for s in task['states'])
                    minutes=settings.get('review_only_minutes',[2,5]) if review_only else settings.get('per_locale_minutes',[4,12])
                    low+=minutes[0];high+=minutes[1]
                    if not review_only:sources.add(task['video_id'])
                shared=settings.get('shared_source_minutes',[8,25])
                low+=len(sources)*shared[0];high+=len(sources)*shared[1]
                anchor=datetime.fromisoformat(now())
                self.ledger.action('eta', {'requirement_id':req['id'],'video_id':video_id,'owner':'ledger bootstrap estimator',
                    'lower_at':(anchor+timedelta(minutes=low)).isoformat(), 'upper_at':(anchor+timedelta(minutes=high)).isoformat(),
                    'basis':'rule_estimate','reason':'首次接入时估计剩余工作' if not prior else '有新阶段证据，更新剩余工作估计',
                    'rule_version':settings.get('eta_rule_version','bootstrap-v1'), 'progress_signature':signature,
                    'assumptions':settings.get('assumptions','未校准规则估算')},
                    'autoeta-'+digest([req['id'],req['scope_id'],video_id,signature,settings.get('eta_rule_version'),prior['id'] if prior else None])[:48])

    def start(self):
        def loop():
            while not self.stop.is_set():
                try: self.sync()
                except Exception as exc:
                    self.error = type(exc).__name__  # never leak records or secrets
                self.stop.wait(self.interval)
        self.thread = threading.Thread(target=loop, name='ledger-collector', daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread: self.thread.join(timeout=10)

    def view(self):
        result = self.ledger.view()
        result['collector'] = {'alive': bool(self.thread and self.thread.is_alive()), 'last_tick_at': self.last_tick, 'pid':os.getpid(),
                               'error': self.error, 'interval_seconds': self.interval}
        result['metrics'] = self.ledger.metrics(result['requirements'])
        return result
