"""Read native project membership and the local host's chat-list receipts for this turn."""
import json
import secrets
import sqlite3
import time
from pathlib import Path
from urllib.parse import unquote

import panel_state as state


def explicit_reference(actor, turn, prompt=None):
    """Only use a structured selection on this user input, never text found in chat history."""
    if not turn:
        return False
    path = state.home() / "thread_history_1.sqlite"
    if not path.is_file():
        return False
    try:
        with state.readonly(path) as db:
            row = db.execute("""SELECT item_json FROM thread_items WHERE thread_id=? AND turn_id=?
                             AND item_type='userMessage' ORDER BY rollout_ordinal DESC LIMIT 1""",
                             (actor, turn)).fetchone()
        items = json.loads(row[0]).get("content", []) if row else []
    except (OSError, sqlite3.Error, ValueError):
        return False
    if prompt is not None and prompt.strip() != "\n".join(
            item.get("text", "") for item in items if item.get("type") == "text").strip():
        return False
    skill = Path(__file__).resolve().parent / "skills/codex-director/SKILL.md"
    for item in items:
        value = item.get("path")
        if not isinstance(value, str):
            continue
        if item.get("type") == "mention" and unquote(value) == "plugin://codex-director@director-local":
            return True
        if item.get("type") == "skill" and Path(value).is_absolute() and Path(value).resolve() == skill:
            return True
    return False


def listed_threads(actor):
    """The newest observation wins. Only an uninterrupted history cursor chain proves coverage."""
    rows, pages = {}, {}
    try:
        with state.readonly(state.home() / "thread_history_1.sqlite") as history:
            turn = state.latest_turn(history, actor)
            if not turn or turn["status"] != "inProgress":
                return rows, False
            for args, content, _ in state.tool_receipts(history, actor, "list_threads", turn["turn_id"]):
                try:
                    args, result = json.loads(args), json.loads(content)
                except (ValueError, TypeError):
                    continue
                if not isinstance(result, dict) or not isinstance(args, dict):
                    continue
                if args.get("hostId", "local") != "local" or args.get("source", "codex") != "codex" or args.get("archived"):
                    continue
                if args.get("mode") == "history" and "nextCursor" in result:
                    pages.setdefault(args.get("cursor"), result["nextCursor"])
                for row in result.get("threads", []) + result.get("pinnedThreads", []):
                    if isinstance(row, dict) and row.get("kind") == "codex" and row.get("hostId") == "local":
                        rows.setdefault(row["id"], row)
    except sqlite3.OperationalError:
        return rows, False
    cursor, seen = None, set()
    while cursor in pages and cursor not in seen:
        seen.add(cursor)
        cursor = pages[cursor]
        if cursor is None:
            return rows, True
    return rows, False


def project_ids(ids, listed):
    # Older desktop versions keep explicit thread assignments outside the native threads table.
    result = {}
    try:
        saved = json.loads((state.home() / ".codex-global-state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    if not isinstance(saved, dict):
        saved = {}
    assignments = saved.get("thread-project-assignments", {})
    hosts = saved.get("thread-project-membership-host-ids", {})
    with state.readonly(state.home() / "state_5.sqlite") as db:
        cols = {c["name"] for c in db.execute("PRAGMA table_info(threads)")}
        project = "project_id" if "project_id" in cols else "NULL"
        for row in db.execute(f"SELECT id,{project} AS project FROM threads WHERE archived=0 AND id IN "
                              "(SELECT value FROM json_each(?)) AND (thread_source IN ('agent_created_thread','user','chatgpt_handoff') "
                              "OR (thread_source IS NULL AND source='vscode'))", (json.dumps(list(ids)),)):
            uid = row["id"]
            entry = assignments.get(uid, {})
            saved_id = entry.get("projectId") if entry.get("projectKind") == "local" and hosts.get(uid) == "local" else None
            known = {p for p in (row["project"], saved_id) if p}
            if uid in listed:
                project_id = listed[uid].get("projectId")
                if project_id and (not known or known == {project_id}):
                    result[uid] = project_id
            elif len(known) == 1:
                result[uid] = known.pop()
    return result


def pending_workers(registry):
    if not registry:
        return {}
    rows = registry.execute("SELECT pending_id,director FROM workers WHERE thread_id IS NULL")
    return {uid: row["director"] for row in rows
            if (uid := state.pending_binding(pending_id=row["pending_id"]))}


def scope(actor, registry, *, candidates=False):
    listed, complete = listed_threads(actor)
    directors = dict(registry.execute("SELECT id,title FROM directors")) if registry else {}
    ids = {actor, *directors}
    if candidates:
        ids.update(listed)
    projects = project_ids(ids, listed)
    project = projects.get(actor)
    pending = pending_workers(registry)
    result = {"project_id": project, "pending_owner": pending.get(actor),
              "project_changed": bool(listed.get(actor, {}).get("projectId") and not project), "directors": [
        {"thread_id": uid, "title": listed.get(uid, {}).get("title") or name}
        for uid, name in directors.items() if uid != actor and project and projects.get(uid) == project]}
    active = state.native_threads(list(directors))
    unresolved = [uid for uid in directors if uid != actor and uid in active and not active[uid]["archived"]
                  and uid not in projects and (uid not in listed or listed[uid].get("projectId"))]
    result["unresolved_directors"] = len(unresolved) if project else 0
    if candidates:
        if actor not in directors:
            raise ValueError("首次完成总讨论登记后才能列出候选。")
        workers = {r[0] for r in registry.execute("SELECT thread_id FROM workers WHERE thread_id IS NOT NULL")}
        workers.update(pending)
        result["complete"] = complete and bool(project) and not any(
            r.get("projectId") == project and uid not in projects for uid, r in listed.items())
        result["candidates"] = [{"thread_id": uid, "title": row["title"]} for uid, row in listed.items()
                                if project and projects.get(uid) == project and uid not in directors and uid not in workers]
    return result


def adopt(actor, *, thread_id, title, project_id, role=None):
    actor, thread_id = state.uuid_text(actor), state.uuid_text(thread_id)
    listed, _ = listed_threads(actor)
    ids = (actor, thread_id)
    with state.write_registry() as db:
        if not db.execute("SELECT 1 FROM directors WHERE id=?", (actor,)).fetchone():
            raise ValueError("只有已登记的总讨论可以接入旧串。")
        if db.execute("SELECT 1 FROM directors WHERE id=?", (thread_id,)).fetchone():
            raise ValueError("该串已经是总讨论。")
        projects = project_ids(ids, listed)
        if not project_id or any(uid not in listed or projects.get(uid) != project_id for uid in ids):
            raise ValueError("请重新从本机原生活跃聊天列表确认两个聊天属于选定项目。")
        target = state.local_thread(thread_id)
        if (target["archived"] or listed[thread_id].get("title") != title
                or state.display_title(target, title) != title):
            raise ValueError("候选已归档或标题已变化，请重新确认。")
        if thread_id in pending_workers(db):
            raise ValueError("候选已有准备中的派工归属，请先完成原配对。")
        if not state.find_worker(db, actor, thread_id, None):
            db.execute("INSERT INTO workers VALUES(?,?,NULL,?,?,'ready','',?,NULL)",
                       (actor, thread_id, secrets.token_urlsafe(24), state.label(title, 240), time.time()))
        if role is not None:
            state._upsert_worker_role(db, actor, thread_id, role, time.time())
    return state.snapshot(actor)
