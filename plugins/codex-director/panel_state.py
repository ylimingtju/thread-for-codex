"""Local, host-thread-bound registry for the Director conversation panel."""
import argparse
from contextlib import closing, contextmanager, nullcontext
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import sqlite3
import stat
import sys
import time
from uuid import UUID
from xml.sax.saxutils import unescape

from panel_usage import usage_for_threads


# A desktop link only. No web service or chat ID is needed to open the current panel.
PANEL_LINK = "https://thread-for-codex.invalid/panel"
DISPATCH_PREFIX = "【Director 派工】"


def home():
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def panel_db():
    return home() / "codex-director" / "panel.sqlite3"


def readonly(path):
    conn = sqlite3.connect(path.absolute().as_uri() + "?mode=ro", uri=True, timeout=1)
    conn.row_factory = sqlite3.Row
    return closing(conn)


@contextmanager
def write_registry():
    path = panel_db()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if sys.platform == "win32":
        # O_NOFOLLOW is unavailable on Windows. Create exclusively or check the existing file.
        try:
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
        except FileExistsError:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise OSError("面板数据库路径必须指向普通文件。") from None
    else:
        os.close(os.open(path, os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600))
    with closing(sqlite3.connect(path, timeout=5)) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        db.execute("""CREATE TABLE IF NOT EXISTS directors(
            id TEXT PRIMARY KEY, title TEXT NOT NULL, view_key TEXT UNIQUE NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS workers(
            director TEXT NOT NULL REFERENCES directors(id), thread_id TEXT UNIQUE,
            pending_id TEXT, view_key TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
            status TEXT NOT NULL, summary TEXT NOT NULL, updated REAL NOT NULL, turn_id TEXT,
            UNIQUE(director,pending_id), CHECK(thread_id IS NOT NULL OR pending_id IS NOT NULL))""")
        # A separate table keeps the registry writable by earlier plugin versions.
        db.execute("""CREATE TABLE IF NOT EXISTS worker_usage_start(
            director TEXT NOT NULL, thread_id TEXT NOT NULL, since REAL NOT NULL,
            PRIMARY KEY(director,thread_id))""")
        yield db


def uuid_text(value):
    try:
        if isinstance(value, str) and str(UUID(value)) == value:
            return value
    except ValueError:
        pass
    raise ValueError("缺少有效的本地 Codex 聊天 ID。")


def label(value, limit=2500):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError("标题、标识或进展说明为空或过长。")
    return value.strip()


def local_thread(thread, *, worker=False):
    with readonly(home() / "state_5.sqlite") as db:
        row = db.execute("SELECT * FROM threads WHERE id=?", (thread,)).fetchone()
    if not row or not (row["thread_source"] in ("agent_created_thread", "user", "chatgpt_handoff")
                       or (row["thread_source"] is None and row["source"] == "vscode")):
        raise ValueError("本机尚未找到对应的独立 Codex 聊天。")
    if worker and row["thread_source"] != "agent_created_thread":
        raise ValueError("该聊天不是 Codex 创建的执行串。请使用本次派工实际返回的 ID。")
    return row


def display_title(native, fallback):
    if native is None:
        return fallback
    if "name" in native.keys():
        name = native["name"]
    elif "title" in native.keys():
        name = native["title"]
        if "first_user_message" in native.keys() and name == native["first_user_message"]:
            return fallback
    else:
        return fallback
    return name if isinstance(name, str) and name.strip() else fallback


def native_threads(ids):
    # On current Codex, name is the sidebar label and title often contains the first prompt.
    try:
        with readonly(home() / "state_5.sqlite") as db:
            columns = {row["name"] for row in db.execute("PRAGMA table_info(threads)")}
            fields = ["id", "archived", "archived_at"]
            if "rollout_path" in columns:
                fields.append("rollout_path")
            if "name" in columns:
                fields.append("name")
            else:
                fields.extend(key for key in ("title", "first_user_message") if key in columns)
            rows = db.execute("SELECT " + ",".join(fields) + """ FROM threads
                WHERE id IN (SELECT value FROM json_each(?))""", (json.dumps(ids),))
            return {row["id"]: row for row in rows}
    except sqlite3.Error:
        return {}


def latest_turn(db, thread):
    return db.execute("""SELECT t.turn_id,t.status,t.started_at,t.completed_at,
            EXISTS(SELECT 1 FROM thread_items i
                   WHERE i.thread_id=t.thread_id AND i.turn_id=t.turn_id
                     AND i.item_id=t.final_agent_item_id AND i.item_type='agentMessage'
                     AND json_extract(i.item_json,'$.phase')='final_answer') AS delivered,
            (SELECT p.started_at FROM thread_turns p
             WHERE p.thread_id=t.thread_id AND p.started_at IS NOT NULL AND p.rollout_ordinal<t.rollout_ordinal
             ORDER BY p.rollout_ordinal DESC LIMIT 1) AS previous_start,
            (SELECT substr(CASE WHEN i.item_type='userMessage' THEN json_extract(i.item_json,'$.content[0].text')
                                ELSE json_extract(i.item_json,'$.output') END,1,1024)
             FROM thread_items i WHERE i.thread_id=t.thread_id AND i.turn_id=t.turn_id AND (
                 (i.item_type='userMessage' AND trim(json_extract(i.item_json,'$.content[0].text'))<>'')
                 OR (i.item_type='functionCallOutput' AND json_extract(i.item_json,'$.namespace')='codex_app'
                     AND json_extract(i.item_json,'$.name') IN ('create_thread','send_message_to_thread')
                     AND json_extract(i.item_json,'$.output') LIKE '<codex_delegation>%'))
             ORDER BY i.rollout_ordinal LIMIT 1) AS request
        FROM thread_turns t WHERE t.thread_id=? AND t.started_at IS NOT NULL
        ORDER BY t.rollout_ordinal DESC LIMIT 1""", (thread,)).fetchone()


def current_turn(thread):
    if thread:
        try:
            with readonly(home() / "thread_history_1.sqlite") as db:
                turn = latest_turn(db, thread)
                return turn["turn_id"] if turn else None
        except sqlite3.Error:
            pass
    return None


def initialize(actor, title, *, alongside=False):
    import panel_onboarding
    actor, title = uuid_text(actor), label(title, 240)
    local_thread(actor)
    with write_registry() as db:
        if db.execute("SELECT 1 FROM workers WHERE thread_id=?", (actor,)).fetchone():
            raise ValueError("已登记的执行串不能成为新的项目总线程。")
        if not db.execute("SELECT 1 FROM directors WHERE id=?", (actor,)).fetchone():
            context = panel_onboarding.scope(actor, db)
            if context["pending_owner"]:
                raise ValueError("本串已有准备中的执行串归属，请先完成原配对。")
            if context["project_changed"] and not alongside:
                raise ValueError("当前聊天的项目归属已变化，请重新定位。")
            conflicts = context["directors"]
            if conflicts and not alongside:
                raise ValueError("本项目已有总讨论，请先让用户选择：" + json.dumps(conflicts, ensure_ascii=False))
            if context["unresolved_directors"] and not alongside:
                raise ValueError("部分已登记总讨论的项目尚不明确。请核对本机聊天列表，再决定是否另设。")
        db.execute("""INSERT INTO directors VALUES(?,?,?) ON CONFLICT(id)
                      DO UPDATE SET title=excluded.title""", (actor, title, secrets.token_urlsafe(24)))
    return snapshot(actor)


def handles(thread_id, pending_id):
    if thread_id is None and pending_id is None:
        raise ValueError("需要派工返回的 thread_id 或 pending_id。")
    return (uuid_text(thread_id) if thread_id is not None else None,
            label(pending_id, 256) if pending_id is not None else None)


def find_worker(db, owner, thread_id, pending_id):
    rows = db.execute("""SELECT rowid,* FROM workers WHERE thread_id=?
                         OR (director=? AND pending_id=?)""", (thread_id, owner, pending_id)).fetchall()
    if len(rows) > 1:
        raise ValueError("正式聊天 ID 与准备中的记录不一致。")
    if not rows:
        return None
    row = rows[0]
    if row["director"] != owner:
        raise ValueError("该执行串已属于另一个总线程。")
    if ((row["thread_id"] and thread_id and row["thread_id"] != thread_id)
            or (row["pending_id"] and pending_id and row["pending_id"] != pending_id)):
        raise ValueError("同一笔派工返回了互不一致的标识。")
    return row


def pending_binding(thread_id=None, *, pending_id=None):
    try:
        data = json.loads((home() / ".codex-global-state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    matches = set()
    prefix = "thread-client-id-v1:local%3A"
    for name, atoms in data.items():
        if not name.startswith("electron-owner-atoms:") or not isinstance(atoms, dict):
            continue
        bindings = atoms.get("client-thread-bindings-v1")
        if not isinstance(bindings, dict):
            continue
        target = thread_id or bindings.get(pending_id)
        if not isinstance(target, str):
            continue
        pending = atoms.get(prefix + target)
        if isinstance(pending, str) and bindings.get(pending) == target and pending_id in (None, pending):
            matches.add(pending if thread_id else target)
    return matches.pop() if len(matches) == 1 else None


def tool_receipts(db, actor, tool, turn_id=None):
    return db.execute("""SELECT json_extract(item_json,'$.arguments') AS args,
            json_extract(item_json,'$.result.content[0].text') AS content,
            coalesce(started_at_ms,created_at_ms) AS sent_ms FROM thread_items
        WHERE thread_id=? AND item_type='mcpToolCall' AND (? IS NULL OR turn_id=?)
          AND json_extract(item_json,'$.server')=?
          AND (? != 'enqueue_task' OR json_extract(item_json,'$.pluginId')='codex-director@director-local')
          AND json_extract(item_json,'$.tool')=?
          AND json_extract(item_json,'$.status')='completed'
          AND json_extract(item_json,'$.error') IS NULL
          AND coalesce(json_extract(item_json,'$.result.isError'),0)=0
          AND json_extract(item_json,'$.result.content[0].type')='text'
        ORDER BY rollout_ordinal DESC""", (actor, turn_id, turn_id, "director-panel" if tool == "enqueue_task" else "codex_app", tool, tool))


def dispatch_receipts(db, actor, tool, turn_id=None):
    for arguments, content, sent_ms in tool_receipts(db, actor, tool, turn_id):
        try:
            args, result = json.loads(arguments), json.loads(content)
        except (TypeError, ValueError):
            continue
        if not isinstance(args, dict) or not isinstance(result, dict) or not isinstance(sent_ms, int):
            continue
        if not isinstance(args.get("prompt"), str) or result.get("hostId", "local") != "local":
            continue
        if tool == "enqueue_task" and (not isinstance(result.get("clientUserMessageId"), str)
                                        or not isinstance(result.get("queuedSubmissionId"), str)):
            continue
        if tool in ("send_message_to_thread", "enqueue_task") and (args.get("threadId") != result.get("threadId")
                                                 or args.get("hostId", "local") != "local"):
            continue
        yield args, result, sent_ms


def queued_turn(history, target, client_id):
    return history.execute("""SELECT t.turn_id,t.status,t.completed_at,i.created_at_ms,
            (f.item_type='agentMessage' AND json_extract(f.item_json,'$.phase')='final_answer'
             AND length(trim(json_extract(f.item_json,'$.text')))>0) AS delivered
        FROM thread_items i JOIN thread_turns t ON t.thread_id=i.thread_id AND t.turn_id=i.turn_id
        LEFT JOIN thread_items f ON f.thread_id=t.thread_id AND f.turn_id=t.turn_id AND f.item_id=t.final_agent_item_id
        WHERE i.thread_id=? AND i.item_type='userMessage' AND json_extract(i.item_json,'$.clientId')=?
        LIMIT 1""", (target, client_id)).fetchone()


def forward_receipts(actor, unstarted=None):
    with readonly(home() / "thread_history_1.sqlite") as db:
        for args, result, sent_ms in dispatch_receipts(db, actor, "send_message_to_thread"):
            try:
                thread = uuid_text(result.get("threadId"))
            except ValueError:
                continue
            if thread == actor or sent_ms <= 0:
                continue
            first_line = args["prompt"].partition("\n")[0]
            subject = first_line[len(DISPATCH_PREFIX):].strip()[:240] if first_line.startswith(DISPATCH_PREFIX) else ""
            yield thread, sent_ms / 1000, subject

        for args, result, sent_ms in dispatch_receipts(db, actor, "enqueue_task"):
            thread = result["threadId"]
            started = queued_turn(db, thread, result["clientUserMessageId"])
            if started and started["created_at_ms"]:
                subject = args["prompt"].partition("\n")[0][len(DISPATCH_PREFIX):].strip()[:240]
                yield thread, started["created_at_ms"] / 1000, subject
            elif unstarted is not None:
                unstarted[thread] = max(unstarted.get(thread, 0), sent_ms / 1000)


def latest_forwards(actor, target=None, *, unstarted=None):
    # A marked message assigns work. An older unmarked send needs explicit track(target).
    forwards = {}
    for thread, sent, subject in forward_receipts(actor, unstarted):
        if (target is None and subject) or target == thread:
            if thread not in forwards or sent > forwards[thread][0]:
                forwards[thread] = (sent, subject)
    return forwards


def created_by(actor, thread_id, pending_id):
    # Only structured, completed host tool returns are evidence. A UUID pasted in a message isn't.
    with readonly(home() / "thread_history_1.sqlite") as db:
        mapped = None
        for _, content, _ in tool_receipts(db, actor, "create_thread"):
            try:
                receipt = json.loads(content)
            except (ValueError, TypeError):
                continue
            if not isinstance(receipt, dict) or receipt.get("hostId") != "local":
                continue
            real, pending = receipt.get("threadId"), receipt.get("clientThreadId")
            if pending_id is not None and pending != pending_id:
                continue
            if thread_id is None or real == thread_id:
                return True, pending
            if pending:
                if mapped is None:
                    mapped = pending_binding(thread_id) or ""
                if pending == mapped:
                    return True, pending
    return False, None


def verify_launch(actor, thread_id, pending_id):
    # The desktop returns the ID before its local history transaction is necessarily visible.
    for delay in (0, 0.1, 0.3, 0.6, 1.0):
        if delay:
            time.sleep(delay)
        try:
            if thread_id and pending_id is None:
                forward = latest_forwards(actor, thread_id).get(thread_id)
                if forward:
                    local_thread(thread_id)
                    return None, forward
            verified, bound_pending = created_by(actor, thread_id, pending_id)
            if verified:
                if thread_id:
                    local_thread(thread_id, worker=True)
                return bound_pending, None
        except (sqlite3.Error, ValueError):
            continue
    raise ValueError("尚无本总线程对应的本地派工回执或工作区绑定，请稍后用原派工的 ID 重试。")


def record_forward(db, owner, thread, forward, title, summary):
    sent, subject = forward
    old = find_worker(db, owner, thread, None)
    if db.execute("SELECT 1 FROM directors WHERE id=?", (thread,)).fetchone():
        raise ValueError("不能把总线程登记为执行串。")
    if old and old["updated"] >= sent:
        return
    summary = summary or subject or "总线程已向原串派工"
    if old:
        if old["status"] == "ready":
            db.execute("INSERT OR IGNORE INTO worker_usage_start VALUES(?,?,?)", (owner, thread, sent))
        db.execute("""UPDATE workers SET status='running',summary=?,updated=?,turn_id=NULL
                      WHERE rowid=?""", (summary, sent, old["rowid"]))
    else:
        db.execute("INSERT INTO workers VALUES(?,?,NULL,?,?,'running',?,?,NULL)",
                   (owner, thread, secrets.token_urlsafe(24), title, summary, sent))


def track(actor, *, title, thread_id=None, pending_id=None, summary=None):
    actor, title = uuid_text(actor), label(title, 240)
    thread_id, pending_id = handles(thread_id, pending_id)
    summary = label(summary) if summary is not None else ""
    with readonly(panel_db()) as db:
        if not db.execute("SELECT 1 FROM directors WHERE id=?", (actor,)).fetchone():
            raise ValueError("只有已初始化的总线程可以登记派工。")
        old = find_worker(db, actor, thread_id, pending_id)
    forward = None
    if not old or (thread_id and not old["thread_id"]) or (pending_id and not old["pending_id"]):
        matched, forward = verify_launch(actor, thread_id or (old and old["thread_id"]), pending_id or (old and old["pending_id"]))
        pending_id = pending_id or matched
    elif thread_id and pending_id is None:
        forward = latest_forwards(actor, thread_id).get(thread_id)
    with write_registry() as db:
        if thread_id and db.execute("SELECT 1 FROM directors WHERE id=?", (thread_id,)).fetchone():
            raise ValueError("不能把总线程登记为执行串。")
        old = find_worker(db, actor, thread_id, pending_id)
        if old and old["status"] == "ready" and (not forward or forward[0] <= old["updated"]):
            raise ValueError("请先向待派工的旧串发送实际任务，再用本次成功回执登记。")
        if forward:
            record_forward(db, actor, thread_id, forward, title, summary)
        elif not old:
            db.execute("INSERT INTO workers VALUES(?,?,?,?,?,?,?,?,?)",
                       (actor, thread_id, pending_id, secrets.token_urlsafe(24), title,
                        "running" if thread_id else "preparing", summary, time.time(), current_turn(thread_id)))
        elif not old["thread_id"] and thread_id:
            db.execute("""UPDATE workers SET thread_id=?,title=?,status='running',summary=?,
                          updated=?,turn_id=? WHERE rowid=?""",
                       (thread_id, title, summary, time.time(), current_turn(thread_id), old["rowid"]))
        elif old["title"] != title or (pending_id and not old["pending_id"]):
            db.execute("UPDATE workers SET title=?,pending_id=coalesce(pending_id,?) WHERE rowid=?",
                       (title, pending_id, old["rowid"]))
    if thread_id:
        usage_starts(actor, {thread_id: pending_id or (old and old["pending_id"])})
    return snapshot(actor)


def update(actor, *, status, summary=None, thread_id=None, pending_id=None, expected_turn_id=None):
    actor = uuid_text(actor)
    manual = expected_turn_id is not None
    if manual:
        uuid_text(expected_turn_id)
        if status not in ("completed", "review") or pending_id is not None:
            raise ValueError("只能标记已回复或已完成的正式执行串。")
    else:
        summary = label(summary)
    if status not in ("preparing", "running", "waiting", "review", "completed", "blocked", "archived"):
        raise ValueError("无效的执行串状态。")
    with write_registry() as db:
        director = db.execute("SELECT 1 FROM directors WHERE id=?", (actor,)).fetchone()
        if director:
            thread_id, pending_id = handles(thread_id, pending_id)
            row = find_worker(db, actor, thread_id, pending_id)
            if manual and db.execute("SELECT 1 FROM directors WHERE id=?", (thread_id,)).fetchone():
                raise ValueError("不能更改总讨论的任务状态。")
        else:
            if manual or pending_id is not None or thread_id not in (None, actor) or status in ("completed", "archived", "preparing"):
                raise ValueError("执行串只能报告自己的进展，结果由总线程确认。")
            row = db.execute("SELECT rowid,* FROM workers WHERE thread_id=?", (actor,)).fetchone()
        if not row:
            raise ValueError("该执行串尚未登记。")
        if not row["thread_id"] and status not in ("preparing", "blocked"):
            raise ValueError("请先补全真实聊天 ID。")
        if row["thread_id"] and status == "preparing":
            raise ValueError("该执行串已经创建。")
        if not manual and row["status"] == "ready" and status != "archived":
            # A queued task may start before the director opens its receipt.
            forward = latest_forwards(row["director"]).get(row["thread_id"])
            if not forward or forward[0] <= row["updated"]:
                raise ValueError("尚未收到开始执行的派工。")
            record_forward(db, row["director"], row["thread_id"], forward, row["title"], forward[1])
        turn = expected_turn_id if manual else current_turn(row["thread_id"])
        if manual:
            summary = validate_status_change(actor, row, status, turn)
        if not director and row["status"] == "completed" and (not turn or turn == row["turn_id"]):
            raise ValueError("本轮任务已由总线程确认；新的追问将恢复执行。")
        if status == "archived":
            with readonly(home() / "state_5.sqlite") as native:
                archived = native.execute("SELECT archived FROM threads WHERE id=?", (row["thread_id"],)).fetchone()
            if not archived or not archived[0]:
                raise ValueError("原生聊天尚未手动归档。")
            # The overlay follows native archiving and restoration without destroying the last task status.
        else:
            db.execute("UPDATE workers SET status=?,summary=?,updated=?,turn_id=? WHERE rowid=?",
                       (status, summary, time.time(), turn, row["rowid"]))
    return {"status": status} if manual else snapshot(actor)


def task_excerpt(request):
    request = (request or "").strip()
    if request.startswith("<codex_delegation>"):
        request = unescape(request.partition("<input>")[2].partition("</input>")[0].strip())
    line = request.splitlines()[0] if request else ""
    return line.removeprefix(DISPATCH_PREFIX).strip()[:240]


def observed(row, turn, native, forward=None):
    status, summary, updated = row["status"], row["summary"], row["updated"]
    if summary in ("执行串已交付，待总线程确认", "总线程已向原串派工"):
        summary = ""
    if native and native["archived"]:
        return "archived", summary, native["archived_at"] or updated
    if status == "ready" or not row["thread_id"]:
        return status, summary, updated
    if not turn:
        return "unconfirmed" if status == "running" else status, summary, updated
    # The previous turn can still be the newest one while the forwarded prompt is queued.
    if row["turn_id"] is None and (
        turn["started_at"] < int(updated)
        or (status == "running" and turn["completed_at"] is not None and turn["completed_at"] <= updated)
    ):
        if status == "review" and not summary:
            summary = task_excerpt(turn["request"])
        return ("pending" if status == "running" else status), summary, updated
    new_turn = row["turn_id"] != turn["turn_id"]
    request = task_excerpt(turn["request"])
    # A dispatch registered without a turn ID must match this turn, not a later follow-up.
    previous_start = turn["previous_start"]
    first_after_dispatch = row["turn_id"] is None and status == "running" and (
        previous_start is None or (
            forward and forward[0] == updated and previous_start < int(updated)
            and (not request or not forward[1] or request == forward[1])
        )
    )
    if not summary or (new_turn and not first_after_dispatch):
        summary = request
    if turn["status"] == "inProgress":
        if not new_turn and status in ("waiting", "blocked"):
            return status, summary, updated
        if status == "running" and (not new_turn or first_after_dispatch):
            return status, summary, updated
        return "running", summary or "原串已收到新的追问", turn["started_at"]
    if not new_turn and status != "running":
        return status, summary, updated
    if turn["status"] in ("failed", "interrupted"):
        return "blocked", "本轮执行失败" if turn["status"] == "failed" else "本轮已中断", turn["completed_at"] or updated
    if turn["status"] == "completed":
        if turn["delivered"]:
            return "review", summary, turn["completed_at"] or updated
        return "blocked", "本轮已结束，尚无已交付的答复", turn["completed_at"] or updated
    return ("unconfirmed" if status == "running" else status), summary, updated


def queue_depths(thread_ids):
    try:
        with readonly(home() / "queue_1.sqlite") as queues:
            return dict(queues.execute("SELECT thread_id,count(*) FROM queued_items WHERE thread_id IN "
                                      "(SELECT value FROM json_each(?)) GROUP BY thread_id",
                                      (json.dumps(thread_ids),)))
    except sqlite3.Error:
        return None


def queue_status(status, thread, turn, depths, unstarted):
    depth = None if depths is None else depths.get(thread, 0)
    if status in ("archived", "waiting", "blocked") or (turn and turn["status"] == "inProgress"):
        return status, depth
    if depth:
        return "queued", depth
    if thread in unstarted and (not turn or unstarted[thread] >= turn["started_at"]):
        return "unconfirmed", depth
    return status, depth


def status_turn(status, turn, native, depth):
    if (status in ("review", "completed") and depth == 0 and native and not native["archived"]
            and turn and turn["status"] == "completed" and turn["completed_at"] is not None and turn["delivered"]):
        return turn["turn_id"]
    return None


def validate_status_change(actor, row, status, expected_turn):
    from panel_onboarding import project_ids

    target = row["thread_id"]
    if not target or actor == target or row["status"] in ("archived", "ready") or local_thread(actor)["archived"]:
        raise ValueError("只能更改本总讨论下已派工、未归档的执行串。")
    native = local_thread(target)
    projects = project_ids((actor, target), {})
    if actor in projects and target in projects and projects[actor] != projects[target]:
        raise ValueError("该执行串与总讨论已位于不同项目。")
    # Plugin queue submissions and this update share the registry write lock.
    depths = queue_depths([target])
    unstarted = {}
    try:
        forward = latest_forwards(actor, target, unstarted=unstarted).get(target)
        with readonly(home() / "thread_history_1.sqlite") as history:
            turn = latest_turn(history, target)
    except sqlite3.Error:
        raise ValueError("暂时无法确认原串状态，请稍后刷新。") from None
    if depths is None or not turn:
        raise ValueError("暂时无法确认原串状态或队列，请稍后刷新。")
    if turn["turn_id"] != expected_turn:
        raise ValueError("原串已有新回合或派工，请刷新后再操作。")
    if forward and forward[0] > row["updated"] and (
        turn["started_at"] < int(forward[0]) or (turn["completed_at"] or 0) <= forward[0]
    ):
        raise ValueError("原串已有新派工尚未完成，请先查看原串。")
    actual, summary, _ = observed(row, turn, native, forward)
    actual, depth = queue_status(actual, target, turn, depths, unstarted)
    if depth or actual in ("queued", "unconfirmed"):
        raise ValueError("原串有任务排队或尚未确认开始，请先查看原串。")
    if not status_turn(actual, turn, native, depth) or actual == status:
        raise ValueError("当前状态已变化。只可在原串答复且空闲后标记或重新打开。")
    return summary


def sync_forwards(owner, rows, forwards):
    stamps = {row["thread_id"]: row["updated"] for row in rows}
    changed = False
    for thread, forward in forwards.items():
        if stamps.get(thread, 0) >= forward[0]:
            continue
        try:
            native = local_thread(thread)
            title = display_title(native, forward[1])
            with write_registry() as db:
                record_forward(db, owner, thread, forward, title, forward[1])
            changed = True
        except (ValueError, sqlite3.OperationalError):
            continue  # Another Director owns it, or the host has not published the thread yet.
    return changed


def usage_starts(owner, workers):
    if not workers:
        return {}
    with readonly(panel_db()) as db:
        has_starts = db.execute("SELECT 1 FROM sqlite_master WHERE name='worker_usage_start'").fetchone()
        starts = dict(db.execute("SELECT thread_id,since FROM worker_usage_start WHERE director=?", (owner,))) if has_starts else {}
    missing = workers.keys() - starts.keys()
    if missing:
        # Zero marks a chat created for this project. Old chats start at a successful assignment.
        discovered = {}
        try:
            for thread in missing:
                pending = workers[thread]
                if created_by(owner, None if pending else thread, pending)[0]:
                    discovered[thread] = 0
            reused = missing - discovered.keys()
            if reused:
                first, marked = {}, {}
                for thread, sent, subject in forward_receipts(owner):
                    if thread in reused:
                        first[thread] = min(sent, first.get(thread, sent))
                        if subject:
                            marked[thread] = min(sent, marked.get(thread, sent))
                # Explicitly registered legacy chats may have only unmarked receipts.
                discovered.update(first | marked)
        except sqlite3.Error:
            pass
        if discovered:
            starts.update(discovered)
            try:
                with write_registry() as db:
                    db.executemany("INSERT OR IGNORE INTO worker_usage_start VALUES(?,?,?)",
                                   [(owner, thread, since) for thread, since in discovered.items()])
            except sqlite3.OperationalError:
                pass  # A read-only snapshot can still use verified receipts until the next refresh.
    return starts


def project_usage(owner, rows, native_by_id):
    workers = {r["thread_id"]: r["pending_id"] for r in rows if r["thread_id"] and r["status"] != "ready"}
    starts = usage_starts(owner, workers)
    sources = []
    for thread in (owner, *workers):
        native = native_by_id.get(thread)
        path = native["rollout_path"] if native and "rollout_path" in native.keys() else None
        if thread != owner and thread not in starts:
            path = None  # Without a dispatch boundary, an old chat's history is out of scope.
        sources.append((path, starts.get(thread) or None))
    return usage_for_threads(sources)


def snapshot(actor=None, view_key=None, *, include_usage=False):
    if actor is not None:
        actor = uuid_text(actor)
    if not (actor or view_key) or not panel_db().exists():
        return {"paired": False}
    # A widget key can only read one view. When the host supplies an identity it takes precedence.
    column = "id" if actor else "view_key"
    with readonly(panel_db()) as db:
        db.execute("BEGIN")
        director = db.execute("SELECT * FROM directors WHERE " + column + "=?", (actor or view_key,)).fetchone()
        role = "director"
        if director:
            own_key = director["view_key"]
            rows = db.execute("SELECT * FROM workers WHERE director=? ORDER BY rowid", (director["id"],)).fetchall()
        else:
            column = "thread_id" if actor else "view_key"
            worker = db.execute("SELECT * FROM workers WHERE " + column + "=?", (actor or view_key,)).fetchone()
            if not worker:
                if actor and view_key:
                    raise ValueError("配对码与当前聊天不匹配。")
                return {"paired": False}
            role, own_key, rows = "worker", worker["view_key"], [worker]
            director = db.execute("SELECT * FROM directors WHERE id=?", (worker["director"],)).fetchone()
        if view_key is not None and view_key != own_key:
            raise ValueError("配对码与当前聊天不匹配。")

    forwards, unstarted = {}, {}
    dispatch_read = False
    if role == "director":
        try:
            forwards = latest_forwards(director["id"], unstarted=unstarted)
            dispatch_read = True
        except sqlite3.OperationalError:
            pass  # Keep the explicit registry available without native history.
    if forwards and sync_forwards(director["id"], rows, forwards):
        with readonly(panel_db()) as db:
            rows = db.execute("SELECT * FROM workers WHERE director=? ORDER BY rowid", (director["id"],)).fetchall()
    native_by_id = native_threads([director["id"], *(r["thread_id"] for r in rows if r["thread_id"])])
    director_title = display_title(native_by_id.get(director["id"]), director["title"])
    result = {"paired": True, "role": role, "director_id": director["id"],
              "director_title": director_title, "view_key": own_key, "threads": []}
    if role == "director" and include_usage:
        result["token_usage"] = project_usage(director["id"], rows, native_by_id)
    depths = queue_depths([row["thread_id"] for row in rows]) if role == "director" else None
    can_change = role == "director" and actor and dispatch_read and actor in native_by_id and not native_by_id[actor]["archived"]
    renamed_workers = []
    for row, turn in observations(rows):
        native = native_by_id.get(row["thread_id"])
        title = display_title(native, row["title"])
        if title != row["title"]:
            renamed_workers.append((title, row["thread_id"], director["id"], row["title"]))
        status, summary, stamp = observed(row, turn, native, forwards.get(row["thread_id"]))
        status, depth = queue_status(status, row["thread_id"], turn, depths, unstarted)
        result["threads"].append({"thread_id": row["thread_id"], "pending_id": row["pending_id"],
                                  "title": title, "status": status, "summary": summary,
                                  "updated_at": datetime.fromtimestamp(stamp, timezone.utc).isoformat()})
        if depth is not None and row["thread_id"]:
            result["threads"][-1]["queued_count"] = depth
        if can_change and (turn_id := status_turn(status, turn, native, depth)):
            result["threads"][-1]["status_turn_id"] = turn_id
        if row["thread_id"] in forwards:
            result["threads"][-1]["latest_assignment"] = forwards[row["thread_id"]][1]
    # Keep the fallback labels current for existing panels. A rename is not task activity.
    if director_title != director["title"] or renamed_workers:
        with write_registry() as db:
            if director_title != director["title"]:
                db.execute("UPDATE directors SET title=? WHERE id=? AND title=?",
                           (director_title, director["id"], director["title"]))
            db.executemany("UPDATE workers SET title=? WHERE thread_id=? AND director=? AND title=?", renamed_workers)
    return result


def observations(rows):
    try:
        connection = readonly(home() / "thread_history_1.sqlite")
    except sqlite3.Error:
        connection = nullcontext()
    with connection as history:
        for row in rows:
            turn = None
            if row["thread_id"] and history:
                try:
                    turn = latest_turn(history, row["thread_id"])
                except sqlite3.Error:
                    history = None
            yield row, turn


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["init", "track", "update", "show", "setup", "candidates", "adopt", "invocation"])
    parser.add_argument("payload", nargs="?")
    parser.add_argument("--stdin", action="store_true", help="从标准输入读取 UTF-8 标题或 JSON")
    parser.add_argument("--alongside", action="store_true", help="用户明确选择另设独立总讨论")
    args = parser.parse_args()
    if args.alongside and args.action != "init":
        parser.error("--alongside 仅用于 init")
    if args.stdin and (args.payload is not None or args.action not in ("init", "track", "update", "adopt")):
        parser.error("--stdin 仅用于 init、track、update 或 adopt，且不能和位置参数一起使用。")
    raw = sys.stdin.buffer.read().decode("utf-8") if args.stdin else args.payload
    actor = uuid_text(os.environ.get("CODEX_THREAD_ID"))
    if args.action == "invocation":
        import panel_onboarding
        result = {"explicit": panel_onboarding.explicit_reference(actor, current_turn(actor))}
    elif args.action in ("setup", "candidates", "adopt"):
        import panel_onboarding
        if args.action == "adopt":
            result = panel_onboarding.adopt(actor, **json.loads(raw or "{}"))
        else:
            with readonly(panel_db()) if panel_db().is_file() else nullcontext() as db:
                result = panel_onboarding.scope(actor, db, candidates=args.action == "candidates")
    elif args.action == "show":
        result = snapshot(actor)
    elif args.action == "init":
        result = initialize(actor, raw, alongside=args.alongside)
    else:
        payload = json.loads(raw or "{}")
        if not isinstance(payload, dict):
            raise ValueError("参数应为 JSON 对象。")
        result = (track if args.action == "track" else update)(actor, **payload)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, TypeError, OSError, sqlite3.Error) as error:
        sys.exit(str(error))
