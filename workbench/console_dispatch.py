"""Host-agent bridge: signed user UI commands -> native tools -> durable receipt.

This script NEVER calls model APIs, sends messages, or edits native automation
files. prepare emits exact native tool arguments for the authorized host agent.
Unacknowledged dispatches stay unknown and must be reconciled, never resent.
"""
from __future__ import annotations
import argparse
import hashlib
import hmac
import json
import re
import sys
import time
from pathlib import Path

from console_data import ConsoleData, fingerprint, now
from store import clean


def owner(data, kind):
    options = data.automations()['automations']
    selected = next((a for a in options if a['id'] == ('fireplay' if kind == 'intake' else 'automation')), None)
    if not selected or not selected.get('target_thread_id'):
        raise ValueError('找不到原负责会话，保留待核验，不猜测新建')
    data.thread(selected['target_thread_id'])
    return selected['target_thread_id']


def tool_spec(data, row, payload):
    cid = row['id']
    tag = f'[译制台指令 {cid}]'
    action = row['action']
    if action == 'message':
        data.thread(row['thread_id'])
        text = payload['text']
        ref = payload.get('artifact')
        if ref:
            actual = data.artifact(row['thread_id'], ref['run_id'], ref['id'])
            if actual['sha256'] != ref['sha256']: raise ValueError('所选产物已变化，请用户重新核对版本')
            text += '\n反馈绑定产物：'+json.dumps({k: actual[k] for k in ('run_id', 'path', 'sha256')}, ensure_ascii=False)
        return {'tool': 'send_message_to_thread', 'args': {'hostId': 'local', 'threadId': row['thread_id'], 'prompt': tag+'\n'+text}, 'target': row['thread_id']}
    if action == 'intake':
        tid = owner(data, 'intake')
        prompt = (f'{tag}\n用户在本项目译制台手动交办精确需求号 {payload["code"]}，要求现在接单并开始视频翻译。'
                  '按现有Fireplay接入合同读取精确正文、原片、语种和权限；先核查编号/UUID、原request、聊天、账本与绑定，已有工作沿原会话恢复。'
                  '这是用户手工点名，不是自动发现；歧义、新增额度和宿主审批仍按现有授权边界处理。'
                  '确需新建时按项目规范创建编号会话，不更改需求状态或投放，不重复制作。'
                  f'\n补充要求：{payload.get("note", "无")}\n请在正常项目状态文件保存真实绑定与执行结果。')
        return {'tool': 'send_message_to_thread', 'args': {'hostId': 'local', 'threadId': tid, 'prompt': prompt}, 'target': tid}
    if action == 'summarize':
        tid = owner(data, 'knowledge')
        return {'tool': 'send_message_to_thread', 'args': {'hostId': 'local', 'threadId': tid,
            'prompt': tag+'\n用户在项目译制台点击“总结经验”。请按既有knowledge-sweep与knowledge-curation技能，总结当前项目新增观察、反馈和反例，保留来源、scope、待补证与未采纳理由。沿用原检查点和本轮限额，不调用付费媒体模型、不清理媒体、不自动commit/push。'}, 'target': tid}
    if action == 'automation':
        a = next(a for a in data.automations()['automations'] if a['id'] == payload['automation_id'])
        if payload['operation'] == 'run':
            tid = a['target_thread_id']
            # Native scheduler remains sole owner. A manual turn uses the saved prompt once.
            import tomllib
            saved = tomllib.loads((data.home/'automations'/a['id']/'automation.toml').read_text())
            prompt = tag+'\n用户手动要求执行本已保存自动任务一轮，不修改计划、不新增调度、不重复处理同一窗口。任务名：'+a['name']+'\n'+saved.get('prompt', '')
            return {'tool': 'send_message_to_thread', 'args': {'hostId': 'local', 'threadId': tid, 'prompt': prompt}, 'target': tid}
        return {'tool': 'automation_update', 'args': {'id': a['id'], 'mode': 'update',
                'status': 'PAUSED' if payload['operation'] == 'pause' else 'ACTIVE'},
                'target': a['target_thread_id'], 'preflight': {'tool': 'automation_update', 'args': {'id': a['id'], 'mode': 'view'}},
                'instruction': '先view读取并保留全部既有字段；按原kind用返回的完整字段执行update，仅改变status。不直接改automation.toml。'}
    raise ValueError('未知动作')


def prepare(data):
    data.folder.mkdir(parents=True, exist_ok=True)
    result = []
    with data.lock, data._db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        # Previous dispatch lacked a receipt. Losing the host turn must not resend it.
        conn.execute("UPDATE commands SET status='unknown',updated_at=? WHERE status='dispatching'", (now(),))
        for row in conn.execute("SELECT * FROM commands WHERE status='queued' ORDER BY created_at LIMIT 4").fetchall():
            p = json.loads(row['payload']);signature = p.pop('_ui_signature', '')
            expected = hmac.new(data._secret(), (row['id']+row['digest']).encode(), hashlib.sha256).hexdigest()
            if fingerprint(p) != row['digest'] or not hmac.compare_digest(signature, expected):
                conn.execute("UPDATE commands SET status='rejected',receipt=?,updated_at=? WHERE id=?",
                             (json.dumps({'reason': 'UI签名或内容指纹不匹配'}), now(), row['id']))
                continue
            try: spec = tool_spec(data, row, p)
            except (ValueError, OSError, KeyError, StopIteration) as exc:
                conn.execute("UPDATE commands SET status='rejected',receipt=?,updated_at=? WHERE id=?",
                             (json.dumps({'reason': str(exc)}, ensure_ascii=False), now(), row['id']))
                continue
            conn.execute("UPDATE commands SET status='dispatching',thread_id=?,updated_at=? WHERE id=?", (spec['target'], now(), row['id']))
            result.append({'command_id': row['id'], 'user_ui_authorized': True, **spec})
        unknown = [dict(r) for r in conn.execute("SELECT id,thread_id,action FROM commands WHERE status='unknown' ORDER BY created_at LIMIT 8")]
    return {'commands': result, 'unknown_do_not_resend': unknown, 'note': '仅处理真实UI签名命令。保持宿主审批，不绕过，不自动重发unknown。'}


def acknowledge(data, command_id, receipt, status):
    if status not in {'accepted', 'failed', 'unknown'}: raise ValueError('非法回执状态')
    with data._db() as conn:
        row = conn.execute('SELECT * FROM commands WHERE id=?', (command_id,)).fetchone()
        if not row or row['status'] not in {'dispatching', 'unknown'}: raise ValueError('指令不在可登记状态')
        conn.execute('UPDATE commands SET status=?,receipt=?,updated_at=? WHERE id=?',
                     (status, json.dumps(clean(receipt), ensure_ascii=False), now(), command_id))
    return {'command_id': command_id, 'status': status}


def snapshot(data, payload):
    safe = {'observed_at': now(), 'threads': {}}
    for identifier, observation in payload.get('threads', {}).items():
        try: data.thread(identifier)
        except ValueError: continue
        safe['threads'][identifier] = {'status': observation.get('status', {}), 'observed_at': now(), 'observed_epoch': time.time(),
                                       'messages': clean(observation.get('messages', []))[-30:]}
    path = data.folder/'host-snapshot.json'
    previous = data.store.read('state/console/host-snapshot.json')
    previous.setdefault('threads', {}).update(safe['threads'])
    previous['observed_at'] = safe['observed_at']
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(previous, ensure_ascii=False));temporary.replace(path)
    return {'updated_threads': len(safe['threads'])}


def heartbeat(data, automation_id):
    path = data.folder/'dispatcher.json';path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'enabled': True, 'automation_id': automation_id, 'observed_epoch': time.time(), 'observed_at': now()}))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['prepare', 'ack', 'snapshot', 'heartbeat', 'status'])
    p.add_argument('--workspace', type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument('--file', type=Path)
    p.add_argument('--id');p.add_argument('--status', default='accepted')
    args = p.parse_args();data = ConsoleData(args.workspace)
    if args.action == 'prepare': result = prepare(data)
    elif args.action == 'ack': result = acknowledge(data, args.id, json.loads(args.file.read_text()), args.status)
    elif args.action == 'snapshot': result = snapshot(data, json.loads(args.file.read_text()))
    elif args.action == 'heartbeat': heartbeat(data, args.id);result = data.dispatch_status()
    else: result = {'bridge': data.dispatch_status(), 'commands': data.commands()}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
