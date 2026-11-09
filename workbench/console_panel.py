"""UI-only MCP adapters and single-command host handoff. No desktop writes here."""
import hashlib
import hmac
import json
import re
import shlex
import sys
from urllib.parse import urlsplit, parse_qs

from console_data import fingerprint


def read_api(data, path):
    url = urlsplit(path)
    if url.scheme or url.netloc: raise ValueError('只允许本项目接口')
    query = parse_qs(url.query)
    arg = lambda key: query.get(key, [''])[0]
    if url.path == '/api/console/config':
        return {'page_size': 8, 'bridge': data.dispatch_status(), 'commands': data.commands()}
    if url.path == '/api/console/sessions':
        return data.overview(arg('q'), arg('state') or 'all', int(arg('page') or 1), arg('archived') == 'true')
    if url.path == '/api/console/requirements': return data.requirement_board()
    if url.path == '/api/console/detail': return data.detail(arg('id'), arg('run') or None)
    if url.path == '/api/console/artifact': return data.artifact(arg('thread'), arg('run'), arg('id'))
    if url.path == '/api/console/knowledge': return data.knowledge_detail(arg('thread'), arg('run'), arg('id'))
    if url.path == '/api/console/automations': return data.automations()
    if url.path == '/api/knowledge': return data.store.knowledge()
    if url.path == '/api/document': return data.store.document(arg('path'))
    raise ValueError('此接口不开放给插件面板')


def handoff(data, command_id, reserve=False):
    if not re.fullmatch(r'[A-Za-z0-9_-]{12,100}', str(command_id)): raise ValueError('指令ID不合法')
    with data.lock, data._db() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM commands WHERE id=?', (command_id,)).fetchone()
        if not row: raise ValueError('找不到原指令')
        payload = json.loads(row['payload'])
        signature = payload.pop('_ui_signature', '')
        expected = hmac.new(data._secret(), (row['id']+row['digest']).encode(), hashlib.sha256).hexdigest()
        if fingerprint(payload) != row['digest'] or not hmac.compare_digest(signature, expected):
            raise ValueError('UI签名不匹配，拒绝交办')
        allowed = row['status'] == 'queued' and not row['notification_state']
        if reserve and allowed:
            db.execute("UPDATE commands SET notification_state='attempted' WHERE id=?", (command_id,))
    root = str(data.root)
    python = sys.executable
    prompt = (f'[译制台交办 {command_id}]\n用户在本机译制台明确点击了这一次交办。'
              f'工作区：{root}。这不是定时任务，不新建或恢复独立 CLI daemon。\n'
              '先读 workbench/console-bridge.md，再只准备这一个指令：\n'
              f'{shlex.quote(python)} {shlex.quote(root+"/workbench/console_dispatch.py")} prepare --id {command_id}\n'
              '只处理返回的同一 command_id 且 user_ui_authorized=true 的精确 tool/args，使用本聊天官方原生工具；'
              '保留目标会话、原输入与产物哈希。自动任务修改先view并保留完整字段，仅改显式status。'
              '每次实际派发后立即保存原始回执到 work/state/session-console-live/receipts/，'
              '用 console_dispatch.py ack --id 原ID --file 原始回执 --status accepted|failed|unknown 登记。'
              '超时或缺回执为unknown，绝不重发。unknown只用read_thread核对原目标精确的“[译制台指令 ID]”。'
              '宿主受理不代表业务完成。审批、预算、质量与已有制作会话不变；不处理其他队列项、不自行制作或调用付费媒体模型。')
    if row['action'] == 'sync':
        prompt += ('\n本次仅同步原会话桌面状态：按返回规格执行一次 wait_threads(timeoutMs=0)，'
                   '把原目标 id、真实 status.type 和观察时间写成 {"threads":{"ID":{"status":{"type":"实际值"}}}}，'
                   '再运行 console_dispatch.py snapshot --file 该JSON。若回执不含可靠状态，保留待确认，不能猜测 idle/active。'
                   '保存原始只读回执并ack；不向制作会话发消息，不重试，不持续等待。')
    return {'command_id': command_id, 'prompt': prompt, 'can_notify': allowed,
            'notification_state': 'attempted' if reserve and allowed else row['notification_state'], 'status': row['status']}


def notified(data, command_id, state):
    if state not in {'delivered', 'unknown'}: raise ValueError('通知状态不合法')
    with data.lock, data._db() as db:
        db.execute('UPDATE commands SET notification_state=? WHERE id=? AND notification_state=\'attempted\'', (state, command_id))
    return {'command_id': command_id, 'notification_state': state,
            'note': '仅宿主通知状态；实际派发受理以原生工具回执为准'}
