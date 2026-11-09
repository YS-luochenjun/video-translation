"""MCP Apps console: local reads/events and explicit user-click queueing only."""
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from workspace import workspace_root

ROOT = workspace_root(Path(__file__).resolve().parent)
sys.path.insert(0, str(ROOT/'workbench'))
from console_data import ConsoleData
from console_events import EventHub
from console_panel import read_api, handoff, notified

data = ConsoleData(ROOT)
URL = 'http://127.0.0.1:8770/console'
RESOURCE = 'ui://localization-console/panel-v3'

def invalidate():
    with data.lock: data.cache.clear()

events = EventHub(ROOT, data.home, invalidate)


def tools():
    read = {'readOnlyHint': True, 'destructiveHint': False, 'openWorldHint': False}
    write = {**read, 'readOnlyHint': False}
    def descriptor(name, description, props, required=(), annotation=read, panel=False):
        return {'name': name, 'description': description,
                'inputSchema': {'type': 'object', 'properties': props, 'required': list(required), 'additionalProperties': False},
                'annotations': annotation,
                '_meta': {'ui': {'resourceUri': RESOURCE, 'visibility': ['app', 'model']} if panel else {'visibility': ['app']},
                          **({'openai/ui': {'entrypoints': [{'type': 'global'}, {'type': 'thread'}]}} if panel else {})}}
    command_id = {'type': 'string', 'pattern': '^[A-Za-z0-9_-]{12,100}$'}
    return [descriptor('session_console_open', '打开译制台插件面板：本机事件更新；仅用户点击交办时通知宿主，不使用定时 Agent 轮询。', {}, panel=True),
            descriptor('session_console_sessions', '只读列出本项目会话，按最近用户提问排序。', {'query': {'type': 'string'}, 'page': {'type': 'integer'}, 'archived': {'type': 'boolean'}}),
            descriptor('session_console_read', '面板读取受限本项目接口，不触发制作。', {'path': {'type': 'string'}}, ['path']),
            descriptor('session_console_wait', '仅面板使用：等待本机文件变化，最多25秒，无变化不返回新内容，不调用模型。', {'revision': {'type': 'integer'}}, ['revision']),
            descriptor('session_console_command', '仅用户在面板明确点击时，校验并签名保存这一次指令。不会执行制作或调用桌面工具。',
                       {'command_id': command_id, 'action': {'type': 'string'}, 'thread_id': {'type': 'string'}, 'text': {'type': 'string'},
                        'code': {'type': 'string'}, 'note': {'type': 'string'}, 'artifact': {'type': 'object'}, 'automation_id': {'type': 'string'},
                        'operation': {'type': 'string'}}, ['command_id', 'action'], write),
            descriptor('session_console_handoff', '仅用户点击时领取同一签名指令的宿主通知；已尝试的不重复通知。',
                       {'command_id': command_id, 'reserve': {'type': 'boolean'}}, ['command_id'], write),
            descriptor('session_console_notified', '登记宿主通知是否确认，不代替实际派发工具回执。',
                       {'command_id': command_id, 'state': {'type': 'string', 'enum': ['delivered', 'unknown']}}, ['command_id', 'state'], write)]


def html():
    static = ROOT/'workbench/console-static'
    value = (static/'index.html').read_text()
    value = value.replace('<link rel="stylesheet" href="/console/styles.css">', '<style>'+(static/'styles.css').read_text()+'</style>')
    value = value.replace('<script src="/console/app.js" defer></script>', '')
    # IIFE initializes the SDK immediately; app.js waits on its handshake promise.
    scripts = ''.join('<script>'+ (static/name).read_text().replace('</script', '<\\/script')+'</script>' for name in ('host.js', 'app.js'))
    return value.replace('</body>', scripts+'</body>')


def assets(value):
    if isinstance(value, dict): return {k: assets(v) for k, v in value.items()}
    if isinstance(value, list): return [assets(v) for v in value]
    if isinstance(value, str) and value.startswith('/api/media?'): return 'http://127.0.0.1:8770'+value
    return value


def result(value):
    value = assets(value)
    return {'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False)}], 'structuredContent': value}


def handle(method, params):
    if method == 'initialize':
        return {'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}, 'resources': {}},
                'serverInfo': {'name': 'localization-console', 'version': '0.3.1'},
                'instructions': '本工具不启动制作或定时调度。UI指令仅在用户点击后签名入队；宿主按单次交办消息中的精确指令ID，使用本聊天官方原生工具执行并立即登记回执。'}
    if method == 'ping': return {}
    if method == 'tools/list': return {'tools': tools()}
    if method == 'resources/list': return {'resources': [{'uri': RESOURCE, 'name': '译制台', 'mimeType': 'text/html;profile=mcp-app'}]}
    if method == 'resources/read':
        if params.get('uri') != RESOURCE: raise ValueError('未知资源')
        return {'contents': [{'uri': RESOURCE, 'mimeType': 'text/html;profile=mcp-app', 'text': html(),
                              '_meta': {'ui': {'csp': {'resourceDomains': ['http://127.0.0.1:8770']}}}}]}
    if method == 'tools/call':
        args = params.get('arguments') or {}
        name = params['name']
        if name == 'session_console_open':
            return {**result({'url': URL, 'page_size': 8, 'mode': 'user_click', 'agent_polling': False}),
                    '_meta': {'ui': {'resourceUri': RESOURCE}}}
        if name == 'session_console_sessions':
            return result(data.overview(args.get('query', ''), page=args.get('page', 1), archived=args.get('archived', False)))
        if name == 'session_console_read': return result(read_api(data, args['path']))
        if name == 'session_console_command': return result(data.enqueue(args))
        if name == 'session_console_handoff': return result(handoff(data, args['command_id'], args.get('reserve') is True))
        if name == 'session_console_notified': return result(notified(data, args['command_id'], args['state']))
        if name == 'session_console_wait':
            revision = int(args['revision'])
            current = events.subscribe()
            try:
                if revision >= 0 and current == revision: events.wait(revision, timeout=25)
                return result(events.status())
            finally: events.unsubscribe()
        raise ValueError('未知工具')
    raise ValueError('不支持的方法')


def serve():
    output_lock = threading.Lock()
    def respond(request):
        try: response = {'jsonrpc': '2.0', 'id': request['id'], 'result': handle(request['method'], request.get('params', {}))}
        except Exception as exc:
            response = {'jsonrpc': '2.0', 'id': request['id'], 'error': {'code': -32602, 'message': type(exc).__name__+': request not supported'}}
        with output_lock:
            print(json.dumps(response, ensure_ascii=False), flush=True)
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix='console-mcp') as pool:
        for line in sys.stdin:
            try: request = json.loads(line)
            except ValueError: continue
            if isinstance(request, dict) and 'id' in request: pool.submit(respond, request)


if __name__ == '__main__': serve()
