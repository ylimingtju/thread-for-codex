"""Keep the appropriate navigation link on replies in registered project chats."""
import json
import re
import sqlite3
import sys

from panel_state import PANEL_LINK, panel_db, readonly, uuid_text


FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def ends_with_footer(reply, url):
    lines = reply.rstrip().splitlines()
    if not lines:
        return False
    link = re.fullmatch(r" {0,3}(?:[←↩]\s*)?\[[^\]\n]+\]\((?:<([^>]+)>|([^\s()<>]+))\)", lines[-1])
    if not link or (link[1] or link[2]) != url:
        return False
    # Markdown can continue a quoted paragraph even when its next line omits ">".
    for line in reversed(lines[:-1]):
        if not line.strip():
            break
        if line.lstrip().startswith(">"):
            return False
    # An unclosed Markdown fence makes an otherwise exact final line literal text.
    fence = None
    for line in lines[:-1]:
        match = FENCE.match(line)
        if not match:
            continue
        marker, rest = match.groups()
        if fence is None:
            if marker[0] != '`' or '`' not in rest:
                fence = marker
        elif marker.startswith(fence) and not rest.strip():
            fence = None
    return fence is None


def hook_result(event):
    if not isinstance(event, dict):
        return
    name = event.get('hook_event_name')
    if name not in ('UserPromptSubmit', 'SessionStart', 'Stop'):
        return
    if name == 'SessionStart' and event.get('source') != 'resume':
        return
    if name == 'Stop':
        reply = event.get('last_assistant_message')
        if event.get('stop_hook_active') is not False or not isinstance(reply, str) or not reply.strip():
            return
    actor = uuid_text(event.get('session_id'))
    if not panel_db().is_file():
        return
    with readonly(panel_db()) as db:
        row = db.execute(
            "SELECT id FROM directors WHERE id = ? UNION ALL "
            "SELECT directors.id FROM workers JOIN directors ON directors.id = workers.director "
            "WHERE workers.thread_id = ? AND workers.status != 'archived'", (actor, actor),
        ).fetchone()
    if not row:
        return
    if row['id'] == actor:
        url, label = PANEL_LINK, '打开项目讨论串'
    else:
        url, label = f"codex://threads/{uuid_text(row['id'])}", '← 返回总讨论'
    footer = f"[{label}]({url})"
    if name == 'Stop':
        if ends_with_footer(reply, url):
            return
        return {'decision': 'block', 'reason': (
            '只修正上一条面向用户的最终答复末尾的导航链接。请直接重新给出完整答复，逐字保留原正文、格式和成果链接，'
            '只替换正文末尾的错误导航行，保留示例和引文。如果末尾的代码块尚未闭合，请先闭合。'
            '在正文后空一行，再原样附上下列链接一次。不要只发链接，不要重做任务或调用任何工具。'
            '如果看不到完整原文，请保留此前的交付，不要凭记忆重写。\n' + footer
        )}
    role_hint = (
        '本串是已登记的总讨论，负责选串、派工和确认交付。能直接引用已有答案时可直接答。'
        '需要调查、计算、实质判断、审查或修改文件时，交给执行串。派工失败时说明原因。'
        '确认送达并登记后，用本总讨论的 view_key 调用一次 director-panel.show_receipt，结束本轮。仅在用户明确要求等结果时持续等待。\n'
        if row['id'] == actor else ''
    )
    return {'hookSpecificOutput': {
        'hookEventName': name,
        'additionalContext': role_hint + '本串面向用户的回复（包括提问和直接追问的答复）以空行和以下独立一行结束，'
                             '链接只写一次。中途进展无需附链接。\n' + footer,
    }}


if __name__ == '__main__':
    try:
        result = hook_result(json.load(sys.stdin.buffer))
        if result:
            print(json.dumps(result))
    except (ValueError, OSError, sqlite3.Error):
        # Navigation is optional when the registry is unavailable. Let the conversation continue.
        pass
