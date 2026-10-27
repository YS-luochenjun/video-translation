"""Request-wide spending authority. Creating runs/batches never issues new credit."""
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from urllib.parse import urlparse
import hashlib
import math
import re
from decimal import Decimal, ROUND_FLOOR

from .common import ROOT, file_hash, inside, lock, object_hash, read_json, require, require_number, utc_now, write_json

_permit = ContextVar('paid_request_permit', default=None)
TERMINAL = ('success', 'fail', 'failed', 'response_received', 'response_invalid')


def duration_allowance(source, root=ROOT):
    """Quote actual source duration; this never opens or replenishes a ledger."""
    from . import media
    policy_path = Path(root) / 'config/budget-policy.json'
    policy = read_json(policy_path)
    require(policy.get('mode') == 'source_duration', 'Unsupported request budget policy')
    rate = require_number(policy['max_credits_per_source_second'], 'credits per source second', minimum=.001)
    seconds = require_number(media.probe(source)['duration'], 'source duration', minimum=.001)
    limit = float((Decimal(str(seconds)) * Decimal(str(rate))).quantize(Decimal('.001'), rounding=ROUND_FLOOR))
    require(limit > 0, 'Source duration leaves no credit allowance')
    return {'credit_limit': limit, 'budget_basis': {'policy': 'source_duration',
            'source_duration_seconds': seconds, 'max_credits_per_source_second': rate,
            'policy_sha256': file_hash(policy_path), 'scope': 'whole_request',
            'rounding': 'floor_to_millicredit'}}


def target_languages(targets, root=ROOT):
    from .languages import resolve
    require(isinstance(targets, list) and bool(targets), 'Budget requires the actual target languages in targets')
    # Aliases and case changes do not issue additional language allowances.
    languages = {}
    for value in targets:
        language = resolve(value, root)['target_language']
        languages.setdefault(language.casefold(), language)
    return [languages[key] for key in sorted(languages)]


def request_allowance(source, targets, root=ROOT):
    policy_path = Path(root) / 'config/budget-policy.json'
    policy = read_json(policy_path)
    if policy.get('mode') == 'source_duration':
        return duration_allowance(source, root)
    require(policy.get('mode') == 'per_target_language', 'Unsupported request budget policy')
    from . import media
    languages = target_languages(targets, root)
    rate = require_number(policy['credits_per_target_language'], 'credits per target language', minimum=.001)
    seconds = require_number(media.probe(source)['duration'], 'source duration', minimum=.001)
    limit = float(Decimal(str(rate)) * len(languages))
    return {'credit_limit': limit, 'budget_basis': {'policy': 'per_target_language',
            'targets': languages, 'target_count': len(languages), 'credits_per_target_language': rate,
            'source_duration_seconds': seconds, 'policy_sha256': file_hash(policy_path),
            'scope': 'whole_request', 'allocation': 'shared_pool'}}


def require_targets(record, targets, root=ROOT):
    basis = record.get('budget_basis', {})
    if basis.get('policy') == 'per_target_language':
        require(set(t.casefold() for t in target_languages(targets, root)).issubset(
                    t.casefold() for t in basis['targets']),
                'Target languages exceed the registered request; use an attributed budget-amend')


def run_allowance(run):
    """Use the bound original request, including for clips; otherwise quote only."""
    run = Path(run).resolve()
    root = run.parent.parent
    sha = _run_source(run)
    index = _index(root)
    entry = index['runs'].get(run.name)
    scope = entry['scope'] if entry else index['sources'].get(sha)
    if scope:
        record = read_json(_record(root, scope))
        require(sha in record['sources'] and (not entry or entry['source_sha256'] == sha), 'Budget source mismatch')
        return {key: record[key] for key in ('credit_limit', 'budget_basis') if key in record}
    request = read_json(run / 'inputs/request.json')
    return request_allowance(inside(run, read_json(run / 'run.json')['source']), [request['target_language']], root)


def job_allowance(run, allowance, segment_seconds):
    """Finite planning guard; money and two repair rounds remain separate gates."""
    basis = allowance.get('budget_basis', {})
    require(basis.get('policy') in ('source_duration', 'per_target_language'), 'Job allowance needs its original source basis')
    units = math.ceil(basis['source_duration_seconds'] / require_number(segment_seconds, 'segment seconds', minimum=.001))
    inventory = Path(run) / 'analysis/inventory.json'
    if inventory.exists():
        roles = {line['character_id'] for line in read_json(inventory).get('speech_segments', [])
                 if line.get('character_id') and line['character_id'] != 'unknown'}
        units = max(units, len(roles))
    return max(2, units * 3 + 2)  # Initial task + two repairs per unit, plus audio review slots.


@contextmanager
def operation():
    token = _permit.set(None)
    try:
        yield
    finally:
        _permit.reset(token)


def _directory(root):
    return Path(root) / 'state/budgets'


def _index(root):
    path = _directory(root) / 'index.json'
    value = read_json(path) if path.exists() else {'sources': {}, 'runs': {}, 'authorizations': {}}
    value.setdefault('requirement_sources', {})
    return value


def _record(root, scope):
    require(isinstance(scope, str) and re.fullmatch(r'[a-f0-9]{32}', scope), 'Invalid request budget id')
    return _directory(root) / (scope + '.json')


def open_request(spec, root=ROOT):
    """Host/operator administrative action backed by a real, new user request.

    authorization_ref is the stable human message/event ID, not a run/task ID.
    Production workers must never invent it to replenish an exhausted budget.
    """
    spec = read_json(spec) if not isinstance(spec, dict) else spec
    require(spec.get('authority') == 'user' and spec.get('authorization_ref') and spec.get('user_request'),
            'Budget requires the originating human request, its stable host event reference and authority=user')
    require(spec.get('mode') in ('first', 'reuse'), 'Budget mode must be first or reuse')
    requirement_code = spec.get('scope_requirement')
    if requirement_code:
        require(isinstance(requirement_code, str) and re.fullmatch(r'[A-Z][A-Z0-9]{1,15}-\d{8}-\d{3,6}', requirement_code),
                'Invalid requirement budget scope')
    source = Path(spec['source']).resolve()
    digest = file_hash(source)
    auth = object_hash({'authorization_ref': spec['authorization_ref']})
    directory = _directory(root)
    with lock(directory / '.lock'):
        index = _index(root)
        if auth in index['authorizations']:
            existing = read_json(_record(root, index['authorizations'][auth]))
            require(existing.get('scope_requirement') == requirement_code, 'Human request belongs to another requirement scope')
            require(existing['original_source_sha256'] == digest and existing['mode'] == spec['mode'],
                    'One user request cannot issue multiple budgets; attach its split work to the original budget')
            if existing.get('budget_basis', {}).get('policy') == 'per_target_language':
                require_targets(existing, spec.get('targets'), root)
            return existing
        source_index = index['requirement_sources'].setdefault(requirement_code, {}) if requirement_code else index['sources']
        previous = source_index.get(digest)
        if spec['mode'] == 'first' and previous:
            existing = read_json(_record(root, previous))
            if existing.get('budget_basis', {}).get('policy') == 'per_target_language':
                require_targets(existing, spec.get('targets'), root)
            # Even a different run, batch or fabricated task ID cannot replenish first-version funds.
            index['authorizations'][auth] = previous
            write_json(directory / 'index.json', index)
            return read_json(_record(root, previous))
        if spec['mode'] == 'reuse':
            require(previous and spec.get('reuse_of') == previous,
                    'Reuse requires the existing budget and a distinct explicit user request')
            old = read_json(_record(root, previous))
            _refresh(old, root)
            require(all(row.get('actual_credits') is not None and row.get('state') in TERMINAL
                        for row in old['reservations'].values()), 'Reconcile the previous request before opening reuse funds')
            require(spec.get('reuse_confirmation') == 'new_user_request',
                    'Retries/revisions are the same request, not a new reuse allowance')
        scope = object_hash({'source': digest, 'authorization': auth, 'mode': spec['mode']})[:32]
        allowance = request_allowance(source, spec.get('targets'), root) if (Path(root) / 'config/budget-policy.json').exists() else {
            'credit_limit': 60 if spec['mode'] == 'first' else 40}
        # Validate/probe before closing the old allowance: a failed quote must be retryable.
        if spec['mode'] == 'reuse':
            old['state'] = 'closed'
            write_json(_record(root, previous), old)
        record = {'schema_version': 1, 'id': scope, 'state': 'open', 'mode': spec['mode'],
                  **allowance,
                  'original_source_sha256': digest, 'sources': [digest], 'runs': {}, 'reservations': {},
                  'authorization_ref': spec['authorization_ref'], 'user_request': spec['user_request'],
                  'created_at': utc_now()}
        if requirement_code:
            record['scope_requirement'] = requirement_code
        if previous:
            record['sources'] = list(old['sources'])
            record['reuse_of'] = previous
            record['historical_receipts'] = sorted(set(old.get('historical_receipts', [])) | {
                row['receipt'] for row in old['reservations'].values() if row.get('receipt')})
        else:
            # A new ledger must include existing work, even if the next submission
            # comes from a new run. Missing media does not erase its old charges.
            for meta_path in (Path(root) / 'runs').glob('*/run.json'):
                meta = read_json(meta_path)
                if meta.get('source_sha256') != digest:
                    continue
                provenance = meta_path.parent / 'inputs/fireplay.json'
                if requirement_code and (not provenance.exists() or read_json(provenance).get('code') != requirement_code):
                    continue
                name = meta_path.parent.name
                require(name not in index['runs'], 'Existing run already belongs to another request')
                record['runs'][name] = digest
                index['runs'][name] = {'scope': scope, 'source_sha256': digest}
            _refresh(record, root)
        write_json(_record(root, scope), record)
        for sha in record['sources']:
            source_index[sha] = scope
        index['authorizations'][auth] = scope
        write_json(directory / 'index.json', index)
    return record


def amend_limit(scope, limit, authorization_ref, source_quote, root=ROOT, targets=None):
    """Host-only amendment from an actual user instruction; never resets spending."""
    require_number(limit, 'credit limit', minimum=.001)
    require(bool(authorization_ref) and bool(source_quote), 'User amendment attribution required')
    with lock(_directory(root) / '.lock'):
        record = read_json(_record(root, scope))
        _refresh(record, root)
        used = sum(row['reserved_credits'] for row in record['reservations'].values())
        require(limit >= used, 'Limit is below already billed/reserved credits')
        require(record['state'] == 'open', 'Request budget is closed')
        languages = target_languages(targets, root) if targets is not None else None
        basis = record.get('budget_basis', {})
        if languages is not None:
            require(basis.get('policy') == 'per_target_language', 'Target amendments require a per-language request')
            require(set(t.casefold() for t in basis['targets']).issubset(t.casefold() for t in languages),
                    'Target amendment cannot remove already registered languages')
        amendments = record.setdefault('authorized_amendments', [])
        prior = [a for a in amendments if a.get('authorization_ref') == authorization_ref]
        if prior:
            require(prior[-1]['new_total_credit_limit'] == limit, 'Amendment identity changed')
            require(prior[-1].get('targets') == languages, 'Amendment target identity changed')
            return record
        amendments.append({'authority': 'user', 'authorization_ref': authorization_ref,
                           'source_quote': source_quote, 'previous_limit': record['credit_limit'],
                           'new_total_credit_limit': limit, 'targets': languages, 'at': utc_now()})
        record['credit_limit'] = limit
        if languages is not None:
            record['budget_basis'] = {**basis, 'targets': languages, 'target_count': len(languages)}
        write_json(_record(root, scope), record)
    return record


def for_source(source_sha, root=ROOT):
    index = _index(root)
    require(source_sha in index['sources'], 'No request budget: host must register the real user request with budget-open; new runs do not create credit')
    record = read_json(_record(root, index['sources'][source_sha]))
    require(record['state'] == 'open', 'Request budget is closed')
    return record


def attach_source(scope, source, authorization_ref, root=ROOT):
    """Host intake: attach another declared original to the SAME language pool.

    No new allowance; the registered human event must already own this scope.
    Unlike derived-run binding, this survives retirement of the first video run.
    """
    digest = file_hash(source)
    with lock(_directory(root) / '.lock'):
        index = _index(root)
        require(index['authorizations'].get(object_hash({'authorization_ref': authorization_ref})) == scope,
                'Source attachment needs the original registered human request')
        record = read_json(_record(root, scope))
        require(record['state'] == 'open', 'Request budget is closed')
        require(record.get('budget_basis', {}).get('policy') == 'per_target_language',
                'Additional originals require a shared per-language request, not a historical duration allowance')
        source_index = index['requirement_sources'].setdefault(record['scope_requirement'], {}) if record.get('scope_requirement') else index['sources']
        require(digest not in source_index or source_index[digest] == scope,
                'Source already belongs to another request; preserve its original ledger')
        if digest not in record['sources']:
            record['sources'].append(digest)
        source_index[digest] = scope
        write_json(_record(root, scope), record)
        write_json(_directory(root) / 'index.json', index)
    return record


def _run_source(run):
    meta = read_json(Path(run) / 'run.json')
    require(file_hash(inside(run, meta['source'])) == meta['source_sha256'], 'Budget source changed')
    return meta['source_sha256']


def bind(run, parent_run=None):
    run = Path(run).resolve()
    root = run.parent.parent
    sha = _run_source(run)
    with lock(_directory(root) / '.lock'):
        index = _index(root)
        if run.name in index['runs']:
            entry = index['runs'][run.name]
            require(entry['source_sha256'] == sha, 'Run identity was reused for another source')
            record = read_json(_record(root, entry['scope']))
            require(record['state'] == 'open', 'Original run request is closed; do not repurpose it for a new allowance')
            if record.get('budget_basis', {}).get('policy') == 'per_target_language':
                require_targets(record, [read_json(run / 'inputs/request.json')['target_language']], root)
            return record
        if parent_run:
            parent = Path(parent_run).resolve()
            require(parent.parent == run.parent and parent.name in index['runs'], 'Derived run needs a bound parent in this workspace')
            parent_sha = _run_source(parent)
            require(parent_sha == index['runs'][parent.name]['source_sha256'], 'Parent source changed')
            scope = index['runs'][parent.name]['scope']
            parent_record = read_json(_record(root, scope))
            source_index = index['requirement_sources'].setdefault(parent_record['scope_requirement'], {}) if parent_record.get('scope_requirement') else index['sources']
            require(sha not in source_index or source_index[sha] == scope, 'Source already belongs to another request')
        else:
            provenance = run / 'inputs/fireplay.json'
            code = read_json(provenance).get('code') if provenance.exists() else None
            scoped = index['requirement_sources'].get(code, {})
            source_index = scoped if sha in scoped else index['sources']
            require(sha in source_index, 'Unbound paid run: budget-open for the human request or budget-bind --parent-run for a derived clip')
            scope = source_index[sha]
        record = read_json(_record(root, scope))
        if record.get('scope_requirement'):
            source_index = index['requirement_sources'].setdefault(record['scope_requirement'], {})
        require(record['state'] == 'open', 'Request budget is closed')
        if record.get('budget_basis', {}).get('policy') == 'per_target_language':
            require_targets(record, [read_json(run / 'inputs/request.json')['target_language']], root)
        record['runs'][run.name] = sha
        if sha not in record['sources']:
            record['sources'].append(sha)
        source_index[sha] = scope
        index['runs'][run.name] = {'scope': scope, 'source_sha256': sha}
        # Existing/restored jobs are imported and deduplicated by actual provider IDs.
        _refresh(record, root)
        write_json(_record(root, scope), record)
        write_json(_directory(root) / 'index.json', index)
        return record


def _refresh(record, root):
    from .workflow import reserved_credits
    receipts = {row.get('receipt'): key for key, row in record['reservations'].items() if row.get('receipt')}
    for name in record['runs']:
        for path in (Path(root) / 'runs' / name / 'jobs').glob('*.json'):
            job = read_json(path)
            key = job['id']
            receipt = ('task:' + job['task_id']) if job.get('task_id') else ('response:' + job['response_id']) if job.get('response_id') else None
            if receipt in record.get('historical_receipts', []):
                continue  # Settled previous-request results cost nothing to reuse.
            if receipt and receipt in receipts:
                key = receipts[receipt]
            elif key in record['reservations']:
                old = record['reservations'][key]
                if (receipt and old.get('receipt') and receipt != old['receipt']) or (
                        old['run'] != name and not (receipt and receipt == old.get('receipt'))):
                    key = object_hash({'receipt': receipt}) if receipt else object_hash({'run': name, 'job': job['id']})
            row = record['reservations'].setdefault(key, {'run': name, 'job': job['id'],
                    'estimate': job.get('estimated_credits', record['credit_limit']), 'imported': True})
            amount = reserved_credits(job, row['estimate'])
            if row['run'] != name:
                amount = max(amount, row.get('reserved_credits', amount))
            row.update(reserved_credits=amount,
                       actual_credits=job.get('credits_consumed'), state=job.get('state'), receipt=receipt)
            if receipt:
                receipts[receipt] = key


def reserve(run, job_id, estimate):
    require_number(estimate, 'request reservation', minimum=.001)
    require(re.fullmatch(r'[a-f0-9]{64}', job_id), 'Invalid request job id')
    record = bind(run)
    root = Path(run).resolve().parent.parent
    with lock(_directory(root) / '.lock'):
        record = read_json(_record(root, record['id']))
        _refresh(record, root)
        require(record['state'] == 'open', 'Request closed')
        require(job_id not in record['reservations'], 'Identical request already reserved/submitted in another run; reuse/reconcile its original job')
        total = sum(row['reserved_credits'] for row in record['reservations'].values())
        require(total + estimate <= record['credit_limit'], 'Whole-request credit budget reached; new runs, batches and revisions share this limit')
        record['reservations'][job_id] = {'run': Path(run).name, 'job': job_id, 'estimate': estimate,
                'reserved_credits': estimate, 'actual_credits': None, 'state': 'reserved', 'created_at': utc_now()}
        write_json(_record(root, record['id']), record)
    permit = {'root': str(root), 'scope': record['id'], 'job': job_id}
    _permit.set(permit)
    return {'request_budget': record['id'], 'credit_limit': record['credit_limit']}


def resume_undispatched(run, job_id):
    """Resume only a locally proven pre-dispatch failure, using the same reservation."""
    record = bind(run)
    root = Path(run).resolve().parent.parent
    with lock(_directory(root) / '.lock'):
        record = read_json(_record(root, record['id']))
        row = record['reservations'][job_id]
        require(row['run'] == Path(run).name and not row.get('dispatch') and
                row.get('actual_credits') is None, 'Task may have been dispatched; reconcile instead')
        require(record['state'] == 'open' and
                sum(r['reserved_credits'] for r in record['reservations'].values()) <= record['credit_limit'],
                'Request limit no longer permits this reservation')
    _permit.set({'root': str(root), 'scope': record['id'], 'job': job_id})


def authorize_request(url, body):
    """Require a live reservation even for direct KieClient use; one paid POST only."""
    if body is None:
        return
    permit = _permit.get()
    require(permit, 'KIE writes require an executor reservation; direct scripts cannot bypass request budgets')
    root = Path(permit['root'])
    with lock(_directory(root) / '.lock'):
        record = read_json(_record(root, permit['scope']))
        require(record['state'] == 'open', 'Request budget closed')
        row = record['reservations'][permit['job']]
        require(not row.get('dispatch'), 'This reservation was already dispatched; reconcile instead of another POST')
        if urlparse(url).hostname == 'kieai.redpandaai.co':
            return  # Asset uploads precede the single charged model request.
        row['dispatch'] = {'endpoint': urlparse(url).path, 'at': utc_now(),
                           'request_sha256': hashlib.sha256(body).hexdigest() if isinstance(body, bytes) else object_hash(body)}
        write_json(_record(root, record['id']), record)


def sync(run):
    root = Path(run).resolve().parent.parent
    with lock(_directory(root) / '.lock'):
        index = _index(root)
        entry = index['runs'].get(Path(run).name)
        if entry:
            record = read_json(_record(root, entry['scope']))
            _refresh(record, root)
            write_json(_record(root, record['id']), record)


def status(scope, root=ROOT):
    with lock(_directory(root) / '.lock'):
        record = read_json(_record(root, scope))
        _refresh(record, root)
        write_json(_record(root, scope), record)
    used = sum(row['reserved_credits'] for row in record['reservations'].values())
    return {**record, 'reserved_or_billed_credits': used, 'remaining_credits': max(0, record['credit_limit']-used),
            'unknown_billing_jobs': sum(row.get('actual_credits') is None or row.get('state') not in TERMINAL
                                        for row in record['reservations'].values()),
            'boundary': 'Provider actual billing may exceed its estimate; no further submission is allowed once the remaining allowance is insufficient.'}
