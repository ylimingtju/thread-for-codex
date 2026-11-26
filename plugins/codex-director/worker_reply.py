"""Keep the appropriate navigation link on replies in registered project chats."""
import json
import re
import sqlite3
import sys

from panel_onboarding import explicit_reference
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
    start_hint = ""
    if name == 'UserPromptSubmit':
        prompt = event.get('prompt')
        if isinstance(prompt, str) and (prompt.strip() == '$codex-director:codex-director' or
                explicit_reference(actor, event.get('turn_id'), prompt)):
            start_hint = ('用户本轮主动调用 Thread for Codex 主插件或主技能。按主技能的首次设置规则核对本串角色及项目归属。'
                          '已有归属发生冲突时先让用户决定。若用户明确只咨询插件，请按该请求回答。\n')
    if not panel_db().is_file():
        return {'hookSpecificOutput': {'hookEventName': name, 'additionalContext': start_hint}} if start_hint else None
    with readonly(panel_db()) as db:
        row = db.execute(
            "SELECT id FROM directors WHERE id = ? UNION ALL "
            "SELECT directors.id FROM workers JOIN directors ON directors.id = workers.director "
            "WHERE workers.thread_id = ? AND workers.status != 'archived'", (actor, actor),
        ).fetchone()
    if not row:
        return {'hookSpecificOutput': {'hookEventName': name, 'additionalContext': start_hint}} if start_hint else None
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
        '总讨论动手前先定归属。协调、确认交付、直接引用唯一已知答案可自办。新调查、判断、设计、计算、审查、运行或修改默认派工，明确要求亲办除外。'
        '按点名或链接、已登记职责和近期相关派工选串，歧义只问冲突，交接保留本轮交付与权限边界。独立任务先按真实 hostId、threadId 取 wait_threads(timeoutMs: 0) 快照。'
        '确认空闲且无待启动或排队任务才直发，否则对获授权的本地配对串用 enqueue_task，取得条目 ID 才报已排队。仅明确要求立即补正同一任务才追加。'
        '每批 show_receipt 一次即结束，明确要求才持续等待。派工答疑确认本轮后默认只列原串链接。\n'
        if row['id'] == actor else ''
    )
    return {'hookSpecificOutput': {
        'hookEventName': name,
        'additionalContext': start_hint + role_hint + '每条最终答复（含追问）末尾空一行，单列以下链接一次。中途进展省略。\n' + footer,
    }}


if __name__ == '__main__':
    try:
        result = hook_result(json.load(sys.stdin.buffer))
        if result:
            print(json.dumps(result))
    except (ValueError, OSError, sqlite3.Error):
        # Navigation is optional when the registry is unavailable. Let the conversation continue.
        pass
