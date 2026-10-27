"""Durable operational ledger. Facts remain in production records; no model calls.

SQLite transactions serialize claims and append-only management events. Views are
reconciled from evidence, never approvals. Importing this module has no side effects.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def stamp(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return dt.astimezone(timezone.utc).isoformat() if dt.tzinfo else None
    except (ValueError, TypeError):
        return None


def seconds(value):
    value = stamp(value)
    return datetime.fromisoformat(value).timestamp() if value else None


def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(packed(value).encode()).hexdigest()


class Conflict(ValueError):
    pass


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS requirements(id TEXT PRIMARY KEY, revision INTEGER NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS scopes(requirement_id TEXT NOT NULL, scope_id TEXT NOT NULL, observed_at TEXT NOT NULL,
 data TEXT NOT NULL, PRIMARY KEY(requirement_id,scope_id));
CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, requirement_id TEXT NOT NULL, video_id TEXT NOT NULL,
 locale TEXT NOT NULL, data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS tasks_requirement ON tasks(requirement_id);
CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, requirement_id TEXT, task_id TEXT, run_id TEXT,
 kind TEXT NOT NULL, occurred_at TEXT, recorded_at TEXT NOT NULL, data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS events_requirement ON events(requirement_id,recorded_at);
CREATE INDEX IF NOT EXISTS events_run ON events(run_id);
CREATE TABLE IF NOT EXISTS estimates(id TEXT PRIMARY KEY, requirement_id TEXT NOT NULL, scope_id TEXT NOT NULL,
 created_at TEXT NOT NULL, lower_at TEXT NOT NULL, upper_at TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS claims(requirement_id TEXT NOT NULL, video_id TEXT NOT NULL, owner TEXT NOT NULL, session TEXT NOT NULL,
 heartbeat_at TEXT NOT NULL, lease_until TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(requirement_id,video_id));
CREATE TABLE IF NOT EXISTS operations(id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, result TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS links(run_id TEXT PRIMARY KEY, requirement_id TEXT NOT NULL, video_id TEXT NOT NULL,
 locale TEXT NOT NULL, evidence TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS source_files(path TEXT PRIMARY KEY, signature TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS source_records(path TEXT PRIMARY KEY,data TEXT NOT NULL);
"""


class Ledger:
    def __init__(self, root):
        self.root = Path(root).resolve()
        folder = self.root / 'state/ledger'
        folder.mkdir(parents=True, exist_ok=True)
        if not folder.resolve().is_relative_to(self.root):
            raise ValueError('Ledger must stay in workspace')
        self.path = folder / 'ledger.sqlite3'
        if self.path.is_symlink():
            raise ValueError('Ledger cannot be a symlink')
        with self.connection() as db:
            db.executescript(SCHEMA)
            db.execute("INSERT OR IGNORE INTO meta VALUES('schema_version','1')")

    @contextmanager
    def connection(self, write=False):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA busy_timeout=15000')
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=FULL')
        try:
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def event(db, identifier, kind, data, requirement=None, task=None, run=None, occurred=None):
        encoded = packed(data)
        previous = db.execute('SELECT kind,data FROM events WHERE id=?', (identifier,)).fetchone()
        if previous:
            if previous['kind'] != kind or previous['data'] != encoded:
                raise Conflict('Event ID already exists with different evidence')
            return False
        db.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,?)',
                   (identifier, requirement, task, run, kind, stamp(occurred), now(), encoded))
        return True

    def reconcile(self, requirements, tasks, health, file_events=(), signatures=(), source_records=()):
        """Atomic projection refresh. Missing sources never delete historical facts."""
        with self.connection(True) as db:
            for req in requirements:
                old = db.execute('SELECT * FROM requirements WHERE id=?', (req['id'],)).fetchone()
                old_data = json.loads(old['data']) if old else {}
                req['first_seen_at'] = old_data.get('first_seen_at') or now()
                # Preserve source-bound first completion for each immutable scope.
                scope = req['scope_id']
                prior = db.execute('SELECT data FROM scopes WHERE requirement_id=? AND scope_id=?', (req['id'], scope)).fetchone()
                scope_data = json.loads(prior['data']) if prior else {'definition': req['scope']}
                known = [v for v in (req.get('first_scope_output_at'),scope_data.get('first_complete_at')) if v]
                if known:
                    scope_data['first_complete_at'] = min(known,key=seconds)
                req['scope_first_complete_at'] = scope_data.get('first_complete_at')
                known = [v for v in (old_data.get('first_complete_at'),scope_data.get('first_complete_at')) if v]
                req['first_complete_at'] = min(known,key=seconds) if known else None
                # A manual ready/block event remains separate from source facts.
                for field in ('ready_at', 'manual_phase', 'block_reason', 'block_kind'):
                    if field in old_data:
                        req[field] = old_data[field]
                revision = old['revision'] if old else 0
                if old_data != req:
                    revision += 1
                    db.execute('INSERT OR REPLACE INTO requirements VALUES(?,?,?)', (req['id'], revision, packed(req)))
                    self.event(db, 'projection:' + digest([req['id'], revision, req]), 'reconciled',
                               {'revision': revision, 'scope_id': scope, 'state': req['state'], 'evidence': req.get('evidence', [])}, req['id'])
                db.execute('INSERT OR REPLACE INTO scopes VALUES(?,?,?,?)', (req['id'], scope, now(), packed(scope_data)))
            for task in tasks:
                db.execute('INSERT OR REPLACE INTO tasks VALUES(?,?,?,?,?)',
                           (task['id'], task['requirement_id'], task['video_id'], task['locale'], packed(task)))
            present = {r['id'] for r in requirements}
            for row in db.execute('SELECT * FROM requirements').fetchall():
                if row['id'] not in present:
                    previous = json.loads(row['data'])
                    previous['source_present'] = False
                    previous['resolved'] = previous.get('origin') == 'unlinked'
                    db.execute('UPDATE requirements SET data=? WHERE id=?', (packed(previous),row['id']))
            for entry in file_events:
                self.event(db, **entry)
            assignments = {}
            for task in tasks:
                for run in task['runs']:
                    assignments.setdefault(run,[]).append(task)
            for run, matches in assignments.items():
                if len(matches)==1:
                    task=matches[0]
                    db.execute('UPDATE events SET requirement_id=?,task_id=? WHERE run_id=? AND (requirement_id IS NOT ? OR task_id IS NOT ?)',
                               (task['requirement_id'],task['id'],run,task['requirement_id'],task['id']))
            for path, signature in signatures:
                db.execute('INSERT OR REPLACE INTO source_files VALUES(?,?)', (path, signature))
            for path, record in source_records:
                db.execute('INSERT OR REPLACE INTO source_records VALUES(?,?)', (path, packed(record)))
            db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', ('sync', packed(health)))

    def signatures(self):
        with self.connection() as db:
            return dict(db.execute('SELECT path,signature FROM source_files').fetchall())

    def cached_records(self):
        with self.connection() as db:
            return {r['path']: json.loads(r['data']) for r in db.execute('SELECT * FROM source_records')}

    def registrations(self):
        with self.connection() as db:
            return [json.loads(r['value']) for r in db.execute("SELECT value FROM meta WHERE key LIKE 'registration:%'")]

    def links(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute('SELECT * FROM links')]

    def action(self, action, spec, operation_id, expected_revision=None):
        if not isinstance(spec, dict) or not re.fullmatch(r'[A-Za-z0-9_-]{8,120}', str(operation_id)):
            raise ValueError('Operation requires a stable ID and an object')
        request_hash = digest([action, spec, expected_revision])
        with self.connection(True) as db:
            old_op = db.execute('SELECT * FROM operations WHERE id=?', (operation_id,)).fetchone()
            if old_op:
                if old_op['request_hash'] != request_hash:
                    raise Conflict('Operation ID reused with different input')
                return json.loads(old_op['result'])
            if action == 'register':
                code = str(spec.get('code') or '').strip().upper()
                if not re.fullmatch(r'[A-Z0-9][A-Z0-9_.-]{2,79}',code) or not spec.get('reason'):
                    raise ValueError('Registration requires code and real request evidence')
                videos = spec.get('videos')
                if not isinstance(videos,list) or not videos:
                    raise ValueError('Registration requires source videos and languages')
                for v in videos:
                    if not isinstance(v,dict) or not re.fullmatch('[0-9a-f]{64}',str(v.get('source_sha256') or '')) or not v.get('targets'):
                        raise ValueError('Each video needs a source SHA256 and targets')
                    if len(v['targets']) != len(set(v['targets'])) or any(not re.fullmatch(r'[a-zA-Z]{2,3}(?:-[A-Za-z0-9]{2,8})*',t) for t in v['targets']):
                        raise ValueError('Use distinct canonical locale tags')
                key = 'registration:'+code
                prior = db.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
                record = {**spec,'code':code,'received_at':stamp(spec.get('received_at')) or now(), 'registered_at':now()}
                if prior:
                    raise Conflict('Requirement already registered; scope revision needs explicit reconciliation')
                if any(json.loads(r['data'])['code'].upper()==code for r in db.execute('SELECT data FROM requirements')):
                    raise Conflict('This code already has an existing requirement')
                db.execute('INSERT INTO meta VALUES(?,?)',(key,packed(record)))
                self.event(db,'management:'+operation_id,'registered',record,'manual:'+code,occurred=now())
                result={'ok':True,'operation_id':operation_id,'requirement_id':'manual:'+code}
                db.execute('INSERT INTO operations VALUES(?,?,?)',(operation_id,request_hash,packed(result)))
                return result
            identifier = spec.get('requirement_id')
            row = db.execute('SELECT * FROM requirements WHERE id=?', (identifier,)).fetchone()
            if not row:
                raise ValueError('Requirement not found; sync or register it first')
            if expected_revision is not None and expected_revision != row['revision']:
                raise Conflict('Requirement changed; refresh before modifying')
            req = json.loads(row['data'])
            moment = now()
            evidence = str(spec.get('reason') or '').strip()
            if action in {'ready', 'block', 'resume', 'eta', 'link'} and not evidence:
                raise ValueError('A reason/evidence reference is required')
            owner = str(spec.get('owner') or '').strip()
            session = str(spec.get('session') or '').strip()
            if action in {'claim', 'heartbeat', 'release', 'stage'}:
                if not owner or not session or len(owner) > 200 or len(session) > 200:
                    raise ValueError('Owner and session are required')
                video_id = spec.get('video_id') or '*'
                if video_id != '*' and not any(v['id']==video_id for v in req['videos']):
                    raise ValueError('Video not in current scope')
                claim = db.execute('SELECT * FROM claims WHERE requirement_id=? AND video_id=?', (identifier,video_id)).fetchone()
                overlap = db.execute("SELECT * FROM claims WHERE requirement_id=? AND video_id!=? AND (video_id='*' OR ?='*')", (identifier,video_id,video_id)).fetchall()
                if any(seconds(c['lease_until']) > seconds(moment) for c in overlap):
                    raise Conflict('Overlapping requirement/video claim exists')
                if overlap and action=='claim':
                    if not evidence:
                        raise Conflict('Expired overlapping claims require an explicit recovery reason')
                    for other in overlap:
                        db.execute('DELETE FROM claims WHERE requirement_id=? AND video_id=?',(identifier,other['video_id']))
                if claim and (claim['owner'], claim['session']) != (owner, session):
                    # Even after expiry an explicit recovery reason is mandatory.
                    if action != 'claim' or seconds(claim['lease_until']) > seconds(moment) or not evidence:
                        raise Conflict('Another session owns this requirement; reconcile before takeover')
                if action != 'claim' and (not claim or (claim['owner'], claim['session']) != (owner, session)):
                    raise Conflict('Claim this requirement with this session first')
                if action == 'release':
                    db.execute('DELETE FROM claims WHERE requirement_id=? AND video_id=?', (identifier,video_id))
                else:
                    ttl = int(spec.get('lease_seconds', 600))
                    if not 60 <= ttl <= 3600:
                        raise ValueError('Lease must be 60–3600 seconds')
                    lease = (datetime.fromisoformat(moment) + timedelta(seconds=ttl)).isoformat()
                    phase = str(spec.get('stage') or (json.loads(claim['data']).get('stage') if claim else '') or '执行中')
                    db.execute('INSERT OR REPLACE INTO claims VALUES(?,?,?,?,?,?,?)',
                               (identifier, video_id, owner, session, moment, lease, packed({'stage': phase, 'reason': evidence})))
            elif action == 'ready':
                req['ready_at'] = req.get('ready_at') or moment
            elif action == 'block':
                kind = spec.get('kind')
                if kind not in {'user', 'model', 'resource', 'platform', 'unknown'}:
                    raise ValueError('Invalid waiting reason type')
                req.update(block_kind=kind, block_reason=evidence, manual_phase='blocked')
            elif action == 'resume':
                req.update(block_kind=None, block_reason=None, manual_phase=None)
            elif action == 'eta':
                video_id=spec.get('video_id') or '*'
                if video_id!='*' and not any(v['id']==video_id for v in req['videos']):
                    raise ValueError('ETA video not in current scope')
                lower, upper = stamp(spec.get('lower_at')), stamp(spec.get('upper_at'))
                if not lower or not upper or seconds(lower) > seconds(upper) or seconds(upper) < seconds(moment):
                    raise ValueError('ETA needs ordered future bounds with explicit timezones')
                data = {'reason': evidence, 'basis': spec.get('basis') or 'agent_estimate',
                        'assumptions': spec.get('assumptions') or '', 'milestone': 'complete_output',
                        'author': owner or 'local_operator', 'rule_version': spec.get('rule_version') or 'agent-v1',
                        'retrospective': bool(req.get('scope_first_complete_at') and seconds(req['scope_first_complete_at']) <= seconds(moment)),
                        'progress_signature': spec.get('progress_signature'), 'video_id':video_id}
                db.execute('INSERT INTO estimates VALUES(?,?,?,?,?,?,?)',
                           (operation_id, identifier, req['scope_id'], moment, lower, upper, packed(data)))
            elif action == 'link':
                run = spec.get('run_id')
                video = spec.get('video_id')
                locale = spec.get('locale')
                target = db.execute('SELECT data FROM tasks WHERE requirement_id=? AND video_id=? AND locale=?',
                                    (identifier, video, locale)).fetchone()
                if not target or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,180}', str(run)):
                    raise ValueError('Choose an existing video/locale and a valid run')
                task = json.loads(target['data'])
                source = spec.get('source_sha256')
                if task.get('source_sha256') and source != task['source_sha256']:
                    raise ValueError('Source hash does not match this video')
                if not source or not re.fullmatch('[0-9a-f]{64}', source):
                    raise ValueError('Verified source SHA256 is required')
                old = db.execute('SELECT * FROM links WHERE run_id=?', (run,)).fetchone()
                if old and (old['requirement_id'], old['video_id'], old['locale']) != (identifier, video, locale):
                    raise Conflict('Run already linked elsewhere')
                db.execute('INSERT OR REPLACE INTO links VALUES(?,?,?,?,?)', (run, identifier, video, locale, evidence))
            else:
                raise ValueError('Unsupported ledger action')
            self.event(db, 'management:' + operation_id, action, spec, identifier, occurred=moment)
            db.execute('UPDATE requirements SET revision=?,data=? WHERE id=?', (row['revision']+1, packed(req), identifier))
            result = {'ok': True, 'operation_id': operation_id, 'revision': row['revision']+1}
            db.execute('INSERT INTO operations VALUES(?,?,?)', (operation_id, request_hash, packed(result)))
            return result

    def view(self, at=None):
        moment = stamp(at) or now()
        clock = seconds(moment)
        with self.connection() as db:
            requirements = [{**json.loads(r['data']), 'revision': r['revision']} for r in db.execute('SELECT * FROM requirements') if not json.loads(r['data']).get('resolved')]
            claims = {}
            for r in db.execute('SELECT * FROM claims'):
                claims.setdefault(r['requirement_id'], []).append(dict(r))
            estimates = {}
            for r in db.execute('SELECT * FROM estimates ORDER BY created_at,rowid'):
                data=json.loads(r['data'])
                estimates.setdefault((r['requirement_id'], r['scope_id'],data.get('video_id','*')), []).append({**dict(r), 'data': data})
            executors = {}
            for row in db.execute("SELECT requirement_id,run_id,kind,occurred_at,data FROM events WHERE kind LIKE 'executor.%' ORDER BY occurred_at"):
                key = (row['requirement_id'],row['run_id'])
                candidate = {**dict(row),'data':json.loads(row['data'])}
                previous = executors.get(key)
                priority = lambda e:(seconds(e['occurred_at']) or 0,e['kind'] in {'executor.finished','executor.failed'})
                if previous is None or priority(candidate) >= priority(previous):
                    executors[key]=candidate
            sync = db.execute("SELECT value FROM meta WHERE key='sync'").fetchone()
        for req in requirements:
            etas = estimates.get((req['id'], req['scope_id'],'*'), [])
            for video in req['videos']:
                video_etas=estimates.get((req['id'],req['scope_id'],video['id']),[])
                video.update(first_eta=video_etas[0] if video_etas else None,latest_eta=video_etas[-1] if video_etas else None)
            req.update(first_eta=etas[0] if etas else None, latest_eta=etas[-1] if etas else None,
                       eta_changes=max(0, len(etas)-1), claim=None, agent_health='unrecorded')
            req['claims'] = []
            req['executors'] = [{**e,'health': ('finished' if e['kind']=='executor.finished' else 'failed' if e['kind']=='executor.failed' else 'recent' if clock-(seconds(e['occurred_at']) or 0)<=180 else 'unconfirmed')}
                                for (rid,_),e in executors.items() if rid==req['id']]
            for claim in claims.get(req['id'], []):
                age = max(0, clock-seconds(claim['heartbeat_at']))
                health = 'unconfirmed' if age > 600 or clock > seconds(claim['lease_until']) else 'delayed' if age > 180 else 'recent'
                req['claims'].append({**claim, 'data': json.loads(claim['data']), 'health': health})
            if req['claims']:
                req['claim'] = req['claims'][0]
                req['agent_health'] = max((c['health'] for c in req['claims']), key=lambda h:{'recent':0,'delayed':1,'unconfirmed':2}[h])
            req['overdue'] = bool(etas and not req.get('complete_at') and clock > seconds(etas[-1]['upper_at']))
            req['eta_scope'] = 'current_scope'
            if req.get('block_reason'):
                req['state'] = 'blocked'
        requirements.sort(key=lambda r: (not (r.get('overdue') or r.get('block_reason') or r['agent_health']=='unconfirmed'), not r.get('countable'), bool(r.get('complete_at')), r['code']))
        return {'requirements': requirements, 'sync': json.loads(sync['value']) if sync else {}, 'read_at': moment}

    def detail(self, identifier):
        req = next((r for r in self.view()['requirements'] if r['id'] == identifier), None)
        if not req:
            raise ValueError('Requirement not found')
        with self.connection() as db:
            tasks = [json.loads(r['data']) for r in db.execute('SELECT data FROM tasks WHERE requirement_id=?', (identifier,))]
            events = [{**dict(r), 'data': json.loads(r['data'])} for r in db.execute(
                'SELECT * FROM events WHERE requirement_id=? ORDER BY COALESCE(occurred_at,recorded_at) DESC LIMIT 160', (identifier,))]
            estimates = [{**dict(r), 'data': json.loads(r['data'])} for r in db.execute(
                'SELECT * FROM estimates WHERE requirement_id=? ORDER BY created_at,rowid', (identifier,))]
            scopes = [dict(r) for r in db.execute('SELECT * FROM scopes WHERE requirement_id=?', (identifier,))]
        return {'requirement': req, 'tasks': tasks, 'events': events, 'estimates': estimates,
                'scopes': [{**r, 'data': json.loads(r['data'])} for r in scopes]}

    def metrics(self, rows=None, at=None, days=14, zone='America/Los_Angeles'):
        moment = stamp(at) or now()
        clock = seconds(moment)
        rows = rows if rows is not None else self.view(moment)['requirements']
        tz = ZoneInfo(zone)
        today = datetime.fromisoformat(moment).astimezone(tz).date()
        first_day = today - timedelta(days=days-1)
        daily = {str(first_day+timedelta(days=i)): {'date': str(first_day+timedelta(days=i)), 'received': 0, 'completed': 0} for i in range(days)}
        cycles, ready_cycles, errors, due, ontime, eta_coverage, completed, received, unknown_received = [], [], [], 0, 0, 0, 0, 0, 0
        for r in rows:
            if r.get('countable') is False:
                continue
            start, end = seconds(r.get('received_at')), seconds(r.get('first_complete_at'))
            if start is None:
                unknown_received += 1
            for timestamp, field in ((start, 'received'), (end, 'completed')):
                if timestamp is not None:
                    day = str(datetime.fromtimestamp(timestamp, tz).date())
                    if day in daily:
                        daily[day][field] += 1
                        if field == 'received': received += 1
                        else: completed += 1
            in_period = end is not None and str(datetime.fromtimestamp(end, tz).date()) in daily
            if in_period and start is not None and end >= start:
                cycles.append(end-start)
            ready = seconds(r.get('ready_at'))
            if in_period and ready is not None and end >= ready:
                ready_cycles.append(end-ready)
            eta = r.get('first_eta')
            forecast_end = seconds(r.get('scope_first_complete_at')) if 'scope_first_complete_at' in r else end
            eligible_eta = bool(eta and not eta['data'].get('retrospective') and
                                (forecast_end is None or seconds(eta['created_at']) < forecast_end))
            if eligible_eta:
                eta_coverage += 1
                upper = seconds(eta['upper_at'])
                # A matured ETA cohort includes unfinished overdue requests.
                if upper <= clock:
                    due += 1
                    ontime += bool(forecast_end is not None and forecast_end <= upper)
                if forecast_end is not None and str(datetime.fromtimestamp(forecast_end,tz).date()) in daily:
                    errors.append(forecast_end-upper)
        return {'timezone': zone, 'days': days, 'daily': list(daily.values()),
                'requirements': sum(r.get('countable') is not False for r in rows),
                'unlinked': sum(r.get('countable') is False for r in rows),
                'open': sum(r.get('countable') is not False and not r.get('complete_at') for r in rows),
                'blocked': sum(bool(r.get('block_reason') or r.get('blockers')) for r in rows),
                'overdue': sum(bool(r.get('overdue')) for r in rows),
                'complete': sum(bool(r.get('complete_at')) and r.get('countable') is not False for r in rows),
                'tasks': sum(r.get('task_count', 0) for r in rows if r.get('countable') is not False),
                'received_in_period': received, 'completed_in_period': completed,
                'cycle_median_seconds': median(cycles) if cycles else None, 'cycle_samples': len(cycles),
                'ready_cycle_median_seconds': median(ready_cycles) if ready_cycles else None, 'ready_cycle_samples': len(ready_cycles),
                'eta_bias_median_seconds': median(errors) if errors else None, 'eta_error_samples': len(errors),
                'eta_covered': eta_coverage, 'eta_due': due, 'eta_ontime': ontime,
                'eta_ontime_rate': ontime/due if due else None, 'unknown_received': unknown_received}

    def backup(self, destination):
        destination = Path(destination).resolve()
        if not destination.is_relative_to(self.root / 'state/ledger/backups') or destination.exists():
            raise ValueError('Backup must be a new file under state/ledger/backups')
        destination.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as source, sqlite3.connect(destination) as target:
            source.backup(target)
            if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Backup integrity check failed')
        return {'path': str(destination.relative_to(self.root)), 'integrity': 'ok'}


def runtime_event(run, kind, data, identifier=None, occurred=None):
    """Durable inbox independent of SQLite availability; never changes production."""
    run = Path(run).resolve()
    root = run.parent.parent
    folder = root / 'state/ledger/inbox'
    folder.mkdir(parents=True, exist_ok=True)
    if not folder.resolve().is_relative_to(root):
        raise ValueError('Event inbox outside workspace')
    identifier = identifier or uuid.uuid4().hex
    path = folder / (identifier + '.json')
    record = {'id': identifier, 'run_id': run.name, 'kind': kind, 'occurred_at': occurred or now(), 'data': data}
    temporary = folder / (identifier + '.tmp')
    temporary.write_text(packed(record), encoding='utf-8')
    temporary.replace(path)


def tracking_packet(run):
    """Read-only navigation for the host Agent. Never claims work or heartbeats."""
    root=Path(run).resolve().parent.parent
    path=root/'state/ledger/ledger.sqlite3'
    result={'workflow':'agent/workflows/ledger-tracking.md','available':False,
            'instructions':'At actual start claim the video using your real owner/session. Report stages, waits and genuine activity; never fabricate a heartbeat. Preserve the first ETA and explain changes.',
            'entries':['ledger claim','ledger stage','ledger heartbeat','ledger block','ledger resume','ledger eta','ledger release']}
    if not path.is_file():
        return result
    try:
        with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2) as db:
            matches=[]
            for task_data,req_data in db.execute('SELECT t.data,r.data FROM tasks t JOIN requirements r ON r.id=t.requirement_id'):
                task,req=json.loads(task_data),json.loads(req_data)
                if Path(run).name in task.get('runs',[]) and not req.get('resolved'):
                    matches.append({k:task[k] for k in ('requirement_id','video_id','locale')})
            result.update(available=True,bindings=matches)
    except (sqlite3.Error,ValueError):
        result['state']='ledger_unavailable; production evidence remains authoritative'
    return result
