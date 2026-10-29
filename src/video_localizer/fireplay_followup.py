"""Bounded owner leases for delivery recovery; never dispatch external actions."""
from datetime import datetime, timezone, timedelta

from .common import file_hash, inside, require, utc_now


def settings(config):
    value = config.get('delivery_followup', {})
    minutes = value.get('lease_minutes', 120)
    retries = value.get('max_stalled_redispatches', 2)
    require(type(minutes) is int and 60 <= minutes <= 1440, 'Invalid delivery follow-up lease')
    require(type(retries) is int and 1 <= retries <= 5, 'Invalid delivery redispatch limit')
    return minutes, retries


def _time(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(parsed.tzinfo is not None, 'Owner observation needs a timezone')
    return parsed


def state(record, config):
    if not record:
        return 'prepared'
    # Unknown sends always require reconciliation, regardless of elapsed time.
    if record['state'] != 'sent':
        return record['state']
    minutes, retries = settings(config)
    anchor = record.get('owner_checked_at') or record.get('receipt_at') or record['dispatched_at']
    if datetime.now(timezone.utc) < _time(anchor) + timedelta(minutes=minutes):
        return 'sent'
    return 'escalation_required' if record.get('attempt', 1) > retries else 'owner_check_required'


def observe(spec, task, root):
    """Bind a fresh host thread observation, rather than infer idleness from age."""
    value = spec['owner_observation']
    require(value.get('threadId') == task['threadId'] and
            value.get('status') in {'idle', 'running', 'needs_attention', 'error'},
            'Read the actual responsible chat status; do not infer it from a sent message')
    age = (datetime.now(timezone.utc) - _time(value.get('observed_at', ''))).total_seconds()
    require(-60 <= age <= 600, 'Refresh the actual owner status before delivery recovery')
    require(value.get('source') in {'wait_threads', 'read_thread'} and value.get('evidence'),
            'Owner observation needs a saved host thread receipt')
    evidence = value['evidence']
    path = inside(root, evidence['path'])
    require(path.is_file() and file_hash(path) == evidence['sha256'], 'Owner observation receipt changed')
    require(task['threadId'] in path.read_text(encoding='utf-8'), 'Owner receipt belongs to another chat')
    return {**value, 'checked_at': utc_now()}
