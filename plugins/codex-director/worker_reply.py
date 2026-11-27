"""Keep the appropriate navigation link on replies in registered project chats."""
import json
import re
import sqlite3
import sys

from panel_onboarding import explicit_reference
from panel_state import PANEL_LINK, director_roster_hint, panel_db, readonly, sync_context_for_worker, uuid_text


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
    role_hint = ''
    if row['id'] == actor:
        role_hint = (
            '总讨论先定归属。可协调、汇总、核对交付及引用明确答案。除非用户本轮点名亲办，严禁总讨论读/搜业务源码、改项目文件或跑项目测试，也不要为写派工说明先翻源码。'
            '查进展与比对结果先用 digest。交付用1–3句讲明结论、跨串冲突和待拍板项，附原串链接。按点名、长期分工和近期派工选串，用 role/roles/decision 后台维护共识。'
            '独立任务先用实际 hostId、threadId 取 wait_threads(timeoutMs: 0)，空闲且无排队才直发，否则用 enqueue_task。每批 show_receipt 一次即结束，明确要求才持续等待。\n'
        )
    if name == 'UserPromptSubmit':
        context = director_roster_hint(actor) if row['id'] == actor else sync_context_for_worker(actor)
        if context:
            role_hint += context + '\n'
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
