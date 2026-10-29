"""Verify initial YouTube enqueue separately from import and downstream progress."""
from pathlib import Path

from .common import ROOT, file_hash, lock, object_hash, read_json, require, utc_now, write_json

QUEUED = {'pending', 'uploading', 'cooldown', 'done', '待上传', '下载中', '上传中', '待向量化', '已完成'}


def required(root=ROOT):
    from .fireplay_youtube import policy
    return policy(root).get('require_enqueue_evidence') is True


def inspect(material, task_response=None):
    """Only an actual current video URL or exact material/resource task proves handoff."""
    from . import fireplay
    mid = material.get('id')
    resource = material.get('currentVideoResourceId') or material.get('videoResourceId')
    require(fireplay._uuid(mid) and fireplay._uuid(resource), 'Read the exact material and current video resource')
    videos = [r for r in material.get('resources', []) if r.get('id') == resource and r.get('type') == 'video']
    require(len(videos) == 1, 'Current video resource is missing or ambiguous')
    url = videos[0].get('url')
    if isinstance(url, str) and fireplay.youtube_id(url):
        return {'material_id': mid, 'video_resource_id': resource,
                'state': 'youtube_url_verified', 'youtube_url': url}
    if task_response is not None:
        value = fireplay.payload(task_response)
        rows = value.get('items', value.get('tasks', [value]))
        require(isinstance(rows, list), 'Read actual upload-task rows')
        matches = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            task_id = row.get('task_id') or row.get('taskId') or row.get('id')
            task_material = row.get('material_id') or row.get('materialId')
            task_resource = row.get('video_resource_id') or row.get('videoResourceId') or row.get('resource_id')
            state = row.get('status') or row.get('state')
            if (task_material == mid and task_resource == resource and fireplay._uuid(task_id)
                    and state in QUEUED and row.get('task_type', 'upload') == 'upload'):
                matches.append({'material_id': mid, 'video_resource_id': resource,
                                'state': 'enqueue_verified', 'task_id': task_id, 'task_status': state})
        require(len(matches) == 1, 'YouTube enqueue needs one actual accepted task for this exact material/resource')
        return matches[0]
    require(False, 'R2 import, a checked upload option or a requested flag is not YouTube enqueue evidence')


def _known(record, root):
    from .fireplay_submission import bound_materials
    result = []
    for video in record['videos']:
        result.extend({**m, 'video_index': video['index']} for m in bound_materials(record, video, root))
        path = Path(root) / 'state/fireplay' / record['code'] / f'return-{video["index"]}.json'
        if path.exists():
            box = read_json(path)
            for i, package in enumerate(box.get('packages', []), 1):
                operation = box.get('operations', {}).get(f'import-{i}', {})
                if operation.get('state') == 'verified':
                    result.append({'material_id': operation['result']['material_id'],
                                   'video_index': video['index'], 'locale': package['locale'],
                                   'sha256': package['sha256']})
    return list({(m['material_id'], m['video_index'], m['locale'], m['sha256']): m for m in result}.values())


def record_receipt(code, spec, root=ROOT):
    """Append proof for an existing material. Never upload, reimport, or replace a binding."""
    from . import fireplay
    spec = fireplay.payload(spec)
    folder = fireplay._folder(code, root)
    with lock(folder / 'request.lock'):
        record = fireplay._record(code, root)
        material_receipt = fireplay.payload(spec['material_receipt'])
        task_receipt = fireplay.payload(spec['task_receipt']) if spec.get('task_receipt') else None
        material = material_receipt.get('material', {})
        matches = [m for m in _known(record, root) if m['material_id'] == material.get('id')]
        require(len(matches) == 1, 'YouTube receipt belongs to an unknown or ambiguous submitted material')
        identity = matches[0]
        require(identity.get('sha256') and spec.get('video_sha256') == identity['sha256'],
                'YouTube receipt must bind the actual submitted video hash')
        acceptance = inspect(material, task_receipt)
        value = {'code': code, 'requirement_id': record['requirement_id'],
                 'content_version': record['content_version'], **identity, 'acceptance': acceptance,
                 'material_receipt': material_receipt, 'task_receipt': task_receipt,
                 'recorded_at': utc_now(), 'scope': 'Initial YouTube enqueue or actual URL only; no new quality approval'}
        path = folder / 'youtube-handoffs/receipts' / (object_hash(value) + '.json')
        write_json(path, value)
        write_json(folder / 'youtube-handoffs' / (identity['material_id'] + '.json'),
                   {'path': str(path.relative_to(root)), 'sha256': file_hash(path)})
        return {'material_id': identity['material_id'], 'locale': identity['locale'],
                'youtube_status': acceptance['state'], 'receipt': str(path.relative_to(root))}


def accepted(record, material, root=ROOT):
    from .common import inside
    path = Path(root) / 'state/fireplay' / record['code'] / 'youtube-handoffs' / (material['material_id'] + '.json')
    if not path.exists():
        return False
    pointer = read_json(path)
    evidence = inside(root, pointer['path'])
    require(file_hash(evidence) == pointer['sha256'], 'YouTube handoff evidence changed')
    value = read_json(evidence)
    if (value.get('requirement_id') != record['requirement_id'] or
            value.get('content_version') != record['content_version'] or
            any(value.get(k) != material.get(k) for k in ('material_id', 'locale', 'sha256'))):
        return False
    from .fireplay import payload
    actual = inspect(payload(value['material_receipt']).get('material', {}), value.get('task_receipt'))
    require(value['acceptance'] == actual, 'YouTube handoff judgment differs from its saved platform evidence')
    return True


def coverage(record, video, root=ROOT):
    from .fireplay_submission import bound_materials, _canonical_materials
    rows = bound_materials(record, video, root)
    if not rows:
        path = Path(root) / 'state/fireplay' / record['code'] / f'return-{video["index"]}.json'
        if path.exists():
            rows = _canonical_materials(read_json(path))
    missing = [m for m in rows if not accepted(record, m, root)] if required(root) else []
    return {'required': required(root), 'complete': not missing,
            'missing': [{k: m[k] for k in ('material_id', 'locale', 'sha256')} for m in missing],
            'scope': 'Initial enqueue acceptance only; does not poll downstream upload progress'}
