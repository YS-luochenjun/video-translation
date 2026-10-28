"""Bounded re-upload after an observed file-upload timeout, preserving all attempts."""
from pathlib import Path
import re

from .common import ROOT, file_hash, inside, lock, read_json, require, utc_now, write_json


def retry_upload(code, locale, spec, execute=False, root=ROOT, index=1):
    """Prepare a new upload attempt; this never calls the external connector."""
    from . import fireplay
    spec = fireplay.payload(spec)
    policy_file = Path(root) / 'config/fireplay-publication.json'
    policy = read_json(policy_file).get('completion', {}).get('upload_timeout_retry', {}) if policy_file.exists() else {}
    authority = spec.get('authority') or policy
    require(authority.get('authority') == 'user' and authority.get('authorization_ref') and authority.get('source_quote'),
            'Timeout re-upload needs an explicit user instruction or standing policy')
    evidence = inside(root, spec['timeout_evidence'])
    require(evidence.is_file() and re.search(r'timeout|timed.?out|超时', evidence.read_text(encoding='utf-8'), re.I),
            'Re-upload requires the actual timeout observation; an in-flight unknown is not enough')
    folder = fireplay._folder(code, root)
    path = folder / f'return-{index}.json'
    with lock(folder / 'request.lock'):
        outbox = read_json(path)
        matches = [(i, p) for i, p in enumerate(outbox['packages'], 1) if p['locale'] == locale]
        require(len(matches) == 1, 'Expected one exact outbox locale for re-upload')
        number, package = matches[0]
        key = f'upload-{number}'
        operation = outbox['operations'].get(key, {})
        require(operation.get('state') == 'unknown' and f'import-{number}' not in outbox['operations']
                and not operation.get('result'), 'Only an unknown upload without import or known resource can be retried')
        require(outbox['operations'].get('bind', {}).get('state') != 'unknown', 'Reconcile an in-flight binding before re-upload')
        require(file_hash(inside(root, package['file'])) == package['sha256'] and
                file_hash(inside(root, package['package']) / 'manifest.json') == package['manifest_sha256'],
                'Reviewed package changed before timeout re-upload')
        attempts = outbox.get('upload_attempts', {}).get(key, [])
        limit = policy.get('max_additional_attempts', 2)
        require(type(limit) is int and 0 < limit <= 2 and len(attempts) < limit, 'Upload retry limit reached; preserve the unresolved gap')
        require(not any(a['timeout_evidence'] == spec['timeout_evidence'] and a['timeout_sha256'] == file_hash(evidence)
                        for a in attempts), 'Record a new timeout observation for each attempt')
        record = {'locale': locale, 'operation_id': key, 'next_attempt': len(attempts) + 2,
                  'previous_operation': operation, 'authority': authority,
                  'timeout_evidence': spec['timeout_evidence'], 'timeout_sha256': file_hash(evidence),
                  'video_sha256': package['sha256'], 'recorded_at': utc_now()}
        if execute:
            attempt_number = len(attempts) + 1
            outbox.setdefault('upload_attempts', {}).setdefault(key, []).append(record)
            del outbox['operations'][key]
            if 'bind' in outbox['operations']:
                outbox.setdefault('binding_history', []).append(outbox['operations'].pop('bind'))
            if locale in outbox.get('deferred_uploads', {}):
                outbox.setdefault('upload_deferral_history', []).append(outbox['deferred_uploads'].pop(locale))
            outbox['state'] = 'ready'
            if locale not in outbox['pending_locales']:
                outbox['pending_locales'].append(locale)
            write_json(folder / 'receipts' / f'{index}-{key}-timeout-attempt-{attempt_number}.json', record)
            write_json(path, outbox)
        return {'state': 'retry_prepared' if execute else 'preview', 'record': record,
                'external_call_executed': False, 'next': 'Use fireplay-dispatch once for the new attempt; keep all previous unknown receipts'}
