"""Prepare scoped Fireplay status writes and confirm them with platform reads."""
from datetime import datetime, timezone
from pathlib import Path

from . import fireplay
from .common import ROOT, lock, read_json, require, utc_now, write_json


def policy(root=ROOT):
    path = Path(root) / 'config/fireplay-intake.json'
    settings = read_json(path).get('status_update') if path.exists() else None
    if not isinstance(settings, dict):
        return {}
    require(settings.get('authority') == 'user' and settings.get('authorization_ref')
            and all(settings.get(key) for key in ('ai_mode', 'intake_status', 'production_status', 'completed_status')),
            'Fireplay status updates require a scoped user policy')
    return settings


def _path(record, action, root):
    return fireplay._folder(record['code'], root) / f'status-{action}.json'


def confirmed(record, action, root=ROOT):
    path = _path(record, action, root)
    if not path.exists():
        return False
    value = read_json(path)
    return (value['requirement_id'] == record['requirement_id']
            and value['content_version'] == record['content_version'] and value['state'] == 'confirmed')


def _status_snapshot(code, action, spec):
    value = fireplay.payload(spec)
    if action != 'finish' or 'summary' in value or 'brief' in value:
        return fireplay.snapshot(code, value), False
    delivery = fireplay.payload(value.get('verification', value))
    row = fireplay._rows(delivery, code)
    fields = {*fireplay.REQUIREMENT_CONTENT_FIELDS, 'updatedAt', 'status', 'aiMode', 'canUpdateStatus',
              'canBindMaterials', 'materials'}
    require(delivery.get('view') == 'delivery' and fields <= row.keys()
            and isinstance(row['materials'], list),
            'Delivery read is incomplete for status; supply fresh summary and blind_brief (plus delivery for attachment sources)')
    return fireplay.snapshot(code, {'summary': delivery, 'brief': delivery, 'delivery': delivery}), True


def transition(code, action, spec, execute=False, root=ROOT, *, retry=False):
    settings = policy(root)
    require(settings and action in ('start', 'finish'), 'Unknown or disabled Fireplay status transition')
    snap, from_delivery = _status_snapshot(code, action, spec)
    fireplay._fresh({'snapshot': snap})
    folder = fireplay._folder(code, root)
    with lock(folder / 'request.lock'):
        record = fireplay._record(code, root)
        row = snap['row']
        require(record.get('status_managed'), 'This requirement needs an individual status decision')
        require(row['id'] == record['requirement_id'] and snap['content_version'] == record['content_version']
                and row.get('aiMode') == settings['ai_mode'], 'Review the current requirement or changed AI mode before proceeding')
        path = _path(record, action, root)
        previous = read_json(path) if path.exists() else {}
        if action == 'start':
            require(not record.get('blockers') and
                    (record.get('chat') or any(video.get('chat') for video in record['videos'])),
                    'Reserve a video slot before starting the requirement')
            if (folder / 'monitor-authority.json').exists():
                from .fireplay_monitor import _matches, policy as monitor_policy
                require(_matches(row, monitor_policy(root)), 'Requirement is outside the current intake scope')
            expected, target = settings['intake_status'], settings['production_status']
        else:
            from .fireplay_submission import completion_gate
            require(completion_gate(record, root)['can_close'], 'Verify every video and locale binding before marking done')
            check = read_json(folder / 'completion-check.json')
            if from_delivery:
                actual = {material['id'] for material in row['materials']}
                require(row.get('materialSelection', {}).get('status') != 'waiting_selection'
                        and {item['material_id'] for item in check['verified']} <= actual,
                        'Delivery read no longer contains every verified binding')
            expected, target = settings['production_status'], settings['completed_status']
        current = row.get('status')
        packet = {'code': code, 'requirement_id': row['id'], 'content_version': snap['content_version'],
                  'status': current, 'target_status': target, 'platform_read_at': snap['server_time']}
        if current == target:
            if action == 'start':
                require(previous.get('requirement_id') == row['id'],
                        'The requirement was started elsewhere. Reconcile ownership before making videos')
            if from_delivery and previous.get('dispatched_at'):
                observed = datetime.fromisoformat(snap['server_time'].replace('Z', '+00:00'))
                require(observed >= datetime.fromisoformat(previous['dispatched_at']),
                        'Read the current Fireplay status after the dispatched write')
            result = {**previous, **packet, 'state': 'confirmed', 'observed_updated_at': row['updatedAt']}
            write_json(path, result)
            if action == 'start':
                record['snapshot'] = snap
                write_json(folder / 'request.json', record)
            return result
        if current != expected:
            return {**packet, 'state': 'manual_review', 'next': 'Review the current platform status individually'}
        if action == 'finish':
            require(check.get('platform_updated_at') == row['updatedAt'],
                    'Refresh the full delivery check after the platform row changes')
            observed = datetime.fromisoformat(check['platform_read_at'].replace('Z', '+00:00'))
            require(-60 <= (datetime.now(timezone.utc) - observed).total_seconds() <= 600,
                    'Refresh the full platform delivery check before changing status')
        if row.get('canUpdateStatus') is not True:
            return {**packet, 'state': 'needs_status_permission'}
        if previous and not retry:
            return {**packet, 'state': 'reconcile_status', 'next': 'Check the original write and current platform row'}
        if retry:
            require(execute and previous.get('state') == 'unknown'
                    and previous.get('attempt', 1) < 2
                    and snap['server_time'] > previous['platform_read_at'],
                    'Retry needs a newer platform read and an unresolved first attempt')
        host_action = {'tool': 'requirement_update_status', 'arguments': {
            'items': [{'requirement_id': row['id'], 'status': target, 'base_updated_at': row['updatedAt']}]}}
        if not execute:
            return {**packet, 'state': 'prepared', 'next': 'Run with --execute before calling Fireplay'}
        history = list(previous.get('history', []))
        if previous:
            history.append({key: value for key, value in previous.items() if key != 'history'})
        result = {**packet, 'state': 'unknown', 'attempt': previous.get('attempt', 0) + 1,
                  'base_updated_at': row['updatedAt'], 'dispatched_at': utc_now(),
                  'history': history}
        write_json(path, result)
        return {**result, 'host_action': host_action}
