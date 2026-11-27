"""MCP Apps conversation panel for local Director chats."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from uuid import UUID

import native_queue
import panel_receipts
import panel_state

ROOT = Path(__file__).resolve().parent
VERSION = json.loads((ROOT / '.codex-plugin/plugin.json').read_text(encoding='utf-8'))['version']
MIME = 'text/html;profile=mcp-app'
ENTRY = 'ui://director-panel/entry.html'
PANEL = 'ui://director-panel/threads.html'
RECEIPT = 'ui://director-panel/receipt.html'
PROTOCOLS = ('2025-11-25', '2025-06-18', '2025-03-26', '2024-11-05')
RESOURCES = {ENTRY: '项目讨论串入口', PANEL: '项目讨论串', RECEIPT: '派工回执'}


def descriptor(name, title, description, resource=None):
    fields = {'view_key': {'type': 'string', 'minLength': 1, 'description': '当前聊天的只读配对码'}}
    required = []
    meta = {'ui': {'visibility': ['app', 'model'] if resource else ['app']}}
    if resource:
        meta['ui']['resourceUri'] = resource
        meta['openai/outputTemplate'] = resource
        meta['openai/ui'] = {'preferredModelDisplayMode': 'fullscreen' if resource == PANEL else 'inline'}
        if name == 'show_panel':
            meta['openai/ui']['entrypoints'] = [{'type': 'thread'}]
        elif name == 'open_panel_link':
            fields = {'url': {'type': 'string', 'enum': [panel_state.PANEL_LINK]}}
            required = ['url']
            meta['ui']['visibility'] = ['app']
            meta['openai/ui']['entrypoints'] = [{'type': 'deepLink', 'patterns': [panel_state.PANEL_LINK]}]
    if name == 'enqueue_task':
        fields = {'threadId': {'type': 'string', 'format': 'uuid'},
                  'prompt': {'type': 'string', 'minLength': 1, 'maxLength': 60000}}
        required = ['threadId', 'prompt']
        meta['ui']['visibility'] = ['model']
    if name == 'snapshot':
        fields['receipt_turn'] = {'type': 'string', 'format': 'uuid'}
    if name == 'open_thread':
        fields['thread_id'] = {'type': 'string', 'format': 'uuid'}
        required.append('thread_id')
    if name == 'set_thread_status':
        fields = {'thread_id': {'type': 'string', 'format': 'uuid'},
                  'expected_turn_id': {'type': 'string', 'format': 'uuid'},
                  'status': {'type': 'string', 'enum': ['completed', 'review']}}
        required = list(fields)
    return {
        'name': name, 'title': title, 'description': description,
        'inputSchema': {'type': 'object', 'properties': fields, 'required': required, 'additionalProperties': False},
        '_meta': meta,
        'annotations': {'readOnlyHint': name not in ('open_thread', 'enqueue_task', 'set_thread_status'),
                        'destructiveHint': False, 'openWorldHint': False},
    }


TOOLS = {tool['name']: tool for tool in (
    descriptor('enqueue_task', '加入执行串队列', '仅总讨论可调用。按用户对目标聊天的派工授权，将完整独立任务加入已登记执行串的本机 Codex 原生队列。'),
    descriptor('show_entry', '项目讨论串入口', '在总讨论显示面板入口，在执行串显示返回总讨论的入口。传入当前聊天的只读配对码。', ENTRY),
    descriptor('show_receipt', '派工回执', '登记本轮全部派工后，在总讨论正文显示自动更新的回执。传入本总讨论的只读配对码。', RECEIPT),
    descriptor('show_panel', '项目讨论串', '打开当前聊天的项目讨论串面板。可传入当前聊天的只读配对码。', PANEL),
    descriptor('open_panel_link', '项目讨论串', '从当前总讨论的回复末尾打开右侧面板。', PANEL),
    descriptor('snapshot', '读取讨论串', '刷新当前绑定的项目讨论串。'),
    descriptor('open_thread', '打开原生聊天', '按用户点击的行打开本项目已登记的本地聊天。'),
    descriptor('set_thread_status', '更改执行串状态', '按用户点击标为已完成或重新打开，只修改当前总讨论名下执行串的面板状态。'),
)}


class ProtocolError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def resource_content(uri):
    if uri not in RESOURCES:
        raise ProtocolError(-32002, '没有这个面板资源。')
    inline = uri != PANEL
    modes = {ENTRY: ['inline', 'fullscreen'], RECEIPT: ['inline'], PANEL: ['fullscreen']}[uri]
    meta = {'ui': {'prefersBorder': False, 'csp': {'connectDomains': [], 'resourceDomains': []}},
            'openai/ui': {'availableDisplayModes': modes, 'preferredDisplayMode': modes[0]}}
    if inline:
        meta.update({'openai/widgetShowCodexWidgetInline': True, 'openai/widgetHideAttribution': True,
                     'openai/widgetHeightHint': 49, 'openai/widgetMinFrameHeight': 0})
    page = (ROOT / 'assets/threads.html').read_text(encoding='utf-8')
    view = {PANEL: 'panel', ENTRY: 'entry', RECEIPT: 'receipt'}[uri]
    page = page.replace('__DIRECTOR_VIEW__', view).replace('__DIRECTOR_VERSION__', VERSION)
    return {'uri': uri, 'mimeType': MIME, 'text': page, '_meta': meta}


def open_registered(data, target):
    try:
        uid = str(UUID(target))
    except (TypeError, ValueError, AttributeError):
        raise ValueError('聊天标识无效。') from None
    if uid != target or not data.get('paired'):
        raise ValueError('请先打开当前项目的面板。')
    titles = {row['thread_id']: row['title'] for row in data['threads']
              if row['thread_id'] and row['status'] not in ('archived', 'preparing')}
    titles[data['director_id']] = data['director_title']
    if uid not in titles:
        raise ValueError('此聊天不属于当前面板，或已经归档。')
    url = 'codex://threads/' + uid
    try:
        if sys.platform == 'win32':
            os.startfile(url)
        else:
            subprocess.run(['/usr/bin/open', '-b', 'com.openai.codex', url], check=True,
                           capture_output=True, timeout=5)
        opened = True
    except (subprocess.SubprocessError, OSError):
        opened = False
    return {'opened': opened, 'url': url, 'title': titles[uid]}


def validate_schema(spec, value):
    kind = spec['type']
    if kind == 'object' and isinstance(value, dict):
        props = spec['properties']
        if value.keys() <= props.keys() and set(spec['required']) <= value.keys():
            for key, field in value.items():
                validate_schema(props[key], field)
            return
    elif kind == 'string' and isinstance(value, str):
        if (spec.get('minLength', 1) <= len(value) <= spec.get('maxLength', 256)
                and ('enum' not in spec or value in spec['enum'])):
            return
    raise ProtocolError(-32602, '无效的工具参数。')


def call(params):
    name = params.get('name')
    args = params.get('arguments', {})
    if not isinstance(name, str) or name not in TOOLS or not isinstance(args, dict):
        raise ProtocolError(-32602, '无效的工具调用。')
    validate_schema(TOOLS[name]['inputSchema'], args)
    meta = params.get('_meta', {})
    try:
        actor = meta.get('threadId') if isinstance(meta, dict) else None
        if isinstance(meta, dict) and 'threadId' in meta and (not isinstance(actor, str) or not actor):
            raise ValueError('宿主提供的聊天标识无效。')
        if name == 'enqueue_task':
            if not actor or meta.get('hostId', 'local') != 'local':
                raise ValueError('需要宿主提供的本机总讨论身份。')
            result = native_queue.enqueue(actor, args['threadId'], args['prompt'])
            return {'content': [{'type': 'text', 'text': json.dumps(result)}], 'structuredContent': result}
        if name == 'set_thread_status':
            if not actor or meta.get('hostId', 'local') != 'local':
                raise ValueError('需要宿主提供的本机总讨论身份。')
            result = panel_state.update(actor, **args)
            label = '已标为完成。' if result['status'] == 'completed' else '已重新打开，未启动任务。'
            return {'content': [{'type': 'text', 'text': label}], 'structuredContent': result}
        if name == 'open_panel_link' and not actor:
            raise ValueError('请从项目总讨论的回复末尾打开面板。')
        if name == 'show_receipt' or 'receipt_turn' in args:
            data = panel_receipts.receipt(actor, args.get('view_key'), args.get('receipt_turn'))
            return {'content': [{'type': 'text', 'text': '派工回执'}], 'structuredContent': data}
        data = panel_state.snapshot(actor=actor, view_key=args.get('view_key'),
                                    include_usage=name in ('show_panel', 'open_panel_link', 'snapshot'))
        if name == 'open_panel_link' and (data.get('role') != 'director' or data.get('director_id') != actor):
            raise ValueError('请从项目总讨论的回复末尾打开面板。')
        if name == 'open_thread':
            data = open_registered(data, args['thread_id'])
            label = '已请求打开聊天。' if data['opened'] else '桌面端未能打开聊天。'
        elif not data.get('paired'):
            label = '请在当前 Director 聊天中使用面板入口或只读配对码。'
        elif data['role'] == 'worker':
            label = f"项目总讨论 · [返回总讨论](codex://threads/{data['director_id']})"
        else:
            label = f"{data['director_title']} · 项目讨论串 {sum(row['status'] != 'archived' for row in data['threads'])} 个"
    except (ValueError, PermissionError, KeyError) as exc:
        return {'isError': True, 'content': [{'type': 'text', 'text': str(exc)}]}
    return {'content': [{'type': 'text', 'text': label}], 'structuredContent': data}


def handle(method, params):
    if not isinstance(params, dict):
        raise ProtocolError(-32602, 'Invalid params')
    if method == 'initialize':
        version = params.get('protocolVersion')
        return {'protocolVersion': version if version in PROTOCOLS else PROTOCOLS[0],
                'serverInfo': {'name': 'director-panel', 'title': '项目讨论串', 'version': VERSION},
                'capabilities': {'tools': {}, 'resources': {}}}
    if method == 'ping':
        return {}
    if method == 'tools/list':
        return {'tools': list(TOOLS.values())}
    if method == 'tools/call':
        return call(params)
    if method == 'resources/list':
        return {'resources': [{'uri': uri, 'name': name, 'mimeType': MIME} for uri, name in RESOURCES.items()]}
    if method == 'resources/templates/list':
        return {'resourceTemplates': []}
    if method == 'resources/read':
        uri = params.get('uri')
        if not isinstance(uri, str):
            raise ProtocolError(-32602, 'Invalid URI')
        return {'contents': [resource_content(uri)]}
    raise ProtocolError(-32601, 'Method not found')


def serve():
    for line in sys.stdin:
        request_id = None
        try:
            try:
                msg = json.loads(line)
            except ValueError:
                raise ProtocolError(-32700, 'Parse error') from None
            if not isinstance(msg, dict) or msg.get('jsonrpc') != '2.0' or not isinstance(msg.get('method'), str):
                raise ProtocolError(-32600, 'Invalid request')
            if 'id' not in msg:
                continue
            request_id = msg['id']
            reply = {'result': handle(msg['method'], msg.get('params', {}))}
        except ProtocolError as exc:
            reply = {'error': {'code': exc.code, 'message': str(exc)}}
        except (OSError, sqlite3.Error, ValueError, KeyError, TypeError):
            reply = {'error': {'code': -32603, 'message': '无法读取本地面板数据。'}}
        print(json.dumps({'jsonrpc': '2.0', 'id': request_id, **reply}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    serve()
