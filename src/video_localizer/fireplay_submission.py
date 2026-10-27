"""Recognize verified Fireplay acceptance without tracking downstream YouTube progress."""
from pathlib import Path
from .common import ROOT, read_json


def bound_materials(record, video, root=ROOT):
    from . import fireplay
    folder = Path(root) / 'state/fireplay' / record['code']
    box = folder / f'return-{video["index"]}.json'
    if box.exists():
        value = read_json(box)
        if (value.get('state') == 'returned' and
                {p['locale'] for p in value['packages']} == set(video['targets']) and
                value.get('operations', {}).get('bind', {}).get('state') == 'verified'):
            return [{'material_id': value['operations'][f'import-{i}']['result']['material_id'],
                     'locale': p['locale'], 'sha256': p['sha256']} for i, p in enumerate(value['packages'], 1)]
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
