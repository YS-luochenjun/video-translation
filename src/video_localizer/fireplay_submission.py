"""Recognize verified Fireplay acceptance without tracking downstream YouTube progress."""
from pathlib import Path
from .common import ROOT, file_hash, object_hash, read_json, require, utc_now, write_json



def _canonical_materials(value):
    from . import fireplay
    operations = value.get('operations', {})
    bind = operations.get('bind', {})
    if value.get('state') != 'returned' or bind.get('state') != 'verified':
        return []
    rows = []
    bound_ids = bind.get('result', {}).get('material_ids')
    for i, package in fireplay._active_packages(value):
        imported = operations.get(f'import-{i}', {})
        verified = operations.get(f'verify-{i}', {})
        mid = imported.get('result', {}).get('material_id')
        if (imported.get('state') == verified.get('state') == 'verified' and fireplay._uuid(mid)
                and (bound_ids is None or mid in bound_ids)):
            rows.append({'material_id': mid, 'locale': package['locale'], 'sha256': package['sha256']})
    return rows


def bound_materials(record, video, root=ROOT):
    from . import fireplay
    folder = Path(root) / 'state/fireplay' / record['code']
    box = folder / f'return-{video["index"]}.json'
    if box.exists():
        value = read_json(box)
        if (value.get('state') == 'returned' and not value.get('pending_locales') and
                {p['locale'] for p in value['packages']} == set(video['targets']) and
                value.get('operations', {}).get('bind', {}).get('state') == 'verified'):
            rows = _canonical_materials(value)
            if {r['locale'] for r in rows} == set(video['targets']):
                return rows
    candidates = [folder / f'user-approved-return-{video["index"]}.json',
                  folder / 'user-directed-submission/submission-final.json']
    for path in candidates:
        if not path.exists():
            continue
        value = read_json(path)
        if path.name == 'submission-final.json' and len(record['videos']) > 1 and value.get('video_index') != video['index']:
            continue
        if value.get('requirement_id') != record['requirement_id']:
            continue
        rows = value.get('items') or value.get('records') or []
        proven = value.get('state') == 'returned_user_approved' or value.get('all_bound') is True
        if rows and all(fireplay._uuid(r.get('material_id')) and
                        (proven or r.get('bound_verified') is True) for r in rows):
            if {r.get('locale') for r in rows} == set(video['targets']):
                return [{k: r.get(k) for k in ('material_id', 'locale', 'sha256')} for r in rows]
    # Legacy browser receipts bind the actual byte identities, not display names.
    for path in folder.glob('*/verified-*-materials.json'):
        value = read_json(path)
        if (value.get('bound_requirement') != record['requirement_id'] or
                value.get('source_sha256') != video.get('source', {}).get('sha256')):
            continue
        rows = value.get('rows', [])
        if rows and {r.get('locale') for r in rows} == set(video['targets']) and all(
                fireplay._uuid(r.get('material_id')) and all(r.get(k) is True for k in
                ('name_verified', 'tags_verified', 'sharing_verified', 'byte_identity_verified')) for r in rows):
            return [{k: r.get(k) for k in ('material_id', 'locale', 'sha256')} for r in rows]
    return []


def coverage(record, video, root=ROOT):
    """Compare requested locales with verified acceptance, including partial returns."""
    from . import fireplay
    expected = set(video['targets'])
    materials = bound_materials(record, video, root)
    path = Path(root) / 'state/fireplay' / record['code'] / f'return-{video["index"]}.json'
    if not materials and path.exists():
        materials = _canonical_materials(read_json(path))
    if not materials:
        for name in (f'user-approved-return-{video["index"]}.json', 'user-directed-submission/submission-final.json'):
            receipt = path.parent / name
            if not receipt.exists():
                continue
            value = read_json(receipt)
            if value.get('requirement_id') != record['requirement_id']:
                continue
            if receipt.name == 'submission-final.json' and len(record['videos']) > 1 and value.get('video_index') != video['index']:
                continue
            proven = value.get('state') == 'returned_user_approved' or value.get('all_bound') is True
            materials.extend(r for r in (value.get('items') or value.get('records') or [])
                             if fireplay._uuid(r.get('material_id')) and (proven or r.get('bound_verified') is True))
    accepted = {r['locale'] for r in materials} & expected
    return {'expected_locales': sorted(expected), 'bound_locales': sorted(accepted),
            'missing_locales': sorted(expected - accepted), 'complete': expected == accepted and bool(expected)}


def verify_completion(code, spec, root=ROOT):
    """Bind full requirement coverage to a current platform read, never its status label."""
    from datetime import datetime, timezone
    from . import fireplay
    value = fireplay.payload(spec)
    verification = fireplay.payload(value['verification']) if 'verification' in value else value
    record = fireplay._record(code, root)
    rows = [r for r in verification.get('items', []) if r.get('id') == record['requirement_id']]
    require(len(rows) == 1, 'Completion needs one exact requirement delivery read-back')
    try:
        observed = datetime.fromisoformat(verification.get('serverTime', '').replace('Z', '+00:00'))
        age = (datetime.now(timezone.utc) - observed).total_seconds()
    except (ValueError, TypeError):
        require(False, 'Completion needs a current timezone-aware platform timestamp')
    require(-60 <= age <= 600, 'Completion platform read-back is stale; refresh delivery view')
    row = rows[0]
    actual = {m['id'] for m in row.get('materials', [])}
    missing, verified, seen = [], [], set()
    for video in record['videos']:
        bound = bound_materials(record, video, root)
        for locale in video['targets']:
            matches = [m for m in bound if m.get('locale') == locale]
            reason = None
            if row.get('materialSelection', {}).get('status') == 'waiting_selection':
                reason = 'platform_user_selection_required'
            elif len(matches) != 1:
                reason = 'source_locale_not_fully_bound'
            else:
                material = matches[0]
                digest = material.get('sha256') or ''
                mid = material['material_id']
                if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                    reason = 'missing_reviewed_video_identity'
                elif mid not in actual:
                    reason = 'material_not_in_current_platform_binding'
                elif mid in seen:
                    reason = 'material_reused_for_different_source_locale'
                else:
                    seen.add(mid)
                    verified.append({'video_index': video['index'], **material})
            if reason:
                missing.append({'video_index': video['index'], 'locale': locale, 'reason': reason})
    result = {'code': code, 'requirement_id': record['requirement_id'], 'content_version': record['content_version'],
              'complete': not missing and bool(verified), 'expected_count': sum(len(v['targets']) for v in record['videos']),
              'verified_count': len(verified), 'verified': verified, 'missing': missing,
              'verification_sha256': object_hash(verification), 'platform_read_at': verification['serverTime'],
              'checked_at': utc_now(), 'request_sha256': file_hash(fireplay._folder(code, root) / 'request.json'),
              'scope': 'Current Fireplay binding of every requested source/locale; no downstream YouTube publication proof'}
    write_json(fireplay._folder(code, root) / 'completion-check.json', result)
    return result
