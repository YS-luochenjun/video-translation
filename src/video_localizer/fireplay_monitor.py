"""Host-driven periodic discovery. Business text never issues authority or credits.

The scheduler wakes a real Agent; it uses the authenticated host connector and
returns actual pages and content decisions here. This module never impersonates
the connector, creates chats, submits paid jobs, or declares a video reviewed.
"""
from pathlib import Path
from datetime import datetime

from . import fireplay
from .common import ROOT, WorkflowError, lock, object_hash, read_json, require, utc_now, write_json


def _directory(root):
    return Path(root) / 'state/fireplay/monitor'


def policy(root=ROOT):
    value = read_json(Path(root) / 'config/fireplay-monitor.json')
    require(value.get('enabled') is True, 'Fireplay monitor is disabled')
    authority = value.get('authority', {})
    require(authority.get('authority') == 'user' and authority.get('authorization_ref')
            and authority.get('source_quote'), 'Monitor needs actual standing user authority')
    selected = [person['id'] for person in value.get('assignees', [])]
    require(selected and len(selected) == len(set(selected)) and value.get('scope_update_quote'),
            'Resolve the user-selected assignees before monitoring')
    require(value.get('assignee_mode') in ('hint_only', 'strict'), 'Unknown assignee selection policy')
    filters = {'assignee_ids': selected} if value['assignee_mode'] == 'strict' else {}
    require(value['query'] == {'scope': 'all', 'view': 'summary', 'asset_type': 'video', **filters,
                              'pagination': 'cursor', 'limit': 200, 'offset': 0},
            'Monitor must scan all visible video groups with complete cursor pagination')
    return value


def _matches(row, config):
    if config['assignee_mode'] == 'hint_only':
        return True
    return bool(set(row.get('assigneeIds') or []) & set(config['query']['assignee_ids']))


def _state(root):
    path = _directory(root) / 'state.json'
    return read_json(path) if path.exists() else {'schema_version': 1, 'requirements': {}}


def _time(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result.timestamp() if result.tzinfo else None
    except (AttributeError, ValueError, TypeError):
        return None


def _summary_version(row):
    return object_hash({key: row.get(key) for key in ('title', 'locales', 'quantity', 'deptId', 'assetType')})


def _rows(spec, config):
    pages = spec.get('summary_pages')
    require(isinstance(pages, list) and pages, 'Need actual summary page receipts')
    expected, rows, seen_ids, page_hashes = None, [], set(), []
    for position, page in enumerate(pages):
        require(isinstance(page, dict) and 'arguments' in page and 'response' in page,
                'Each page needs its actual arguments and response')
        args, response = page['arguments'], fireplay.payload(page['response'])
        require(args == {**config['query'], **({'cursor': expected} if expected else {})},
                'Keep exact monitor filters and follow the cursor chain from the first page')
        require(position == 0 or expected, 'Page provided after pagination ended')
        require(isinstance(response.get('items'), list), 'Summary response needs items')
        for row in response['items']:
            require(fireplay._uuid(row.get('id')) and row.get('assetType') == 'video',
                    'Visible video row needs its real requirement UUID')
            require(_matches(row, config), 'Response includes a requirement outside the selected assignees')
            require(row['id'] not in seen_ids, 'Duplicate row in live pagination; refresh the scan')
            seen_ids.add(row['id'])
            rows.append(row)
        page_hashes.append(object_hash(page))
        expected = response.get('next_cursor')
        require(not response.get('has_more') or expected, 'Incomplete pagination without a cursor')
    return rows, expected, page_hashes


def scan(spec=None, root=ROOT):
    config = policy(root)
    if spec is None:
        return {'state': 'needs_summary', 'host_actions': [{'tool': 'requirement_list', 'arguments': config['query']}],
                'external_write': False, 'workflow': 'agent/workflows/fireplay-monitor.md'}
    spec = fireplay.payload(spec)
    rows, cursor, hashes = _rows(spec, config)
    if cursor:
        return {'state': 'needs_more_pages', 'host_actions': [{'tool': 'requirement_list',
                'arguments': {**config['query'], 'cursor': cursor}}], 'checkpoint_advanced': False}
    path = _directory(root) / 'state.json'
    with lock(path.with_suffix('.lock')):
        state = _state(root)
        first = not state.get('baseline_at')
        now, fresh, changed = utc_now(), [], []
        activation = _time(config['activated_at'])
        require(activation is not None, 'Monitor activation needs a real timezone-aware timestamp')
        codes = {}
        for row in rows:
            code = row.get('code')
            require(not code or code not in codes, 'Duplicate code with different IDs; refresh before dispatch')
            codes[code] = row['id']
            previous = state['requirements'].get(row['id'])
            entry = previous or {'first_seen_at': now, 'state': 'baseline'}
            try:
                fireplay._code(code)
            except WorkflowError:
                entry.update(state='unsupported_code', reason='Exact platform code does not match the supported intake format',
                             row=row, summary_version=_summary_version(row), last_seen_at=now)
                state['requirements'][row['id']] = entry
                continue
            registered = (Path(root) / 'state/fireplay' / code / 'request.json').is_file()
            if registered:
                registered_record = read_json(Path(root) / 'state/fireplay' / code / 'request.json')
                entry['state'] = 'needs_information' if registered_record.get('blockers') else 'registered'
                if previous and (previous['row'].get('updatedAt') != row.get('updatedAt') or
                                 previous['summary_version'] != _summary_version(row)):
                    entry['review_pending'] = True
            elif previous is None:
                if (_time(row.get('createdAt')) or 0) >= activation:
                    entry.update(state='needs_review', reason='newly_created')
                    fresh.append(code)
                elif not first:
                    entry.update(state='newly_visible_old', reason='Creation predates activation; no automatic historical backlog')
            elif not _matches(previous['row'], config):
                entry.update(state='needs_review', reason='new_assignment_in_scope')
                fresh.append(code)
            elif previous['row'].get('updatedAt') != row.get('updatedAt') or previous['summary_version'] != _summary_version(row):
                # Changes can be status-only. The Agent compares actual brief
                # content; an updated timestamp alone never starts paid work.
                entry.update(state='needs_review', reason='updated_content_or_metadata',
                             previous_summary_version=previous['summary_version'],
                             previous_row=previous['row'])
                changed.append(code)
            entry.update(row=row, summary_version=_summary_version(row), last_seen_at=now)
            state['requirements'][row['id']] = entry
        scan_id = object_hash(hashes)
        state.update(last_success_at=now, last_scan_id=scan_id, visible_count=len(rows),
                     baseline_at=state.get('baseline_at', now), policy_sha256=object_hash(config))
        write_json(_directory(root) / 'scans' / (scan_id + '.json'),
                   {'completed_at': now, 'page_hashes': hashes, 'rows': len(rows), 'new_codes': fresh,
                    'changed_codes': changed, 'first_baseline': first, 'authority': config['authority']})
        write_json(path, state)
    return status(root)


def _ordered(items):
    ranks = {'P0': 0, 'P1': 1, 'P2': 2}
    return sorted(items, key=lambda x: (ranks.get(x.get('priority'), 3), x.get('code') or ''))


def assess(code, spec, root=ROOT):
    """Record real Agent judgment on a fresh brief; no keyword-based auto-accept."""
    fireplay._code(code)
    config = policy(root)
    spec = fireplay.payload(spec)
    snap = fireplay.snapshot(code, spec['snapshot'])
    decision, row = spec['decision'], snap['row']
    require(_matches(row, config), 'Requirement is no longer assigned to the selected people')
    require(isinstance(decision.get('is_translation'), bool) and decision.get('reason')
            and decision.get('evidence'), 'Agent must judge translation scope with actual brief evidence')
    allowed = {'brief.title', 'brief.description', 'brief.refText', 'brief.locales', 'summary.title', 'summary.locales'}
    require(isinstance(decision['evidence'], list) and set(decision['evidence']) <= allowed,
            'Use actual summary/brief fields as content evidence')
    for reference in decision['evidence']:
        view, key = reference.split('.')
        require((snap['brief'] if view == 'brief' else row).get(key), 'Referenced content evidence is empty')
    require(_time(snap.get('server_time')) is not None and
            -60 <= _time(utc_now()) - _time(snap['server_time']) <= 600,
            'Refresh current summary and brief before assessing a requirement')
    path = _directory(root) / 'state.json'
    with lock(path.with_suffix('.lock')):
        state = _state(root)
        entry = state['requirements'].get(row['id'])
        require(entry and entry['row']['code'] == code, 'Requirement was not discovered in the authorized monitor')
        require(entry['state'] in ('needs_review', 'needs_information', 'admitted', 'registered') or
                (spec.get('recheck') is True and entry['state'] in ('baseline', 'ignored', 'historical_translation_pending')),
                'Historical/newly-visible backlog is not automatically authorized')
        old_record = Path(root) / 'state/fireplay' / code / 'request.json'
        if old_record.exists():
            old = read_json(old_record)
            if old['content_version'] != snap['content_version']:
                entry.update(state='needs_revision_review', reason='Existing requirement changed; preserve its chat, budget and work',
                             proposed_content_version=snap['content_version'], review_pending=False)
                write_json(path, state)
                return {'code': code, 'state': entry['state'], 'chat': old.get('chat'), 'budget': old.get('budget')}
        uncertain_historical = False
        if not old_record.exists() and (entry.get('reason') == 'updated_content_or_metadata' or spec.get('recheck') is True):
            old_brief = entry.get('assessed_brief_version')
            summary_changed = entry.get('previous_summary_version', entry.get('summary_version')) != _summary_version(row)
            # Without an old brief, unchanged summary cannot prove new content.
            if not summary_changed and (not old_brief or old_brief == snap['content_version']):
                uncertain_historical = decision['is_translation']
        saved = {'code': code, 'requirement_id': row['id'], 'snapshot': spec['snapshot'], 'decision': decision,
                 'assessed_at': utc_now(), 'authority': config['authority']}
        write_json(_directory(root) / 'assessments' / (object_hash(saved) + '.json'), saved)
        entry.update(assessed_brief_version=snap['content_version'], decision=decision, row=row,
                     summary_version=_summary_version(row), review_pending=False)
        if uncertain_historical:
            entry.update(state='historical_translation_pending',
                         reason='Translation intent confirmed; historical content timing unproven. Keep visible for scope confirmation, do not mark non-translation or restart automatically.')
        elif not decision['is_translation']:
            entry.update(state='ignored', reason=decision['reason'])
        elif row.get('status') not in config['eligible_statuses'] or row.get('canBindMaterials') is not True:
            entry.update(state='not_eligible', reason='Not in an eligible status or lacks execution permission')
        else:
            authority = {**config['authority'], 'scope_update_quote': config['scope_update_quote'],
                         'authorization_ref': config['authority']['authorization_ref'] + ':' + row['id'],
                         'standing_authorization_ref': config['authority']['authorization_ref'], 'mode': 'first',
                         'user_request': config['authority']['source_quote'] + '\n自动发现并独立制作：' + code,
                         'scope_requirement': code, 'requirement_id': row['id']}
            interpretation = {'authorization_ref': authority['authorization_ref'], 'source_quote': authority['source_quote'],
                              'quantity_mode': config['quantity_mode']}
            if decision.get('targets'):
                interpretation['targets'] = decision['targets']
            if old_record.exists():
                interpretation = old.get('decision', {})
            result = fireplay.register(code, spec['snapshot'], interpretation, root)
            authority_file = Path(root) / 'state/fireplay' / code / 'monitor-authority.json'
            if not authority_file.exists():
                write_json(authority_file, authority)
            entry.update(state='needs_information' if result['blockers'] else 'admitted',
                         reason='; '.join(result['blockers']) or decision['reason'])
        write_json(path, state)
        return {'code': code, 'state': entry['state'], 'reason': entry['reason'],
                'authority_path': f'state/fireplay/{code}/monitor-authority.json' if entry['state'] in ('admitted', 'needs_information') else None}


def followups(root=ROOT):
    """Navigation only. Existing return gates still verify every actual package."""
    config = policy(root)
    index_path = Path(root) / 'outputs/index.json'
    packages = read_json(index_path).get('entries', []) if index_path.exists() else []
    result = []
    for path in (Path(root) / 'state/fireplay').glob('*/request.json'):
        record = read_json(path)
        if not _matches(record['snapshot']['row'], config):
            continue
        for video in record['videos']:
            chat = video.get('chat') or record.get('chat', {})
            if chat.get('state') != 'ready':
                continue
            from .fireplay_submission import bound_materials
            # User 2026-10-27: stop after Fireplay acceptance; downstream
            # YouTube queues and retries belong to Fireplay, not this monitor.
            if bound_materials(record, video, root):
                continue
            box = path.parent / f'return-{video["index"]}.json'
            pending_locales = None
            manual = path.parent / f'user-approved-return-{video["index"]}.json'
            if manual.exists() and read_json(manual).get('state') == 'returned_user_approved':
                continue
            if box.exists():
                outbox = read_json(box)
                if outbox.get('state') == 'returned':
                    pending_locales = outbox.get('pending_locales')
                    if not pending_locales:
                        continue
            if box.exists() and pending_locales is None:
                operations = outbox.get('operations', {})
                operations = operations.values() if isinstance(operations, dict) else operations
                action = 'reconcile_return' if any(op.get('state') == 'unknown' for op in operations) else 'resume_return'
                identity = object_hash(outbox)
            else:
                matching = [p for p in packages if p.get('origin_run_id') in video.get('members', [])
                            and p.get('source_sha256') == video.get('source', {}).get('sha256')
                            and (pending_locales is None or p.get('target_language') in pending_locales)
                            and p.get('status') in ('delivered', 'delivered_with_issues')]
                latest = {}
                for package in sorted(matching, key=lambda p: p.get('archived_at') or ''):
                    latest[package.get('target_language')] = package
                matching = list(latest.values())
                if set(p.get('target_language') for p in matching) != set(pending_locales or video['targets']):
                    continue
                # Historical browser submissions may predate the canonical
                # outbox. Match actual bytes/IDs and verified binding, not names.
                submitted = False
                for receipt_path in path.parent.glob('*/verified-*-materials.json'):
                    verified = read_json(receipt_path)
                    if (verified.get('bound_requirement') != record['requirement_id'] or
                            verified.get('source_sha256') != video.get('source', {}).get('sha256')):
                        continue
                    actual = {r.get('locale'): r for r in verified.get('rows', []) if fireplay._uuid(r.get('material_id'))
                              and all(r.get(k) is True for k in ('name_verified','tags_verified','sharing_verified','byte_identity_verified'))}
                    if all(p['target_language'] in actual and
                           actual[p['target_language']].get('sha256') == p.get('video_sha256') for p in matching):
                        submitted = True
                        break
                if submitted:
                    continue
                action, identity = 'auto_return', object_hash(matching)
                blocked = False
                for package in matching:
                    if package.get('status') == 'delivered_with_issues':
                        digest = package.get('video_sha256') or ''
                        review_file = path.parent / 'publication-reviews' / (digest + '.json')
                        if not review_file.exists():
                            action = 'review_publication'
                        elif read_json(review_file).get('decision') != 'minor_issues_acceptable':
                            blocked = True
                if blocked:
                    continue
            task = {'code': record['code'], 'video_index': video['index'], 'threadId': chat['threadId'],
                    'hostId': chat.get('hostId', 'local'), 'action': action, 'artifact_identity': identity}
            task['key'] = object_hash(task)
            note = _directory(root) / 'signals' / (task['key'] + '.json')
            task['signal_state'] = read_json(note)['state'] if note.exists() else 'prepared'
            result.append(task)
    return result


def signal(spec, root=ROOT):
    """Journal exactly once BEFORE the host sends an authorized owner follow-up."""
    policy(root)
    spec = fireplay.payload(spec)
    task = next((t for t in followups(root) if t['key'] == spec.get('key')), None)
    require(task, 'Follow-up inputs changed; refresh monitor status')
    path = _directory(root) / 'signals' / (task['key'] + '.json')
    with lock(path.with_suffix('.lock')):
        old = read_json(path) if path.exists() else None
        if old:
            if spec.get('response'):
                response = fireplay.payload(spec['response'])
                require(response.get('threadId') == task['threadId'], 'Follow-up receipt belongs to another chat')
                old.update(state='sent', receipt=spec['response'], receipt_at=utc_now())
                write_json(path, old)
            return old
        require(not spec.get('response'), 'Journal follow-up dispatch before recording the receipt')
        from .kie_access import instruction as kie_access_instruction
        from .fireplay_youtube import instruction as youtube_instruction
        message = (f'按已授权项目流程继续需求{task["code"]}第{task["video_index"]}个原片的回传。'
                   f'当前待办：{task["action"]}。复用既有run、素材ID、outbox和真实回执；未知写入先核查，不重复上传。'
                   '用户已允许正式outputs完整成品的普通小瑕疵，按fireplay-publication-review记录实际严重度；合格或小瑕疵直接提交，不再询问固定动作。严重/多项影响观看的问题、漏译或缺少必需配音阻止上传，保留质量结论。'
                   + kie_access_instruction(root) +
                   youtube_instruction(root) +
                   'Fireplay受理并核验共享、标签及绑定后就收尾；不跟踪YouTube进度，不因排队/限额重入库。'
                   + fireplay.submission_instruction(root))
        value = {'state': 'unknown', 'task': task, 'dispatched_at': utc_now(),
                 'host_action': {'tool': 'send_message_to_thread', 'arguments': {
                     'threadId': task['threadId'], 'hostId': task['hostId'], 'prompt': message}}}
        write_json(path, value)
        return value


def status(root=ROOT):
    config, state = policy(root), _state(root)
    review, queue, revisions, historical = [], [], [], []
    for entry in state['requirements'].values():
        row = entry['row']
        if not _matches(row, config):
            continue
        packet = {key: row.get(key) for key in ('id', 'code', 'priority', 'title', 'deptName', 'createdAt', 'updatedAt')}
        packet.update(state=entry['state'], reason=entry.get('reason'))
        if entry['state'] == 'needs_review' or entry.get('review_pending'):
            packet['host_action'] = {'tool': 'requirement_list', 'arguments': {
                'scope': 'all', 'view': 'blind_brief', 'requirement_ids': [row['id']]}}
            review.append(packet)
        if entry['state'] == 'needs_revision_review':
            revisions.append(packet)
        if entry['state'] == 'historical_translation_pending':
            historical.append(packet)
        if entry['state'] in ('admitted', 'registered'):
            p = Path(root) / 'state/fireplay' / row['code'] / 'request.json'
            if p.exists() and not read_json(p).get('blockers') and read_json(p).get('chat', {}).get('state') != 'ready':
                queue.append(packet)
    return {'state': 'ready' if state.get('baseline_at') else 'needs_baseline', 'interval_minutes': config['interval_minutes'],
            'scope': config['group_policy'], 'baseline_at': state.get('baseline_at'), 'last_success_at': state.get('last_success_at'),
            'visible_count': state.get('visible_count', 0), 'needs_review': _ordered(review), 'ready_to_dispatch': _ordered(queue),
            'revision_reviews': _ordered(revisions),
            'historical_translation_candidates': _ordered(historical),
            'publication_followups': followups(root), 'max_active_requirements': config['max_active_requirements'],
            'p1_waits_for_p0': False, 'automatic_paid_execution_by_script': False}
