"""Local, host-thread-bound registry for the Director conversation panel."""
import argparse
from contextlib import closing, contextmanager, nullcontext
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
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
MAX_ROLE_LEN = 160
MAX_DECISION_LEN = 240
MAX_DECISIONS = 20
DECISION_ID_RE = re.compile(r"^[0-9a-f]{8}$")


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
        db.execute("""CREATE TABLE IF NOT EXISTS worker_roles(
            director TEXT NOT NULL REFERENCES directors(id), thread_id TEXT NOT NULL,
            role TEXT NOT NULL, updated REAL NOT NULL, PRIMARY KEY(director,thread_id))""")
        db.execute("""CREATE TABLE IF NOT EXISTS project_decisions(
            id TEXT PRIMARY KEY, director TEXT NOT NULL REFERENCES directors(id),
            content TEXT NOT NULL, source_thread_id TEXT, created REAL NOT NULL,
            updated REAL NOT NULL, position INTEGER NOT NULL DEFAULT 0)""")
        first_revision_table = not db.execute("SELECT 1 FROM sqlite_master WHERE name='project_revisions'").fetchone()
        db.execute("""CREATE TABLE IF NOT EXISTS project_revisions(
            director TEXT PRIMARY KEY REFERENCES directors(id), rev INTEGER NOT NULL DEFAULT 0, updated REAL NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS worker_sync(
            director TEXT NOT NULL REFERENCES directors(id), thread_id TEXT NOT NULL,
            seen_rev INTEGER NOT NULL DEFAULT 0, updated REAL NOT NULL, PRIMARY KEY(director,thread_id))""")
        db.execute("""CREATE TABLE IF NOT EXISTS sync_log(
            director TEXT NOT NULL REFERENCES directors(id), rev INTEGER NOT NULL, kind TEXT NOT NULL,
            item_key TEXT NOT NULL, summary TEXT NOT NULL, created REAL NOT NULL, PRIMARY KEY(director,rev))""")
        if first_revision_table:
            # Existing v1.4 notes are the first snapshot; empty projects remain at revision zero.
            db.execute("""INSERT INTO project_revisions SELECT director,1,? FROM
                       (SELECT director FROM worker_roles UNION SELECT director FROM project_decisions)""", (time.time(),))
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
            (SELECT substr(json_extract(i.item_json,'$.text'),1,1024) FROM thread_items i
             WHERE i.thread_id=t.thread_id AND i.turn_id=t.turn_id AND i.item_id=t.final_agent_item_id
               AND i.item_type='agentMessage' AND json_extract(i.item_json,'$.phase')='final_answer') AS final_answer,
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
            yield thread, sent_ms / 1000, subject, sent_ms / 1000

        for args, result, sent_ms in dispatch_receipts(db, actor, "enqueue_task"):
            thread = result["threadId"]
            started = queued_turn(db, thread, result["clientUserMessageId"])
            if started and started["created_at_ms"]:
                subject = args["prompt"].partition("\n")[0][len(DISPATCH_PREFIX):].strip()[:240]
                yield thread, started["created_at_ms"] / 1000, subject, sent_ms / 1000
            elif unstarted is not None:
                unstarted[thread] = max(unstarted.get(thread, 0), sent_ms / 1000)


def latest_forwards(actor, target=None, *, unstarted=None, assignment_times=None):
    # A marked message assigns work. An older unmarked send needs explicit track(target).
    forwards = {}
    for thread, started, subject, sent in forward_receipts(actor, unstarted):
        if (target is None and subject) or target == thread:
            if thread not in forwards or started > forwards[thread][0]:
                forwards[thread] = (started, subject)
                if assignment_times is not None:
                    # A queued prompt cannot contain decisions made while it was waiting.
                    assignment_times[thread] = sent
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


def normalize_text(value, limit, *, allow_empty=False):
    if not isinstance(value, str):
        raise ValueError("内容必须为文本。")
    text = " ".join(value.split())
    if not text and not allow_empty:
        raise ValueError("内容不能为空。")
    if len(text) > limit:
        raise ValueError(f"内容不能超过 {limit} 字。")
    return text


def decision_id_text(value):
    if not isinstance(value, str) or not DECISION_ID_RE.fullmatch(value):
        raise ValueError("无效的决定标识。")
    return value


def _require_director(db, actor, *, check_native=False):
    uuid_text(actor)
    if not db.execute("SELECT 1 FROM directors WHERE id=?", (actor,)).fetchone():
        raise ValueError("只有已登记的总讨论可以修改项目资料。")
    if check_native and local_thread(actor)["archived"]:
        raise ValueError("已归档的总讨论不能修改项目资料。")


def _validate_source_thread(db, director, source_thread_id):
    if source_thread_id in (None, ""):
        return None
    uid = uuid_text(source_thread_id)
    if uid != director and not db.execute("SELECT 1 FROM workers WHERE director=? AND thread_id=?",
                                          (director, uid)).fetchone():
        raise ValueError("来源讨论不属于当前项目。")
    native = native_threads([uid]).get(uid)
    if native and native["archived"]:
        raise ValueError("不能关联已归档的讨论串。")
    return uid


def _bump_rev(db, director, kind, item_key, summary, now):
    db.execute("""INSERT INTO project_revisions VALUES(?,1,?) ON CONFLICT(director)
                  DO UPDATE SET rev=rev+1, updated=excluded.updated""", (director, now))
    rev = db.execute("SELECT rev FROM project_revisions WHERE director=?", (director,)).fetchone()[0]
    db.execute("INSERT INTO sync_log VALUES(?,?,?,?,?,?)", (director, rev, kind, item_key, summary, now))
    db.execute("DELETE FROM sync_log WHERE director=? AND rev<=?", (director, rev - 30))


def _upsert_worker_role(db, director, thread_id, role, now):
    text = normalize_text(role, MAX_ROLE_LEN, allow_empty=True)
    if text:
        change = db.execute("""INSERT INTO worker_roles VALUES(?,?,?,?) ON CONFLICT(director,thread_id)
                      DO UPDATE SET role=excluded.role, updated=excluded.updated
                      WHERE worker_roles.role<>excluded.role""", (director, thread_id, text, now))
    else:
        change = db.execute("DELETE FROM worker_roles WHERE director=? AND thread_id=?", (director, thread_id))
    if change.rowcount:
        title = db.execute("SELECT title FROM workers WHERE director=? AND thread_id=?", (director, thread_id)).fetchone()[0]
        summary = f"分工更新 · {title}：{text}" if text else f"分工移除 · {title}"
        _bump_rev(db, director, "role_upsert" if text else "role_delete", thread_id, summary, now)


def set_worker_role(actor, *, thread_id, role):
    thread_id = uuid_text(thread_id)
    with write_registry() as db:
        _require_director(db, actor)
        if not db.execute("SELECT 1 FROM workers WHERE director=? AND thread_id=?", (actor, thread_id)).fetchone():
            raise ValueError("该执行串尚未登记。")
        _upsert_worker_role(db, actor, thread_id, role, time.time())
    return snapshot(actor)


def save_worker_roles(actor, roles, *, include_usage=True, check_native=True, only_missing=False):
    if not isinstance(roles, list) or len(roles) > 200:
        raise ValueError("分工列表最多包含 200 个执行串。")
    with write_registry() as db:
        _require_director(db, actor, check_native=check_native)
        registered = dict(db.execute("SELECT thread_id,status FROM workers WHERE director=? AND thread_id IS NOT NULL",
                                     (actor,)))
        edits = {}
        for item in roles:
            if not isinstance(item, dict) or set(item) != {"thread_id", "role"}:
                raise ValueError("每条分工须包含 thread_id 和 role。")
            thread = uuid_text(item["thread_id"])
            if thread in edits or thread not in registered:
                raise ValueError("执行串重复或不属于当前总讨论。")
            edits[thread] = item["role"]
        native = native_threads(list(edits))
        now = time.time()
        for thread, role in edits.items():
            if thread not in native or native[thread]["archived"] or registered[thread] == "archived":
                raise ValueError("只能修改已登记、未归档的执行串。")
            if only_missing and db.execute("SELECT 1 FROM worker_roles WHERE director=? AND thread_id=?",
                                           (actor, thread)).fetchone():
                continue
            _upsert_worker_role(db, actor, thread, role, now)
    return snapshot(actor, include_usage=include_usage)


def set_worker_roles(actor, roles, *, only_missing=False):
    if not isinstance(only_missing, bool):
        raise ValueError("only_missing 须为布尔值。")
    return save_worker_roles(actor, roles, include_usage=False, check_native=False, only_missing=only_missing)


def _insert_decision(db, director, text, source, now, position):
    did = secrets.token_hex(4)
    while db.execute("SELECT 1 FROM project_decisions WHERE id=?", (did,)).fetchone():
        did = secrets.token_hex(4)
    db.execute("INSERT INTO project_decisions VALUES(?,?,?,?,?,?,?)", (did, director, text, source, now, now, position))
    _bump_rev(db, director, "decision_upsert", did, "已确认决定：" + text, now)
    return did


def _update_decision(db, director, row, text, source, now):
    if (row["content"], row["source_thread_id"]) == (text, source):
        return False
    db.execute("UPDATE project_decisions SET content=?,source_thread_id=?,updated=? WHERE id=? AND director=?",
               (text, source, now, row["id"], director))
    _bump_rev(db, director, "decision_upsert", row["id"], "已确认决定：" + text, now)
    return True


def upsert_decision(actor, *, content, id=None, source_thread_id=None):
    text = normalize_text(content, MAX_DECISION_LEN)
    with write_registry() as db:
        _require_director(db, actor)
        source = _validate_source_thread(db, actor, source_thread_id)
        now = time.time()
        if id is None:
            count, position = db.execute("SELECT count(*),coalesce(max(position),-1)+1 FROM project_decisions "
                                         "WHERE director=?", (actor,)).fetchone()
            if count >= MAX_DECISIONS:
                raise ValueError(f"已确认决定最多保留 {MAX_DECISIONS} 条，请先删除过期决定。")
            _insert_decision(db, actor, text, source, now, position)
        else:
            did = decision_id_text(id)
            row = db.execute("SELECT id,content,source_thread_id FROM project_decisions WHERE id=? AND director=?",
                             (did, actor)).fetchone()
            if not row:
                raise ValueError("未找到对应的已确认决定。")
            _update_decision(db, actor, row, text, source, now)
    return snapshot(actor)


def delete_decision(actor, *, id):
    did = decision_id_text(id)
    with write_registry() as db:
        _require_director(db, actor)
        old = db.execute("SELECT content FROM project_decisions WHERE id=? AND director=?", (did, actor)).fetchone()
        if not old:
            raise ValueError("未找到对应的已确认决定。")
        db.execute("DELETE FROM project_decisions WHERE id=? AND director=?", (did, actor))
        _bump_rev(db, actor, "decision_delete", did, f"原决定「{old[0][:80]}」已废止", time.time())
    return snapshot(actor)


def track(actor, *, title, thread_id=None, pending_id=None, summary=None, role=None):
    actor, title = uuid_text(actor), label(title, 240)
    thread_id, pending_id = handles(thread_id, pending_id)
    if role is not None and thread_id is None:
        raise ValueError("补全正式聊天 ID 后才能登记长期分工。")
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
        if role is not None:
            _upsert_worker_role(db, actor, thread_id, role, time.time())
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


def request_body(request):
    request = (request or "").strip()
    if request.startswith("<codex_delegation>"):
        request = unescape(request.partition("<input>")[2].partition("</input>")[0].strip())
    return request


def task_excerpt(request):
    request = request_body(request)
    line = request.splitlines()[0] if request else ""
    return line.removeprefix(DISPATCH_PREFIX).strip()[:240]


RETURN_LINK = re.compile(r"(?m)^[ \t]*(?:[←↩]\s*)?\[(?:[←↩]\s*)?返回(?:项目)?总讨论\]"
                         r"\(<?codex://threads/[0-9a-fA-F-]+>?\)[ \t]*\Z")


def reply_excerpt(text, limit=180):
    text = RETURN_LINK.sub("", (text or "").rstrip())
    lines = []
    for line in text.splitlines():
        line = re.sub(r"^(?:#{1,6}\s+|>\s*|[-*]\s+)+", "", line.strip())
        line = re.sub(r"(\*\*|`+)(.+?)\1", r"\2", line).strip()
        if line:
            lines.append(line)
        if len(lines) == 2:
            break
    return " ".join(" ".join(lines).split())[:limit]


def observed(row, turn, native, forward=None):
    status, summary, stamp = _observed_status(row, turn, native, forward)
    if turn and (status == "review" or (status == "waiting" and summary in ("", task_excerpt(turn["request"])))):
        summary = reply_excerpt(turn["final_answer"]) or summary
    return status, summary, stamp


def _observed_status(row, turn, native, forward=None):
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
                for thread, sent, subject, _ in forward_receipts(owner):
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


def project_notes(db, director):
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    roles, decisions = {}, []
    if "worker_roles" in tables:
        roles = dict(db.execute("SELECT thread_id,role FROM worker_roles WHERE director=?", (director,)))
    if "project_decisions" in tables:
        decisions = db.execute("SELECT * FROM project_decisions WHERE director=? ORDER BY position,created",
                               (director,)).fetchall()
    return roles, decisions


def sync_context_for_worker(actor):
    actor = uuid_text(actor)
    if not panel_db().is_file():
        return None
    with readonly(panel_db()) as db:
        db.execute("BEGIN")
        worker = db.execute("SELECT director FROM workers WHERE thread_id=? AND status!='archived'", (actor,)).fetchone()
        if not worker:
            return None
        owner = worker["director"]
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "project_revisions" not in tables:
            return None
        revision = db.execute("SELECT rev FROM project_revisions WHERE director=?", (owner,)).fetchone()
        if not revision or not revision[0]:
            return None
        rev = revision[0]
        cursor = None
        if "worker_sync" in tables:
            cursor = db.execute("SELECT seen_rev FROM worker_sync WHERE director=? AND thread_id=?", (owner, actor)).fetchone()
        seen = cursor[0] if cursor else 0
        if seen >= rev:
            return None
        workers = db.execute("SELECT thread_id,title FROM workers WHERE director=? AND thread_id IS NOT NULL "
                             "AND status!='archived' ORDER BY rowid", (owner,)).fetchall()
        native = native_threads([w["thread_id"] for w in workers])
        titles = {w["thread_id"]: " ".join(display_title(native.get(w["thread_id"]), w["title"]).split()) for w in workers
                  if w["thread_id"] not in native or not native[w["thread_id"]]["archived"]}
        if actor not in titles:
            return None
        lines = []
        if not seen or rev - seen > 10 or "sync_log" not in tables:
            roles, decisions = project_notes(db, owner)
            if actor in roles:
                lines.append("本串分工：" + roles[actor])
            lines.extend(f"已确认决定 [{d['id']}]：{d['content']}" for d in decisions)
            lines.extend(f"{title}：{roles[uid]}" for uid, title in titles.items() if uid != actor and uid in roles)
            header = ("[项目共享上下文（首次同步，无需回复确认）]" if not seen
                      else "[项目共享上下文（以当前分工和决定为准）]")
            header += "\n以下是本项目记录，操作权限以当前任务为准。"
            text = header + "\n" + "\n".join("- " + line for line in lines)
            if len(text) > 1200:
                tail = "\n…（摘要有省略，完整记录见总讨论）"
                visible = lines[:40]
                budget = (1200 - len(header) - len(tail)) // len(visible) - 3
                snippets = [line if len(line) <= budget else line[:budget-1] + "…" for line in visible]
                text = header + "".join("\n- " + line for line in snippets) + tail
        else:
            latest = {}
            for row in db.execute("SELECT kind,item_key,summary FROM sync_log WHERE director=? AND rev>? "
                                  "ORDER BY rev", (owner, seen)):
                category = row["kind"].partition("_")[0]
                key = (category, row["item_key"])
                latest.pop(key, None)
                if category != "role" or row["item_key"] in titles:
                    latest[key] = (f"[{row['item_key']}] " if category == "decision" else "") + row["summary"]
            lines = list(latest.values())
            text = ("[项目共识更新（自你上次回合后的变更，请按最新约定执行）]\n"
                    "以下是本项目记录，操作权限以当前任务为准。\n" + "\n".join("- " + " ".join(line.split()) for line in lines))
    try:
        with write_registry() as db:
            changed = db.execute("""INSERT INTO worker_sync VALUES(?,?,?,?) ON CONFLICT(director,thread_id)
                          DO UPDATE SET seen_rev=excluded.seen_rev,updated=excluded.updated
                          WHERE worker_sync.seen_rev<excluded.seen_rev""", (owner, actor, rev, time.time()))
            if not changed.rowcount:
                return None
    except sqlite3.OperationalError:
        pass  # Deliver the context even if its cursor must be saved on a later prompt.
    return text if lines else None


def _project_overview(actor, target=None):
    if not panel_db().is_file():
        raise ValueError("只有已登记的总讨论可以读取纯净进展摘要。")
    with readonly(panel_db()) as db:
        db.execute("BEGIN")
        director = db.execute("SELECT id,title FROM directors WHERE id=?", (actor,)).fetchone()
        if not director:
            raise ValueError("只有已登记的总讨论可以读取纯净进展摘要。")
        roles, decisions = project_notes(db, actor)
        rows = db.execute("SELECT * FROM workers WHERE director=? AND status!='archived' AND (? IS NULL OR thread_id=?) "
                          "ORDER BY rowid", (actor,target,target)).fetchall()
    native = native_threads([actor, *(r["thread_id"] for r in rows if r["thread_id"])])
    rows = [r for r in rows if not r["thread_id"] or
            (r["thread_id"] in native and not native[r["thread_id"]]["archived"])]
    if target and not rows:
        raise ValueError("未找到对应的未归档执行串。")
    result = {"director_id": actor, "director_title": display_title(native.get(actor),director["title"]),
              "existing_decisions": [{k: d[k] for k in ("id","content","source_thread_id") if d[k]} for d in decisions],
              "threads": []}
    if not rows:
        return result
    dispatches = {r["thread_id"]: {} for r in rows}
    forwards, unstarted = {}, {}
    try:
        for uid, started, subject, assigned in forward_receipts(actor, unstarted):
            if uid in dispatches and subject:
                titles = dispatches[uid]
                titles[subject] = max(assigned, titles.get(subject, 0))
                if uid not in forwards or started > forwards[uid][0]:
                    forwards[uid] = (started, subject)
    except sqlite3.Error:
        pass
    depths = queue_depths(list(dispatches))
    for row, turn in observations(rows):
        uid = row["thread_id"]
        status, _, stamp = observed(row, turn, native.get(uid), forwards.get(uid))
        status, _ = queue_status(status, uid, turn, depths, unstarted)
        titles = dispatches[uid]
        result["threads"].append({
            "thread_id": uid, "title": display_title(native.get(uid), row["title"]), "status": status,
            "role": roles.get(uid, ""), "recent_dispatches": sorted(titles, key=titles.get, reverse=True)[:3],
            "updated_at": datetime.fromtimestamp(stamp, timezone.utc).isoformat()})
    return result


def director_roster_hint(actor):
    actor = uuid_text(actor)
    try:
        project = _project_overview(actor)
    except ValueError:
        return ""
    rows = project["threads"]
    count = len(project["existing_decisions"])
    if not rows and not count:
        return ""
    labels = {"waiting":"等你回复", "blocked":"受阻", "running":"进行中", "queued":"排队中", "pending":"排队中",
              "preparing":"排队中", "unconfirmed":"排队中", "review":"已回复", "completed":"已完成", "ready":"未派工"}
    lines = ["当前执行串花名册（选串前优先对照，不要先读源码）："]
    for row in rows[:15]:
        title = " ".join(row["title"].split())
        lines.append(f"- {title} [{labels.get(row['status'], '状态待确认')}] ({row['thread_id'] or '正式 ID 待定'})：{row['role'] or '未记分工'}")
    if len(rows) > 15:
        lines.append(f"…另有 {len(rows)-15} 个讨论串（完整列表见 show）")
    if count:
        lines.append(f"后台已记录 {count} 条跨串决定（可用 show / digest 查看）。")
    return "\n".join(lines)


def _digest_text(text, limit):
    text = re.sub(r"(?ms)^ *`{3,}(?:diff|patch)\b[^\n]*\n.*?(?:^ *`{3,}[^\n]*$|\Z)", "", text)
    text = re.split(r"(?m)^diff --git ", text, maxsplit=1)[0]
    return " ".join(text.split())[:limit]


def _digest_turns(db, thread, count, req_limit, reply_limit):
    turns = db.execute("""SELECT t.turn_id,t.status,json_extract(f.item_json,'$.text') AS reply
        FROM thread_turns t LEFT JOIN thread_items f ON f.thread_id=t.thread_id AND f.turn_id=t.turn_id
            AND t.status='completed' AND f.item_id=t.final_agent_item_id AND f.item_type='agentMessage'
            AND json_extract(f.item_json,'$.phase')='final_answer'
        WHERE t.thread_id=? AND t.started_at IS NOT NULL ORDER BY t.rollout_ordinal DESC LIMIT ?""", (thread,count))
    results = []
    for turn in turns:
        inputs = db.execute("""SELECT CASE WHEN i.item_type='userMessage' THEN (
              SELECT group_concat(json_extract(p.value,'$.text'),' ') FROM json_each(i.item_json,'$.content') p
              WHERE json_type(p.value,'$.text')='text')
            ELSE json_extract(i.item_json,'$.output') END AS request
            FROM thread_items i WHERE i.thread_id=? AND i.turn_id=? AND (i.item_type='userMessage'
            OR (i.item_type='functionCallOutput' AND json_extract(i.item_json,'$.namespace')='codex_app'
                AND json_extract(i.item_json,'$.name') IN ('create_thread','send_message_to_thread')
                AND json_extract(i.item_json,'$.output') LIKE '<codex_delegation>%'))
            ORDER BY i.rollout_ordinal""", (thread, turn["turn_id"]))
        request = next((body for r in inputs if (body := request_body(r["request"]).removeprefix(DISPATCH_PREFIX).strip())), "")
        reply = RETURN_LINK.sub("", (turn["reply"] or "").rstrip())
        results.append({"turn_id": turn["turn_id"], "status": turn["status"],
                        "request": _digest_text(request, req_limit), "reply": _digest_text(reply, reply_limit)})
    return results


def digest(actor, *, all_threads=False, thread_id=None, turns=None):
    actor = uuid_text(actor)
    target = uuid_text(thread_id) if thread_id is not None else None
    maximum = 5 if target else 3
    count = turns if turns is not None else (3 if target else 1)
    if not isinstance(count, int) or count < 1:
        raise ValueError("回合数须为正整数。")
    result = _project_overview(actor, target)
    result["threads"] = [r for r in result["threads"] if r["thread_id"] and
                         (target or all_threads or r["status"] in ("waiting","blocked","review","running"))]
    for row in result["threads"]:
        row["turns"] = []
    try:
        with readonly(home() / "thread_history_1.sqlite") as history:
            history.execute("BEGIN")
            for row in result["threads"]:
                row["turns"] = _digest_turns(history, row["thread_id"], min(count, maximum),
                                              400 if target else 240, 800 if target else 400)
    except sqlite3.Error:
        pass
    return result


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
            roles_by_thread, decision_rows = project_notes(db, director["id"])
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

    forwards, unstarted, assignment_times = {}, {}, {}
    dispatch_read = False
    if role == "director":
        try:
            forwards = latest_forwards(director["id"], unstarted=unstarted, assignment_times=assignment_times)
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
        if role == "director" and row["thread_id"] in roles_by_thread:
            result["threads"][-1]["role"] = roles_by_thread[row["thread_id"]]
        if row["thread_id"] in forwards:
            _, subject = forwards[row["thread_id"]]
            sent = assignment_times[row["thread_id"]]
            result["threads"][-1]["latest_assignment"] = subject
            result["threads"][-1]["latest_assignment_at"] = datetime.fromtimestamp(sent, timezone.utc).isoformat()
    if role == "director":
        result["decisions"] = []
        titles = {row["thread_id"]: row["title"] for row in result["threads"]}
        titles[director["id"]] = director_title
        for decision in decision_rows:
            item = {"id": decision["id"], "content": decision["content"],
                    "updated_at": datetime.fromtimestamp(decision["updated"], timezone.utc).isoformat()}
            sid = decision["source_thread_id"]
            if sid:
                item.update(source_thread_id=sid, source_title=titles.get(sid, "来源讨论"))
                if sid in native_by_id and native_by_id[sid]["archived"]:
                    item["source_archived"] = True
            result["decisions"].append(item)
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
    parser.add_argument("action", choices=["init", "track", "update", "show", "setup", "candidates", "adopt", "invocation", "role", "roles", "decision", "digest"])
    parser.add_argument("payload", nargs="?")
    parser.add_argument("--stdin", action="store_true", help="从标准输入读取 UTF-8 标题或 JSON")
    parser.add_argument("--alongside", action="store_true", help="用户明确选择另设独立总讨论")
    parser.add_argument("--all", action="store_true", help="读取全部未归档执行串摘要（仅用于 digest）")
    parser.add_argument("--thread", help="仅读取指定执行串摘要（仅用于 digest）")
    parser.add_argument("--turns", type=int, help="每串最近回合数（仅用于 digest）")
    args = parser.parse_args()
    if (args.all or args.thread is not None or args.turns is not None) and args.action != "digest":
        parser.error("--all、--thread、--turns 仅用于 digest")
    if args.action == "digest" and args.payload is not None:
        parser.error("digest 不接受位置参数")
    if args.alongside and args.action != "init":
        parser.error("--alongside 仅用于 init")
    if args.stdin and (args.payload is not None or args.action not in ("init", "track", "update", "adopt", "role", "roles", "decision")):
        parser.error("--stdin 仅用于 init、track、update、adopt、role、roles 或 decision，且不能和位置参数一起使用。")
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
    elif args.action == "digest":
        result = digest(actor, all_threads=args.all, thread_id=args.thread, turns=args.turns)
    elif args.action == "roles":
        payload = json.loads(raw or "null")
        if isinstance(payload, dict):
            result = set_worker_roles(actor, payload.get("roles"), only_missing=payload.get("only_missing", False))
        else:
            result = set_worker_roles(actor, payload)
    elif args.action == "init":
        result = initialize(actor, raw, alongside=args.alongside)
    else:
        payload = json.loads(raw or "{}")
        if not isinstance(payload, dict):
            raise ValueError("参数应为 JSON 对象。")
        if args.action == "decision":
            op = payload.pop("action", "upsert")
            if op not in ("upsert", "delete"):
                raise ValueError("decision 的 action 仅支持 upsert 或 delete。")
            command = upsert_decision if op == "upsert" else delete_decision
        else:
            command = {"track": track, "update": update, "role": set_worker_role}[args.action]
        result = command(actor, **payload)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, TypeError, OSError, sqlite3.Error) as error:
        sys.exit(str(error))
