"""Recognize verified Fireplay acceptance without tracking downstream YouTube progress."""
from pathlib import Path
from .common import ROOT, read_json



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
