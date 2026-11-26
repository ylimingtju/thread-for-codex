"""Inline dispatch receipts reconstructed from the native chats' durable turn history."""
import sqlite3
from xml.sax.saxutils import escape

import panel_state as state


def reply_status(history, owner, worker, tool, prompt, sent_ms):
    # Compare the actual inbound delegation. A later direct question in this worker is unrelated.
    template = "<codex_delegation>\n  <source_thread_id>{}</source_thread_id>\n  <input>{}</input>\n</codex_delegation>"
    inbound = history.execute("""SELECT t.status,t.completed_at,
            (f.item_type='agentMessage' AND json_extract(f.item_json,'$.phase')='final_answer'
             AND length(trim(json_extract(f.item_json,'$.text')))>0) AS delivered
        FROM thread_items i JOIN thread_turns t ON t.thread_id=i.thread_id AND t.turn_id=i.turn_id
        LEFT JOIN thread_items f ON f.thread_id=t.thread_id AND f.turn_id=t.turn_id
             AND f.item_id=t.final_agent_item_id
        WHERE i.thread_id=? AND i.item_type='functionCallOutput' AND i.created_at_ms>=?
          AND json_extract(i.item_json,'$.namespace')='codex_app' AND json_extract(i.item_json,'$.name')=?
          AND json_extract(i.item_json,'$.output') IN (?,?)
        ORDER BY i.rollout_ordinal LIMIT 1""", (
        worker, sent_ms, tool, template.format(owner, prompt), template.format(owner, escape(prompt)),
    )).fetchone()
    if not inbound or inbound["completed_at"] is None:
        return "running"
    if inbound["status"] == "completed" and inbound["delivered"]:
        return "review"
    if inbound["status"] in ("failed", "interrupted"):
        return "blocked"
    if inbound["status"] == "completed":
        return "missing"
    return "running"


def receipt(actor, key, turn_id=None):
    if not actor and not key:
        raise ValueError("请在已登记的总讨论中打开回执。")
    with state.readonly(state.panel_db()) as registry:
        column = "id" if actor else "view_key"
        owner = registry.execute("SELECT * FROM directors WHERE " + column + "=?", (actor or key,)).fetchone()
        if not owner or (key and key != owner["view_key"]):
            raise ValueError("当前聊天与派工回执不匹配。")
        workers = registry.execute("SELECT * FROM workers WHERE director=?", (owner["id"],)).fetchall()
    by_thread = {r["thread_id"]: r for r in workers if r["thread_id"]}
    by_pending = {r["pending_id"]: r for r in workers if r["pending_id"]}
    rows = []
    with state.readonly(state.home() / "thread_history_1.sqlite") as history:
        history.execute("BEGIN")
        latest = state.latest_turn(history, owner["id"])
        if not latest:
            raise ValueError("尚未读取到总讨论本轮记录。")
        turn_id = state.uuid_text(turn_id or latest["turn_id"])
        busy = latest["status"] not in ("completed", "interrupted", "failed")
        for tool in ("create_thread", "send_message_to_thread"):
            for args, result, sent_ms in state.dispatch_receipts(history, owner["id"], tool, turn_id):
                prompt = args["prompt"]
                if tool == "send_message_to_thread" and not prompt.startswith(state.DISPATCH_PREFIX):
                    continue
                target, pending = result.get("threadId"), result.get("clientThreadId")
                worker = by_thread.get(target) or by_pending.get(pending)
                if worker is None:
                    # Registration may follow the native receipt. Try again on the next refresh.
                    rows.append({"title": args.get("title") or "执行串", "status": "preparing"})
                    continue
                target = worker["thread_id"]
                if not target and pending:
                    target = state.pending_binding(pending_id=pending)
                    if target:
                        try:
                            state.track(owner["id"], title=worker["title"], thread_id=target, pending_id=pending)
                        except (ValueError, sqlite3.Error):
                            target = None  # The binding can become visible before its native thread.
                status = "preparing" if not target else "running"
                if target and not busy:
                    status = reply_status(history, owner["id"], target, tool, prompt, sent_ms)
                rows.append({"thread_id": target, "title": worker["title"], "status": status, "sent_ms": sent_ms})
    native = state.native_threads([r["thread_id"] for r in rows if r.get("thread_id")])
    for row in rows:
        row["title"] = state.display_title(native.get(row.get("thread_id")), row["title"])
    rows.sort(key=lambda row: row.get("sent_ms", 0))
    return {"paired": True, "role": "director", "director_id": owner["id"], "view_key": owner["view_key"],
            "receipt_turn": turn_id, "threads": rows, "busy": busy,
            "finished": bool(rows) and all(r["status"] in ("review", "blocked") for r in rows)}
