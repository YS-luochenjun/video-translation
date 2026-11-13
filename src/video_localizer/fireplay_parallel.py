"""Persistent source ownership for host-delegated Fireplay production.

This is a coordination journal, not a process runner or a security sandbox.
It never creates chats, submits models, changes budgets, or writes to Fireplay.
Unknown dispatches and expired leases retain ownership until reconciled.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import re

from .common import ROOT, file_hash, inside, lock, object_hash, read_json, require, utc_now, write_json
from .fireplay import _code, _uuid


LIVE = {'active', 'dispatch_unknown', 'blocked'}
TERMINAL = {'worker_complete', 'released'}


def policy(root=ROOT):
    path = Path(root) / 'config/fireplay-parallel.json'
    value = read_json(path) if path.exists() else {'enabled': False}
    for field, default in (('max_active_sources_per_requirement', 2),
                           ('max_active_sources_global', 15), ('lease_minutes', 120)):
        number = value.get(field, default)
        require(isinstance(number, int) and not isinstance(number, bool) and number > 0,
                'Parallel policy limits must be positive integers')
        value[field] = number
    return value


def _path(root):
    return Path(root) / 'state/fireplay/parallel.json'


def _state(root):
    path = _path(root)
    return read_json(path) if path.exists() else {'schema_version': 1, 'tasks': {}}


def _record(code, root):
    return read_json(inside(Path(root) / 'state/fireplay', _code(code)) / 'request.json')


def _owner(record):
    chat = record.get('chat', {})
    require(chat.get('state') == 'ready' and _uuid(chat.get('threadId')),
            'Parallel production requires the existing ready owner chat')
    return chat['threadId']


def _scope(record, video, root):
    """Derive paths from the registered source only; callers cannot widen them."""
    root = Path(root).resolve()
    require(record.get('budget') and video.get('members') and video.get('pilot'),
            'Source needs owner fireplay-start and its original shared budget before delegation')
    source = video.get('source') or {}
    sha = source.get('sha256')
    require(isinstance(sha, str) and re.fullmatch('[0-9a-f]{64}', sha),
            'Source must have a registered SHA256 before delegation')
    source_path = inside(root, source.get('path', ''))
    require(source_path.is_file() and file_hash(source_path) == sha,
            'Source file is missing or its current SHA256 changed')
    runs = list(dict.fromkeys([*(video.get('members') or []),
                              *([video['pilot']] if video.get('pilot') else [])]))
    paths = []
    for name in runs:
        require(isinstance(name, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', name),
                'Registered run id is invalid')
        path = inside(root, 'runs/' + name)
        paths.append(path.relative_to(root).as_posix())
    identity = {'requirement_id': record['requirement_id'],
                'content_version': video.get('source_scope_content_version', record['content_version']),
                'video_index': video['index'], 'source_sha256': sha}
    return {'task_id': object_hash(identity), **identity,
            'source_path': source_path.relative_to(root).as_posix(),
            'targets': list(video.get('targets') or record.get('targets') or []),
            'allowed_paths': sorted(set(paths)), 'budget_id': record.get('budget'),
            'owner_thread_id': _owner(record)}


def _expiry(task):
    raw = task.get('lease_expires_at')
    return bool(raw and datetime.fromisoformat(raw) <= datetime.now(timezone.utc))


def _public(task):
    return {**task, 'lease_expired': _expiry(task), 'auto_reassign': False,
            'whole_requirement_complete': False}


def status(code=None, root=ROOT):
    if code is not None:
        _code(code)
    tasks = [_public(t) for t in _state(root)['tasks'].values() if code is None or t['code'] == code]
    return {'policy': policy(root), 'tasks': tasks,
            'active_source_count': sum(t['state'] in LIVE for t in tasks),
            'external_actions': False, 'whole_requirement_completion_authority': 'existing_owner_only'}


def plan(code, root=ROOT):
    """Read-only source plan. Existing work must be inspected before a claim."""
    record = _record(code, root)
    owner = _owner(record)
    registry = _state(root)['tasks']
    settings = policy(root)
    result = []
    for video in record['videos']:
        item = {'video_index': video['index'], 'targets': video.get('targets', []), 'runnable': False}
        from .fireplay_submission import coverage
        if coverage(record, video, root)['complete']:
            item.update(state='already_bound', reason='All source locales already have verified acceptance; do not reproduce')
            result.append(item)
            continue
        if not record.get('budget') or not video.get('members') or not video.get('pilot'):
            item.update(state='needs_owner_start', reason='Owner must bind source runs to the existing shared budget before claiming')
            result.append(item)
            continue
        try:
            scope = _scope(record, video, root)
        except Exception as exc:
            # Missing/changed sources stay explicit, without fabricating a worker.
            from .common import WorkflowError
            if not isinstance(exc, (WorkflowError, FileNotFoundError)):
                raise
            item.update(state='source_not_ready', reason=str(exc))
        else:
            existing = registry.get(scope['task_id'])
            other = [t for t in registry.values() if t['requirement_id'] == scope['requirement_id']
                     and t['video_index'] == scope['video_index'] and t['state'] in LIVE
                     and t['task_id'] != scope['task_id']]
            item.update(scope, state=existing['state'] if existing else 'unclaimed',
                        runnable=settings.get('enabled') is True and not existing and not other and not record.get('blockers'),
                        task=_public(existing) if existing else None,
                        previous_live_claims=[t['task_id'] for t in other])
        result.append(item)
    return {'code': code, 'owner_thread_id': owner, 'budget_id': record.get('budget'),
            'sources': result, 'policy': policy(root), 'read_only': True,
            'next_action': 'Owner inspects existing tasks/files, claims its own source, then claims one independent source before spawning a child'}


def _evidence(paths, root, allowed=None):
    require(isinstance(paths, list) and bool(paths), 'Actual evidence files are required')
    result = []
    for value in paths:
        require(isinstance(value, str), 'Evidence must contain workspace-relative paths')
        path = inside(root, value)
        require(path.is_file(), 'Evidence file does not exist')
        if allowed is not None:
            require(any(path.is_relative_to(inside(root, folder)) for folder in allowed),
                    'Completion evidence is outside the assigned source paths')
        result.append({'path': path.relative_to(Path(root).resolve()).as_posix(), 'sha256': file_hash(path)})
    return result


def _touch(task, settings):
    task['updated_at'] = utc_now()
    task['lease_expires_at'] = (datetime.now(timezone.utc) + timedelta(minutes=settings['lease_minutes'])).isoformat(timespec='seconds')


def _current(task, record, root):
    video = next((v for v in record['videos'] if v['index'] == task['video_index']), None)
    require(video is not None, 'Assigned source was removed; reconcile or release the old task')
    scope = _scope(record, video, root)
    require(scope['task_id'] == task['task_id'], 'Assigned source or content version changed; review before continuing')
    require(scope['allowed_paths'] == task['allowed_paths'], 'Assigned run paths changed; reconcile the source scope')
    require(scope['targets'] == task['targets'] and scope['budget_id'] == task['budget_id'],
            'Assigned targets or shared budget changed; review the original claim')


def update(code, spec, root=ROOT):
    require(isinstance(spec, dict), 'Expected a parallel update object')
    settings = policy(root)
    require(settings.get('enabled') is True, 'Source parallel production is not enabled')
    action = spec.get('action')
    require(action in {'claim', 'heartbeat', 'release', 'block', 'complete', 'reconcile'},
            'Unknown parallel action')
    path = _path(root)
    with lock(path.with_suffix('.lock')):
        state = _state(root)
        record = _record(code, root)
        owner = _owner(record)
        actor = spec.get('actor_id')
        token = spec.get('claim_token')
        require(isinstance(token, str) and 8 <= len(token) <= 200, 'Stable claim_token of 8 to 200 characters is required')
        require('allowed_paths' not in spec, 'Write paths are derived from the registered source; overrides are prohibited')
        if action == 'claim':
            require(actor == owner and spec.get('owner_thread_id') == owner,
                    'Only the existing owner chat can claim a source')
            require(not record.get('blockers'), 'Resolve requirement blockers before delegation')
            video = next((v for v in record['videos'] if v['index'] == spec.get('video_index')), None)
            require(video is not None, 'Exact registered video_index is required')
            from .fireplay_submission import coverage
            require(not coverage(record, video, root)['complete'],
                    'Source is already fully bound; no automatic reproduction')
            scope = _scope(record, video, root)
            previous = state['tasks'].get(scope['task_id'])
            if previous and previous['claim_token'] == token:
                _current(previous, record, root)
                return _public(previous)
            require(not previous or previous['state'] == 'released', 'Source already has an owner; inspect its current claim')
            require(not any(t['state'] in LIVE and t['requirement_id'] == scope['requirement_id']
                            and t['video_index'] == scope['video_index'] for t in state['tasks'].values()),
                    'A previous source/content version still owns this video; reconcile or release it')
            live = [t for t in state['tasks'].values() if t['state'] in LIVE]
            require(len(live) < settings['max_active_sources_global'], 'Global active source limit reached')
            require(sum(t['requirement_id'] == scope['requirement_id'] for t in live)
                    < settings['max_active_sources_per_requirement'], 'Requirement active source limit reached')
            kind = spec.get('assignee_kind')
            require(kind in ('owner', 'subagent'), 'Assignee kind must be owner or subagent')
            assignee = spec.get('assignee_id')
            require((kind == 'owner' and assignee == owner) or (kind == 'subagent' and not assignee),
                    'Owner claims must use the owner id; child dispatch must start unknown before actual spawn')
            task = {**scope, 'code': code, 'claim_token': token, 'assignee_kind': kind,
                    'assignee_id': assignee, 'state': 'active' if kind == 'owner' else 'dispatch_unknown',
                    'created_at': utc_now(), 'history': list(previous.get('history', [])) if previous else [],
                    'permissions': {'production_only': True, 'paid_submission': False, 'budget_mutation': False,
                                    'platform_submission': False, 'spawn_children': False}}
            if previous:
                task['history'].append({'action': 'previous_claim', 'task': {k: v for k, v in previous.items() if k != 'history'}})
        else:
            task = state['tasks'].get(spec.get('task_id'))
            require(task is not None and task['code'] == code, 'Exact existing source task is required')
            require(task['claim_token'] == token, 'Claim token does not match')
            require(actor == owner or (actor == task.get('assignee_id') and actor is not None),
                    'Only the owner or the assigned worker can update this task')
            require(task['owner_thread_id'] == owner, 'Owner chat changed; inspect the original delegation before recovery')
            if action == 'release':
                require(actor == owner, 'Only the owner chat can release source ownership')
                require(spec.get('relinquish') is True and spec.get('work_stopped') is True and spec.get('reason'),
                        'Release requires explicit relinquish, stopped-work confirmation and reason')
                if task['state'] == 'dispatch_unknown':
                    require(spec.get('reconciled_no_worker') is True,
                            'Unknown dispatch must be reconciled before release; expiry is insufficient')
                task['release_evidence'] = _evidence(spec.get('evidence'), root)
                task['state'] = 'released'
            elif action == 'reconcile':
                require(actor == owner, 'Only the owner chat can reconcile actual worker identity')
                require(task['state'] == 'dispatch_unknown', 'Only unknown dispatch accepts a worker receipt')
                assignee = spec.get('assignee_id')
                require(isinstance(assignee, str) and bool(assignee.strip()) and assignee != owner,
                        'Actual distinct spawned worker id is required')
                task['dispatch_evidence'] = _evidence(spec.get('evidence'), root)
                require(any(assignee in inside(root, item['path']).read_text(encoding='utf-8')
                            for item in task['dispatch_evidence']), 'Dispatch evidence must contain the actual worker id')
                task.update(assignee_id=assignee, state='active')
                # A stale task can be attached to its real worker for recovery, but cannot proceed.
                try:
                    _current(task, record, root)
                except Exception as exc:
                    from .common import WorkflowError
                    if not isinstance(exc, (WorkflowError, FileNotFoundError)):
                        raise
                    task.update(state='blocked', reason='Stale source scope after dispatch: ' + str(exc))
            else:
                require(task['state'] in LIVE and task['state'] != 'dispatch_unknown',
                        'Reconcile actual worker first; completed/released tasks cannot continue')
                if action == 'block':
                    require(spec.get('reason'), 'Blocked source needs a concrete reason')
                    task['block_evidence'] = _evidence(spec.get('evidence'), root)
                    task.update(state='blocked', reason=spec['reason'])
                else:
                    if action == 'heartbeat':
                        require(task['state'] == 'active', 'Blocked source needs explicit owner review, not an automatic resume')
                    elif action == 'complete':
                        require(task['state'] == 'active', 'Blocked source cannot be completed')
                    _current(task, record, root)
                    if action == 'complete':
                        task['completion_evidence'] = _evidence(spec.get('evidence'), root, task['allowed_paths'])
                        task.update(state='worker_complete', result='handed_off_for_owner_review')
        _touch(task, settings)
        task['history'].append({'action': action, 'actor_id': actor, 'at': utc_now(),
                                'state': task['state'], 'reason': spec.get('reason')})
        state['tasks'][task['task_id']] = task
        write_json(path, state)
        return _public(task)


def instruction(root=ROOT):
    settings = policy(root)
    if settings.get('enabled') is not True:
        return ''
    return ('\n多原片按原片并行：保留本需求原负责聊天和共享预算，先读 agent/workflows/fireplay-parallel.md，'
            '用 fireplay-parallel plan 登记前检查各原片现场；负责聊天先认领自己处理的原片，'
            '再逐条claim登记dispatch_unknown，实际spawn子代理后用真实回执reconcile绑定。'
            f'每需求最多{settings["max_active_sources_per_requirement"]}条活跃原片（含负责聊天），'
            f'全局登记最多{settings["max_active_sources_global"]}条。每条原片仅一个负责人，'
            '子代理只写分派run目录、不再分派、不新建预算、不发付费模型、不做平台提交；'
            '所需付费调用交原负责聊天沿原账本调度。已发模型及未知费用先查原任务，不重复制作。'
            'lease到期不自动夺取；unknown先核查真实子代理。子代理完成只代表交回审核，'
            '原聊天负责正式封装、逐版固定提交和全部原片/语言completion-check及close。')
