"""Bounded owner leases for delivery recovery; never dispatch external actions."""
import json
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
    dispatched_at = record['dispatched_at']
    observation = record.get('owner_observation') or {}
    checked_at = record.get('owner_checked_at')
    if not checked_at and observation.get('checked_at'):
        if _time(observation['checked_at']) > _time(dispatched_at):
            checked_at = observation['checked_at']
    exhausted = record.get('attempt', 1) > retries
    if record.get('owner_empty_turns') and observation.get('status') in {'idle', 'error'}:
        return 'escalation_required'
    if exhausted and checked_at and observation.get('status') in {'idle', 'error'}:
        return 'escalation_required'
    anchor = checked_at or record.get('receipt_at') or dispatched_at
    if datetime.now(timezone.utc) < _time(anchor) + timedelta(minutes=minutes):
        return 'sent'
    return 'escalation_required' if exhausted else 'owner_check_required'


def empty_turns(observation, receipt, dispatched_at):
    if observation['source'] != 'read_thread' or observation['status'] != 'idle':
        return None
    try:
        details = json.loads(receipt)
    except json.JSONDecodeError:
        return None
    if not isinstance(details, dict):
        return None
    thread = details.get('thread', {})
    turns = details.get('turns')
    if (thread.get('id') != observation['threadId'] or thread.get('status', {}).get('type') != 'idle'
            or details.get('page', {}).get('order') != 'newest_first' or not isinstance(turns, list) or not turns):
        return None
    started_at = turns[0].get('startedAt')
    if type(started_at) is not int or started_at < _time(dispatched_at).timestamp():
        return None
    empty_ids = []
    for turn in turns[:2]:
        turn_id = turn.get('id')
        items = turn.get('items')
        if (not turn_id or turn_id in empty_ids or turn.get('status') != 'completed' or turn.get('error')
                or turn.get('nextItemCursor') or not isinstance(items, list)):
            return None
        if any(item.get('type') not in {'userMessage', 'agentMessage', 'reasoning'}
               and not (item.get('type') == 'functionCallOutput' and item.get('namespace') == 'codex_app'
                        and item.get('name') in {'create_thread', 'send_message_to_thread'})
               for item in items):
            break
        if not any(item.get('type') == 'agentMessage' and item.get('phase') == 'final_answer' for item in items):
            return None
        empty_ids.append(turn_id)
    return empty_ids


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
    receipt = path.read_text(encoding='utf-8')
    require(task['threadId'] in receipt, 'Owner receipt belongs to another chat')
    return {**value, 'checked_at': utc_now()}, receipt
