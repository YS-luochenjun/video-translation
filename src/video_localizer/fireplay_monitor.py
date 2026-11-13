"""Host-driven periodic discovery. Business text never issues authority or credits.

The scheduler wakes a real Agent; it uses the authenticated host connector and
returns actual pages and content decisions here. This module never impersonates
the connector, creates chats, submits paid jobs, or declares a video reviewed.
"""
from pathlib import Path
from datetime import datetime

from . import fireplay
from .common import ROOT, WorkflowError, file_hash, inside, lock, object_hash, read_json, require, utc_now, write_json


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
    polling = value.get('polling', {})
    require(value.get('eligible_statuses') == ['not_started', 'in_progress']
            and polling.get('page_size') == 40 and polling.get('tracked_batch_size') == 40
            and polling.get('full_reconciliation_hours') == 24
            and polling.get('authority', {}).get('authority') == 'user'
            and polling['authority'].get('authorization_ref') and polling['authority'].get('source_quote'),
            'Active polling needs its explicit scope authority and reconciliation policy')
    require(value['query'] == {'scope': 'all', 'view': 'summary', 'asset_type': 'video', **filters,
                              'status': value['eligible_statuses'],
                              'pagination': 'cursor', 'limit': polling['page_size'], 'offset': 0},
            'Monitor must scan both active statuses across all visible video groups with complete cursor pagination')
    return value


def _matches(row, config):
    if config['assignee_mode'] == 'hint_only':
        return True
    return bool(set(row.get('assigneeIds') or []) & set(config['query']['assignee_ids']))


def _conditional_intake(row, config):
    rules = config.get('conditional_intakes', [])
    matches = [r for r in rules if r.get('code') == row.get('code') or r.get('requirement_id') == row.get('id')]
    require(len(matches) <= 1, 'Duplicate conditional intake rule')
    if not matches:
        return None
    rule = matches[0]
    require(rule.get('code') == row['code'] and rule.get('requirement_id') == row['id']
            and isinstance(rule.get('assignee_id'), str) and rule['assignee_id'],
            'Conditional intake must bind an exact requirement and assignee ID')
    return rule


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


def _summary_changed(previous, row):
    return (previous['summary_version'] != _summary_version(row)
            or any(previous['row'].get(key) != row.get(key)
                   for key in ('updatedAt', 'status', 'canBindMaterials', 'assigneeIds')))


def _query(config, mode, requirement_ids=None):
    require(mode in ('active', 'full', 'tracked'), 'Unknown monitor scan_mode')
    query = dict(config['query'])
    if mode != 'active':
        query.pop('status')
    if mode == 'tracked':
        require(isinstance(requirement_ids, list) and requirement_ids
                and len(requirement_ids) <= config['polling']['tracked_batch_size']
                and len(set(requirement_ids)) == len(requirement_ids)
                and all(fireplay._uuid(value) for value in requirement_ids),
                'Tracked scan needs a bounded list of exact known requirement UUIDs')
        query['requirement_ids'] = requirement_ids
    else:
        require(requirement_ids is None, 'Discovery scans cannot narrow to requirement IDs')
    return query


def _polling_plan(config, state, watch, root):
    tracked = set()
    unresolved = {'needs_information', 'needs_revision_review', 'historical_translation_pending',
                  'waiting_for_assignment', 'admitted', 'needs_review'}
    for requirement_id, entry in state['requirements'].items():
        if _matches(entry['row'], config) and (entry['state'] in unresolved or entry.get('review_pending')):
            tracked.add(requirement_id)
    for member in watch.get('pending', []):
        tracked.add(member['requirement_id'])
    for path in (Path(root) / 'state/fireplay').glob('*/request.json'):
        record = read_json(path)
        if (_matches(record['snapshot']['row'], config)
                and (record.get('blockers') or record.get('chat', {}).get('state') != 'ready')):
            tracked.add(record['requirement_id'])
    ids = sorted(tracked)
    batch_size = config['polling']['tracked_batch_size']
    last_full = state.get('last_full_success_at') or state.get('last_success_at')
    full_due = (_time(utc_now()) - (_time(last_full) or 0)
                >= config['polling']['full_reconciliation_hours'] * 3600)
    return {'discovery': {'scan_mode': 'active', 'tool': 'requirement_list',
                          'arguments': _query(config, 'active')},
            'full_reconciliation_due': full_due,
            'full_reconciliation': {'scan_mode': 'full', 'tool': 'requirement_list',
                                    'arguments': _query(config, 'full')},
            'tracking': [{'scan_mode': 'tracked', 'tool': 'requirement_list',
                          'requirement_ids': ids[start:start + batch_size],
                          'arguments': _query(config, 'tracked', ids[start:start + batch_size])}
                         for start in range(0, len(ids), batch_size)],
            'tracked_count': len(ids), 'last_full_success_at': last_full,
            'last_active_success_at': state.get('last_active_success_at'),
            'last_tracked_success_at': state.get('last_tracked_success_at'),
            'active_visible_count': state.get('active_visible_count'),
            'tracking_gaps': state.get('tracking_gaps', {})}


def _rows(spec, config, query):
    pages = spec.get('summary_pages')
    require(isinstance(pages, list) and pages, 'Need actual summary page receipts')
    expected, rows, seen_ids, page_hashes, cursors = None, [], set(), [], set()
    for position, page in enumerate(pages):
        require(isinstance(page, dict) and 'arguments' in page and 'response' in page,
                'Each page needs its actual arguments and response')
        args, response = page['arguments'], fireplay.payload(page['response'])
        require(args == {**query, **({'cursor': expected} if expected else {})},
                'Keep exact monitor filters and follow the cursor chain from the first page')
        require(position == 0 or expected, 'Page provided after pagination ended')
        require(isinstance(response.get('items'), list), 'Summary response needs items')
        require(_time(response.get('serverTime')) is not None
                and -60 <= _time(utc_now()) - _time(response['serverTime']) <= 600,
                'Summary page needs a fresh serverTime; refresh the scan')
        require(response.get('returned', len(response['items'])) == len(response['items'])
                and not response.get('query_meta', {}).get('source_limit_reached'),
                'Summary page is truncated or has inconsistent row counts')
        for row in response['items']:
            require(fireplay._uuid(row.get('id')) and row.get('assetType') == 'video',
                    'Visible video row needs its real requirement UUID')
            require(_matches(row, config), 'Response includes a requirement outside the selected assignees')
            require('status' not in query or row.get('status') in query['status'],
                    'Response includes a requirement outside the requested active statuses')
            require('requirement_ids' not in query or row['id'] in query['requirement_ids'],
                    'Response includes a requirement outside the tracked UUIDs')
            require(row['id'] not in seen_ids, 'Duplicate row in live pagination; refresh the scan')
            seen_ids.add(row['id'])
            rows.append(row)
        page_hashes.append(object_hash(page))
        expected = response.get('next_cursor')
        require(not response.get('has_more') or expected, 'Incomplete pagination without a cursor')
        require(not response.get('next_offset') and
                (not response.get('query_meta', {}).get('total_exact')
                 or response.get('total') == len(response['items']) or expected),
                'Incomplete cursor pagination; refresh the scan')
        require(not expected or isinstance(expected, str) and expected not in cursors,
                'Repeated or invalid pagination cursor; refresh the scan')
        if expected:
            cursors.add(expected)
    return rows, expected, page_hashes


def scan(spec=None, root=ROOT):
    config = policy(root)
    spec = fireplay.payload(spec) if spec is not None else {}
    mode = spec.get('scan_mode', 'active')
    query = _query(config, mode, spec.get('requirement_ids'))
    if mode == 'tracked':
        known_ids = set(_state(root)['requirements'])
        for request_path in (Path(root) / 'state/fireplay').glob('*/request.json'):
            known_ids.add(read_json(request_path)['requirement_id'])
        require(set(query['requirement_ids']) <= known_ids, 'Tracked scan UUIDs must already be known locally')
    if 'summary_pages' not in spec:
        return {'state': 'needs_summary', 'scan_mode': mode,
                'host_actions': [{'tool': 'requirement_list', 'arguments': query}],
                'polling': status(root)['polling'], 'external_write': False,
                'workflow': 'agent/workflows/fireplay-monitor.md'}
    rows, cursor, hashes = _rows(spec, config, query)
    if cursor:
        return {'state': 'needs_more_pages', 'scan_mode': mode, 'host_actions': [{'tool': 'requirement_list',
                'arguments': {**query, 'cursor': cursor}}], 'checkpoint_advanced': False}
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
            conditional = _conditional_intake(row, config)
            if registered:
                registered_record = read_json(Path(root) / 'state/fireplay' / code / 'request.json')
                entry['state'] = 'needs_information' if registered_record.get('blockers') else 'registered'
                if previous and _summary_changed(previous, row):
                    entry['review_pending'] = True
            elif conditional and (not previous or previous.get('conditional_policy_version') != object_hash(conditional)):
                entry.update(state='needs_review', reason='human_conditional_intake_policy')
            elif previous is None:
                if (_time(row.get('createdAt')) or 0) >= activation:
                    entry.update(state='needs_review', reason='newly_created')
                    fresh.append(code)
                elif not first:
                    entry.update(state='newly_visible_old', reason='Creation predates activation; no automatic historical backlog')
            elif not _matches(previous['row'], config):
                entry.update(state='needs_review', reason='new_assignment_in_scope')
                fresh.append(code)
            elif (entry['state'] == 'not_eligible' and row.get('status') == 'in_progress'
                  and entry.get('eligibility_policy_version') != object_hash(config['eligible_statuses'])):
                entry.update(state='needs_review', reason='updated_content_or_metadata',
                             previous_summary_version=previous['summary_version'], previous_row=previous['row'])
                changed.append(code)
            elif _summary_changed(previous, row):
                # Changes can be status-only. The Agent compares actual brief
                # content; an updated timestamp alone never starts paid work.
                entry.update(state='needs_review', reason='updated_content_or_metadata',
                             previous_summary_version=previous['summary_version'],
                             previous_row=previous['row'])
                changed.append(code)
            entry.update(row=row, summary_version=_summary_version(row), last_seen_at=now,
                         eligibility_policy_version=object_hash(config['eligible_statuses']))
            state['requirements'][row['id']] = entry
        scan_id = object_hash({'scan_mode': mode, 'query': query, 'pages': hashes})
        state.update(policy_sha256=object_hash(config))
        state.update({f'last_{mode}_success_at': now, f'last_{mode}_scan_id': scan_id})
        if mode == 'full':
            state.update(last_success_at=now, last_scan_id=scan_id, visible_count=len(rows),
                         baseline_at=state.get('baseline_at', now))
        elif mode == 'active':
            state['active_visible_count'] = len(rows)
        else:
            returned_ids = {row['id'] for row in rows}
            for requirement_id in query['requirement_ids']:
                state.setdefault('tracking_checkpoints', {})[requirement_id] = {'checked_at': now, 'scan_id': scan_id}
                gaps = state.setdefault('tracking_gaps', {})
                if requirement_id in returned_ids:
                    gaps.pop(requirement_id, None)
                else:
                    gaps[requirement_id] = {'checked_at': now, 'scan_id': scan_id,
                                            'reason': 'not_returned_under_current_permissions_and_assignee_filter'}
        write_json(_directory(root) / 'scans' / (scan_id + '.json'),
                   {'completed_at': now, 'scan_mode': mode, 'query': query,
                    'summary_pages': spec['summary_pages'], 'page_hashes': hashes, 'rows': len(rows),
                    'new_codes': fresh, 'changed_codes': changed,
                    'first_baseline': first and mode == 'full', 'authority': config['polling']['authority']})
        write_json(path, state)
    return status(root)


def _ordered(items):
    ranks = {'P0': 0, 'P1': 1, 'P2': 2}
    return sorted(items, key=lambda x: (ranks.get(x.get('priority'), 3), x.get('code') or ''))


def _explicit_authority(spec, row):
    """Host-recorded human selection releases only this exact historical row."""
    authority = spec.get('authority')
    if authority is None:
        return None
    require(isinstance(authority, dict) and authority.get('authority') == 'user'
            and authority.get('authorization_ref') and authority.get('source_quote')
            and authority.get('user_request') and authority.get('source_thread_id'),
            'Explicit intake needs the actual human request and its source')
    require(authority.get('scope_requirement') == row['code']
            and authority.get('requirement_id') == row['id'],
            'Explicit authority must select this exact requirement code and UUID')
    return authority


def assess(code, spec, root=ROOT):
    """Record real Agent judgment on a fresh brief; no keyword-based auto-accept."""
    fireplay._code(code)
    config = policy(root)
    spec = fireplay.payload(spec)
    snap = fireplay.snapshot(code, spec['snapshot'])
    decision, row = spec['decision'], snap['row']
    explicit = _explicit_authority(spec, row)
    conditional = _conditional_intake(row, config)
    waiting_assignment = False
    if conditional and not explicit:
        conditional_authority = _explicit_authority({'authority': conditional['authority']}, row)
        waiting_assignment = conditional['assignee_id'] not in (row.get('assigneeIds') or [])
        if not waiting_assignment:
            explicit = conditional_authority
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
                (entry['state'] == 'needs_revision_review' and decision.get('reviewed_content_version')) or
                (conditional and entry['state'] in ('baseline', 'ignored', 'historical_translation_pending',
                                                    'newly_visible_old', 'not_eligible', 'waiting_for_assignment')) or
                (explicit and entry['state'] in ('baseline', 'ignored', 'historical_translation_pending',
                                                 'newly_visible_old', 'not_eligible')) or
                (spec.get('recheck') is True and entry['state'] in ('baseline', 'ignored', 'historical_translation_pending')),
                'Historical/newly-visible backlog is not automatically authorized')
        old_record = Path(root) / 'state/fireplay' / code / 'request.json'
        if old_record.exists():
            old = read_json(old_record)
            if old['content_version'] != snap['content_version']:
                if decision.get('reviewed_content_version') and decision['is_translation']:
                    interpretation = {**old.get('decision', {}),
                                      'reviewed_content_version': decision['reviewed_content_version'],
                                      'revision_reason': decision['reason']}
                    if decision.get('targets'):
                        interpretation['targets'] = decision['targets']
                    if 'source_targets' in decision:
                        interpretation['source_targets'] = decision['source_targets']
                    fireplay.register(code, spec['snapshot'], interpretation, root)
                    old = read_json(old_record)
                else:
                    entry.update(state='needs_revision_review', reason='Existing requirement changed; preserve its chat, budget and work',
                                 proposed_content_version=snap['content_version'], review_pending=False)
                    write_json(path, state)
                    return {'code': code, 'state': entry['state'], 'chat': old.get('chat'), 'budget': old.get('budget')}
        uncertain_historical = False
        if not explicit and not old_record.exists() and (entry.get('reason') == 'updated_content_or_metadata' or spec.get('recheck') is True):
            old_brief = entry.get('assessed_brief_version')
            summary_changed = entry.get('previous_summary_version', entry.get('summary_version')) != _summary_version(row)
            # Without an old brief, unchanged summary cannot prove new content.
            if not summary_changed and (not old_brief or old_brief == snap['content_version']):
                uncertain_historical = decision['is_translation']
        saved = {'code': code, 'requirement_id': row['id'], 'snapshot': spec['snapshot'], 'decision': decision,
                 'assessed_at': utc_now(), 'authority': explicit or config['authority'],
                 'polling_scope_authority': config['polling']['authority']}
        write_json(_directory(root) / 'assessments' / (object_hash(saved) + '.json'), saved)
        entry.update(assessed_brief_version=snap['content_version'], decision=decision, row=row,
                     summary_version=_summary_version(row), review_pending=False)
        if conditional:
            entry['conditional_policy_version'] = object_hash(conditional)
        if not decision['is_translation']:
            entry.update(state='ignored', reason=decision['reason'])
        elif row.get('status') not in config['eligible_statuses'] or row.get('canBindMaterials') is not True:
            entry.update(state='not_eligible', reason='Not in an eligible status or lacks execution permission')
        elif waiting_assignment and not old_record.exists():
            entry.update(state='waiting_for_assignment',
                         reason='User authorized this exact requirement only after the specified assignee is assigned')
        elif uncertain_historical:
            entry.setdefault('historical_pending_since', utc_now())
            entry.update(state='historical_translation_pending',
                         reason='Translation intent confirmed; resolve existing chat/delivery evidence or ask the owner once. Historical timing alone does not authorize production.')
        else:
            authority = explicit or {**config['authority'], 'scope_update_quote': config['scope_update_quote'],
                         'polling_scope_authority': config['polling']['authority'],
                         'authorization_ref': config['authority']['authorization_ref'] + ':' + row['id'],
                         'standing_authorization_ref': config['authority']['authorization_ref'], 'mode': 'first',
                         'user_request': config['authority']['source_quote'] + '\n自动发现并独立制作：' + code,
                         'scope_requirement': code, 'requirement_id': row['id']}
            interpretation = {'authorization_ref': authority['authorization_ref'], 'source_quote': authority['source_quote'],
                              'quantity_mode': config['quantity_mode']}
            if decision.get('targets'):
                interpretation['targets'] = decision['targets']
            if 'source_targets' in decision:
                interpretation['source_targets'] = decision['source_targets']
            if old_record.exists():
                interpretation = old.get('decision', {})
                if not old.get('targets') and decision.get('targets'):
                    # Agent-resolved missing languages are still preproduction.
                    # register enforces that no chat, budget or return exists.
                    interpretation = {**interpretation, 'targets': decision['targets']}
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
    from .fireplay_submission import coverage, bound_materials, completion_gate
    config = policy(root)
    from .delivery_layout import catalog
    index_path = catalog(Path(root))
    if not index_path.exists():
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
            # User 2026-10-27: stop after Fireplay acceptance; downstream
            # YouTube queues and retries belong to Fireplay, not this monitor.
            progress = coverage(record, video, root)
            if progress['complete']:
                continue
            box = path.parent / f'return-{video["index"]}.json'
            pending_locales = None
            matching, ready, review, blocked = [], [], [], []
            if box.exists():
                outbox = read_json(box)
                if outbox.get('state') == 'returned':
                    pending_locales = progress['missing_locales']
            if box.exists() and pending_locales is None:
                operations = outbox.get('operations', {})
                operations = operations.values() if isinstance(operations, dict) else operations
                action = 'reconcile_return' if any(op.get('state') == 'unknown' for op in operations) else 'resume_return'
                identity = object_hash(outbox)
            else:
                matching = [p for p in packages if p.get('origin_run_id') in video.get('members', [])
                            and p.get('source_sha256') == video.get('source', {}).get('sha256')
                            and p.get('target_language') in progress['missing_locales']
                            and p.get('status') in ('delivered', 'delivered_with_issues')]
                latest = {}
                for package in sorted(matching, key=lambda p: p.get('archived_at') or ''):
                    latest[package.get('target_language')] = package
                matching = list(latest.values())
                if not matching:
                    action = 'complete_delivery'
                    identity = object_hash({'coverage': progress, 'ready_packages': matching})
                else:
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
                    ready, review, blocked = [], [], []
                    for package in matching:
                        locale = package['target_language']
                        if package.get('status') == 'delivered_with_issues':
                            digest = package.get('video_sha256') or ''
                            review_file = path.parent / 'publication-reviews' / (digest + '.json')
                            if not review_file.exists():
                                review.append(locale)
                            else:
                                from .fireplay_publication import publication_decision, ACCEPTABLE
                                if publication_decision(record['code'], digest, root) in ACCEPTABLE:
                                    ready.append(locale)
                                else:
                                    blocked.append(locale)
                        else:
                            ready.append(locale)
                    if ready:
                        action = 'auto_return'
                    elif review:
                        action = 'review_publication'
                    elif blocked:
                        action = 'resolve_delivery_blockers'
            task = {'code': record['code'], 'video_index': video['index'], 'threadId': chat['threadId'],
                    'hostId': chat.get('hostId', 'local'), 'action': action, 'artifact_identity': identity,
                    'missing_locales': progress['missing_locales']}
            task['key'] = object_hash(task)
            # One ready locale is actionable even when another still needs production.
            if action not in ('reconcile_return', 'resume_return'):
                task['available_locales'] = sorted(p['target_language'] for p in matching)
                task['production_locales'] = sorted(set(progress['missing_locales']) - set(task['available_locales']))
                if matching:
                    task.update(ready_locales=sorted(ready), review_locales=sorted(review), blocked_locales=sorted(blocked))
            note = _directory(root) / 'signals' / (task['key'] + '.json')
            from .fireplay_followup import state as signal_state
            task['signal_state'] = signal_state(read_json(note) if note.exists() else None, config)
            result.append(task)
        # Batch receipts do not replace the final full platform read-back.
        if record['videos'] and all(coverage(record, v, root)['complete'] for v in record['videos']):
            chat = record.get('chat') or record['videos'][0].get('chat', {})
            if chat.get('state') == 'ready' and not completion_gate(record, root)['can_close']:
                task = {'code': record['code'], 'video_index': record['videos'][0]['index'],
                        'threadId': chat['threadId'], 'hostId': chat.get('hostId', 'local'),
                        'action': 'verify_completion', 'artifact_identity': object_hash([
                            bound_materials(record, v, root) for v in record['videos']]), 'missing_locales': []}
                task['key'] = object_hash(task)
                note = _directory(root) / 'signals' / (task['key'] + '.json')
                from .fireplay_followup import state as signal_state
                task['signal_state'] = signal_state(read_json(note) if note.exists() else None, config)
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
                require(old.get('attempt', 1) == 1 or spec.get('attempt') == old['attempt'],
                        'Record the matching delivery follow-up attempt with the send receipt')
                if old['state'] == 'sent':
                    require(old.get('receipt') == spec['response'], 'A sent follow-up already has its immutable send receipt')
                    return old
                response = fireplay.payload(spec['response'])
                require(response.get('threadId') == task['threadId'], 'Follow-up receipt belongs to another chat')
                old.update(state='sent', receipt=spec['response'], receipt_at=utc_now())
                write_json(path, old)
                return old
            if not spec.get('owner_observation'):
                return old
            from .fireplay_followup import observe, state as signal_state
            observation = observe(spec, task, root)
            current = signal_state(old, policy(root))
            if observation['status'] == 'running':
                old.update(owner_observation=observation, owner_checked_at=utc_now())
                write_json(path, old)
                return old
            require(old['state'] == 'sent', 'Reconcile an unknown send before redispatching')
            if current != 'owner_check_required' or observation['status'] not in {'idle', 'error'}:
                old['owner_observation'] = observation
                write_json(path, old)
                return {**old, 'next_action': 'Resolve the concrete owner blocker; delivery remains incomplete'}
            # The old send stays immutable in history. A lease permits a recovery
            # prompt only; it never retries a paid job or platform write itself.
            history = _directory(root) / 'signals/history' / task['key'] / f'{old.get("attempt", 1)}.json'
            if not history.exists():
                write_json(history, old)
        require(not spec.get('response'), 'Journal follow-up dispatch before recording the receipt')
        from .kie_access import instruction as kie_access_instruction
        from .fireplay_youtube import instruction as youtube_instruction
        from .fireplay_materials import attribution_instruction
        message = (f'按已授权项目流程继续需求{task["code"]}第{task["video_index"]}个原片的回传。'
                   f'当前待办：{task["action"]}，缺少语种：{task["missing_locales"]}。复用既有run、素材ID、outbox和真实回执；未知写入先核查，不重复上传。'
                   '用户已允许有限预算/返工内做到最好的完整成品带普通不合格提交；按fireplay-publication-review记录实际影响和best_available证据，内部revise不等于禁止提交。大面积撕裂、无法观看、严重主体损坏、漏译或缺必需配音仍阻断对应版本。'
                   f'先交本次可提交语种{task.get("ready_locales", [])}，同时继续其余缺项，不等待全部制作完成。'
                   '真实文件上传超时先恢复已有ID；无可用结果时按fireplay-retry-upload的既有额外两次授权重传，不能把此权限用于重发未知付费模型。'
                   '设计师从当前执行人和Fireplay真实成员目录自行核对，可使用已核验用户ID归属；不要求用户提供DID。KIE已有持续授权，在本需求原账本和模型范围内直接使用，不再次弹项目同意问题。'
                   + kie_access_instruction(root) +
                   attribution_instruction() +
                   youtube_instruction(root) +
                   fireplay.submission_consent_instruction(root) +
                   '逐项核对本需求全部原片与全部目标语种；只有全部入库、共享、标签和绑定核验后才可结案。partial和unknown继续恢复，不以部分成功收尾；不跟踪YouTube进度，不因排队/限额重入库。'
                   + fireplay.submission_instruction(root))
        value = {'state': 'unknown', 'task': task, 'dispatched_at': utc_now(),
                 'attempt': old.get('attempt', 1) + 1 if old else 1,
                 **({'previous_dispatch': str(history.relative_to(root)), 'owner_observation': observation} if old else {}),
                 'host_action': {'tool': 'send_message_to_thread', 'arguments': {
                     'threadId': task['threadId'], 'hostId': task['hostId'], 'prompt': message}}}
        write_json(path, value)
        return value


def completion_watch_status(followup_items, root=ROOT):
    """Plan host scheduling; never create automations or infer delivery from chat status."""
    from .fireplay_submission import completion_gate
    root = Path(root)
    monitor_policy = policy(root)
    config = monitor_policy.get('completion_watch', {})
    if not config.get('enabled'):
        return {'enabled': False}
    manifest_path = root / config['manifest']
    manifest = read_json(manifest_path) if manifest_path.exists() else {}
    active = manifest.get('status') == 'ACTIVE'
    members = {m['code']: m for m in manifest.get('requirements', [])} if active else {}
    watched_codes = set(members)
    enrollment_start = manifest.get('enrollment_started_at') or manifest.get('created_at')
    # Human-created requests can acquire an owner between discovery scans. A
    # complete upload without a current close receipt still needs supervision.
    for path in (root / 'state/fireplay').glob('*/request.json'):
        record = read_json(path)
        chat = record.get('chat', {})
        if chat.get('state') == 'ready' and _matches(record['snapshot']['row'], monitor_policy):
            # A new rolling watch is not permission to reopen already accepted
            # historical batches solely for missing legacy close paperwork.
            if (path.parent.name not in watched_codes and enrollment_start
                    and _time(record['created_at']) < _time(enrollment_start)
                    and completion_gate(record, root)['can_close']):
                continue
            members.setdefault(path.parent.name, {'code': path.parent.name,
                               'requirement_id': record['requirement_id'],
                               'threadId': chat['threadId'], 'hostId': chat.get('hostId', 'local')})
    for item in followup_items:
        code = item['code']
        record = read_json(root / 'state/fireplay' / code / 'request.json')
        members.setdefault(code, {'code': code, 'requirement_id': record['requirement_id'],
                                 'threadId': item['threadId'], 'hostId': item.get('hostId', 'local')})
    pending, complete = [], []
    for code, member in sorted(members.items()):
        try:
            folder = root / 'state/fireplay' / fireplay._code(code)
            record = read_json(folder / 'request.json')
            require(record['requirement_id'] == member['requirement_id'], 'Watched UUID changed')
            require(record.get('chat', {}).get('threadId') == member['threadId'], 'Watched owner changed')
            gate = completion_gate(record, root)
            require(gate['can_close'], 'All-source/all-locale platform verification is incomplete')
            pointer = read_json(folder / 'delivery-closure.json')
            receipt = inside(root, pointer['receipt'])
            require(file_hash(receipt) == pointer['sha256'], 'Closure receipt hash changed')
            closed = read_json(receipt)
            require(closed.get('complete') is True and closed.get('requirement_id') == record['requirement_id']
                    and closed.get('content_version') == record['content_version']
                    and closed.get('completion_check_sha256') == file_hash(folder / 'completion-check.json'),
                    'Closure is missing or no longer matches the current completion check')
            complete.append({**member, 'closure': str(receipt.relative_to(root)), 'sha256': pointer['sha256']})
        except (WorkflowError, OSError, ValueError, KeyError, TypeError) as exc:
            pending.append({**member, 'reason': str(exc)})
    # Already closed history must not be copied into a new watch generation.
    complete = [member for member in complete if member['code'] in watched_codes]
    requirements = {member['code']: members[member['code']] for member in complete + pending}
    action = 'ensure_active' if pending else 'delete_completion_watch' if active and watched_codes else 'none'
    restricted = manifest.get('followup_approval_required') is True
    if restricted and pending:
        action = 'observe_only' if active else 'request_followup_approval'
    return {'enabled': True, 'interval_minutes': config['interval_minutes'], 'manifest': config['manifest'],
            'automation_id': manifest.get('automation_id') if active else None, 'host_action': action,
            'requirements': list(requirements.values()), 'pending': pending, 'verified_complete': complete,
            'scheduler_action': ('update' if active else 'create') if pending else
                                'delete' if action == 'delete_completion_watch' else 'none',
            'restart_when_new_owner': config.get('restart_when_new_owner', True),
            'scope_mode': config.get('scope', 'ongoing_newly_intaken_requirements_one_shared_watch'),
            'followup_approval_required': restricted, 'effective_mode': manifest.get('mode', 'owner_followup'),
            'discovery_automation_action': 'keep_active', 'automatic_approval': False}


def status(root=ROOT):
    config, state = policy(root), _state(root)
    review, queue, revisions, historical, waiting = [], [], [], [], []
    for entry in state['requirements'].values():
        row = entry['row']
        if not _matches(row, config):
            continue
        packet = {key: row.get(key) for key in ('id', 'code', 'priority', 'title', 'deptName', 'createdAt', 'updatedAt')}
        packet.update(state=entry['state'], reason=entry.get('reason'))
        if entry['state'] == 'needs_review' or entry.get('review_pending'):
            packet['host_action'] = {'tool': 'requirement_list', 'arguments': {
                'scope': 'all', 'view': 'blind_brief', 'asset_type': 'video',
                **({'assignee_ids': config['query']['assignee_ids']} if config['assignee_mode'] == 'strict' else {}),
                'requirement_ids': [row['id']]}}
            review.append(packet)
        if entry['state'] == 'needs_revision_review':
            revisions.append(packet)
        if entry['state'] == 'waiting_for_assignment':
            rule = _conditional_intake(row, config)
            if rule:
                packet.update(assignee_id=rule['assignee_id'],
                              next_action='Keep scanning actual assigneeIds; when assigned, refresh brief/summary and assess under the stored conditional human authority. Do not ask again or create a request before then.')
                waiting.append(packet)
        if entry['state'] == 'historical_translation_pending':
            packet.update(pending_since=entry.get('historical_pending_since', entry['first_seen_at']),
                          resolution_key=object_hash({'kind': 'historical_translation_review', 'id': row['id'],
                                                      'content_version': entry.get('assessed_brief_version')}),
                          next_action='Check existing exact-code chat/request/ledger and requirement bindings; reuse proven work. If scope is still unresolved, ask the owner once for this resolution_key. Record the actual reply as assess.authority; do not silently leave pending or auto-remake history.')
            historical.append(packet)
        if entry['state'] in ('admitted', 'registered'):
            p = Path(root) / 'state/fireplay' / row['code'] / 'request.json'
            if p.exists() and not read_json(p).get('blockers') and read_json(p).get('chat', {}).get('state') != 'ready':
                queue.append(packet)
    followup_items = followups(root)
    watch = completion_watch_status(followup_items, root)
    return {'state': 'ready' if state.get('baseline_at') else 'needs_baseline', 'interval_minutes': config['interval_minutes'],
            'scope': config['group_policy'], 'baseline_at': state.get('baseline_at'), 'last_success_at': state.get('last_success_at'),
            'visible_count': state.get('visible_count', 0), 'needs_review': _ordered(review), 'ready_to_dispatch': _ordered(queue),
            'revision_reviews': _ordered(revisions),
            'historical_translation_candidates': _ordered(historical),
            'historical_review_required': _ordered(historical),
            'waiting_for_assignment': _ordered(waiting),
            'publication_followups': followup_items, 'max_active_requirements': config['max_active_requirements'],
            'completion_watch': watch, 'polling': _polling_plan(config, state, watch, root),
            'priority_policy': read_json(Path(root) / 'config/fireplay-intake.json').get('priority_policy', {}),
            'p1_waits_for_p0': False, 'automatic_paid_execution_by_script': False}
