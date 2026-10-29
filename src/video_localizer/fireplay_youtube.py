"""Fail closed on a default YouTube account whose group was never verified."""
from pathlib import Path
from datetime import datetime, timezone

from .common import ROOT, file_hash, inside, lock, read_json, require, write_json


def policy(root=ROOT):
    path = Path(root) / 'config/fireplay-youtube-routing.json'
    # A missing local deployment policy must never restore the unsafe default.
    return {'require_requirement_group': True, **(read_json(path) if path.exists() else {})}


def instruction(root=ROOT):
    if not policy(root).get('require_requirement_group'):
        return ('按用户最新固定流程入库、共享到需求组、请求YouTube自动上传、打语言/产品tag并绑定需求。'
                'YouTube账号路由交给Fireplay，账号/任务组显示不作为上传门禁；入库共享和绑定仍须核验。'
                'R2入库、VedioSouce=YouTube、勾选开关或requested标记不证明平台创建上传任务；必须读取精确素材/视频资源的真实任务ID或已有YouTube链接，执行fireplay-youtube-handoff登记。'
                '缺受理证据时保留待补传，沿已有素材ID启用/恢复YouTube上传，不重复入库或重做视频；未知写入先核查。'
                '取得真实初始受理后不跟踪YouTube后续进度；仅有入库绑定不能整项结案。')
    return ('上传必须显式核验需求组、实际YouTube账号组和任务组；没有实际支持的路径只暂停上传，不默认选账号。')


def _department(value):
    return value[3:] if isinstance(value, str) and value.startswith('od-') else value


def _expected(record):
    row = record['snapshot']['row']
    return {'id': _department(row['deptId']), 'name': row['deptName']}


def block_packet(record):
    return {'state': 'needs_explicit_youtube_routing', 'expected_department': _expected(record),
            'external_call_executed': False, 'default_youtube_import_allowed': False,
            'next': 'Use an actually supported explicit-account upload path. Verify the selected account department against the requirement, record fireplay-youtube-route, then dispatch exactly once. shared_dept_id is not YouTube routing.'}


def record_route(code, spec, index=1, root=ROOT):
    from . import fireplay
    spec = fireplay.payload(spec)
    path = fireplay._folder(code, root) / f'return-{index}.json'
    with lock(fireplay._folder(code, root) / 'request.lock'):
        record, box = fireplay._record(code, root), read_json(path)
        key, phase, item = fireplay._next_operation(box)
        require(phase == 'import' and key not in box['operations'], 'Resolve the existing operation before selecting a new upload route')
        require(spec.get('video_sha256', item['sha256']) == item['sha256'] and
                spec.get('operation_id', key) == key, 'Account selection belongs to another video/operation')
        route = {**spec, 'method': spec.get('method'), 'video_sha256': item['sha256'], 'operation_id': key}
        validate(record, route, root)
        old = item.get('youtube_route')
        require(not old or old['account']['id'] == route['account']['id'],
                'An account selection is already frozen; inspect it before replacing the account')
        item['youtube_route'] = route
        write_json(path, box)
        return {'state': 'explicit_route_prepared', 'operation_id': key, 'expected_department': _expected(record),
                'selected_account_id': route['account']['id'], 'external_call_executed': False}


def validate(record, route, root=ROOT):
    from .fireplay import _uuid
    require(route.get('method') == 'host_web_account_selection', 'Current MCP import has no explicit YouTube routing fields')
    expected, account = _expected(record), route.get('account', {})
    require(_uuid(account.get('id')) and route.get('selected_account_id') == account.get('id'),
            'Need the actual selected account ID, not an automatic default')
    require(_department(account.get('department_id')) == expected['id'] and account.get('department_name') == expected['name'],
            'YouTube account group differs from the requirement group')
    require(route.get('selection_verified') is True and route.get('video_sha256'), 'Verify the actual per-video account selection')
    try:
        moment = datetime.fromisoformat(route['observed_at'].replace('Z', '+00:00'))
        age = (datetime.now(timezone.utc)-moment).total_seconds()
    except (KeyError, ValueError, TypeError, AttributeError):
        age = -999
    require(-60 <= age <= policy(root).get('selection_max_age_seconds', 600), 'Refresh the actual account selection before submission')
    evidence = route.get('evidence', {})
    file = inside(root, evidence.get('path', ''))
    require(file.is_relative_to((Path(root)/'work/runs').resolve()) or
            file.is_relative_to((Path(root)/'state/fireplay'/record['code']).resolve()),
            'Keep account-selection evidence in the task-owned work/state directory')
    require(file.is_file() and file_hash(file) == evidence.get('sha256'), 'Account-selection evidence is missing or changed')


def verify_task(record, operation, spec, material_id, root=ROOT):
    if not policy(root).get('require_requirement_group'):
        return  # Latest user policy delegates YouTube routing to Fireplay.
    route = operation.get('youtube_route')
    if not route:
        return  # Historical, already dispatched operations keep their original evidence.
    task = spec.get('youtube_task_verification', {})
    expected = _expected(record)
    from .fireplay import _uuid
    exception_path = Path(root) / 'state/fireplay' / record['code'] / 'task-group-user-exception.json'
    if exception_path.exists():
        exception = read_json(exception_path)
        require(exception.get('authority') == 'user' and exception.get('authorization_ref')
                and exception.get('source_quote') and exception.get('ignore_task_group_display') is True
                and exception.get('requirement_id') == record['requirement_id']
                and exception.get('content_version') == record['content_version']
                and route['video_sha256'] in exception.get('video_sha256s', []),
                'User task-group exception does not match this requirement/video')
        require(task.get('user_exception_sha256') == file_hash(exception_path)
                and task.get('material_id') == material_id
                and task.get('account_id') == route['account']['id']
                and _department(task.get('account_department_id')) == expected['id']
                and task.get('account_department_name') == expected['name']
                and task.get('verification_scope') == 'selected_account_and_fireplay_acceptance_user_exception',
                'Exception receipt must retain the selected account and exact material acceptance')
        return  # Explicit task-scoped user decision; never claim task-group or downstream completion.
    require(task.get('material_id') == material_id and _uuid(task.get('task_id')) and
            task.get('account_id') == route['account']['id'], 'Read back the exact material task and actually assigned account')
    require(_department(task.get('account_department_id')) == expected['id'] and
            task.get('account_department_name') == expected['name'] and
            _department(task.get('task_department_id')) == expected['id'],
            'Actual YouTube task/account group mismatch; retain the material ID and reconcile without re-uploading')
