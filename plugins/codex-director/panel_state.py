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
                     AND json_extract(i.item_json,'$.phase')='final_answer') AS delivered
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


def initialize(actor, title):
    actor, title = uuid_text(actor), label(title, 240)
    local_thread(actor)
    with write_registry() as db:
        if db.execute("SELECT 1 FROM workers WHERE thread_id=?", (actor,)).fetchone():
            raise ValueError("已登记的执行串不能成为新的项目总线程。")
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
          AND json_extract(item_json,'$.server')='codex_app'
          AND json_extract(item_json,'$.tool')=?
          AND json_extract(item_json,'$.status')='completed'
          AND json_extract(item_json,'$.error') IS NULL
          AND coalesce(json_extract(item_json,'$.result.isError'),0)=0
          AND json_extract(item_json,'$.result.content[0].type')='text'
        ORDER BY rollout_ordinal DESC""", (actor, turn_id, turn_id, tool))


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
        if tool == "send_message_to_thread" and (args.get("threadId") != result.get("threadId")
                                                 or args.get("hostId", "local") != "local"):
            continue
        yield args, result, sent_ms


def forward_receipts(actor):
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


def latest_forwards(actor, target=None):
    # A marked message assigns work. An older unmarked send needs explicit track(target).
    forwards = {}
    for thread, sent, subject in forward_receipts(actor):
        if (target is None and subject) or target == thread:
            forwards.setdefault(thread, (sent, subject))
            if target is not None:
                break
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


def update(actor, *, status, summary, thread_id=None, pending_id=None):
    actor, summary = uuid_text(actor), label(summary)
    if status not in ("preparing", "running", "waiting", "review", "completed", "blocked", "archived"):
        raise ValueError("无效的执行串状态。")
    with write_registry() as db:
        director = db.execute("SELECT 1 FROM directors WHERE id=?", (actor,)).fetchone()
        if director:
            thread_id, pending_id = handles(thread_id, pending_id)
            row = find_worker(db, actor, thread_id, pending_id)
        else:
            if pending_id is not None or thread_id not in (None, actor) or status in ("completed", "archived", "preparing"):
                raise ValueError("执行串只能报告自己的进展，结果由总线程确认。")
            row = db.execute("SELECT rowid,* FROM workers WHERE thread_id=?", (actor,)).fetchone()
        if not row:
            raise ValueError("该执行串尚未登记。")
        if not row["thread_id"] and status not in ("preparing", "blocked"):
            raise ValueError("请先补全真实聊天 ID。")
        if row["thread_id"] and status == "preparing":
            raise ValueError("该执行串已经创建。")
        turn = current_turn(row["thread_id"])
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
    return snapshot(actor)


def observed(row, turn, native):
    status, summary, updated = row["status"], row["summary"], row["updated"]
    if native and native["archived"]:
        return "archived", summary, native["archived_at"] or updated
    if not turn:
        return status, summary, updated
    # The previous turn can still be the newest one while the forwarded prompt is queued.
    if row["turn_id"] is None and turn["started_at"] < int(updated):
        return status, summary, updated
    new_turn = row["turn_id"] != turn["turn_id"]
    if not new_turn and status != "running":
        return status, summary, updated
    if turn["status"] == "inProgress" and new_turn:
        if status == "running" and not row["turn_id"]:
            return status, summary, updated
        return "running", "原串已收到新的追问", turn["started_at"]
    if turn["status"] in ("failed", "interrupted"):
        return "blocked", "本轮执行失败" if turn["status"] == "failed" else "本轮已中断", turn["completed_at"] or updated
    if turn["status"] == "completed":
        if turn["delivered"]:
            return "review", "执行串已交付，待总线程确认", turn["completed_at"] or updated
        return "blocked", "本轮已结束，尚无已交付的答复", turn["completed_at"] or updated
    return status, summary, updated


def sync_forwards(owner, rows):
    stamps = {row["thread_id"]: row["updated"] for row in rows}
    try:
        forwards = latest_forwards(owner)
    except sqlite3.OperationalError:
        return False  # The explicit registry still works when host history is unavailable.
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
    workers = {r["thread_id"]: r["pending_id"] for r in rows if r["thread_id"]}
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

    if role == "director" and sync_forwards(director["id"], rows):
        with readonly(panel_db()) as db:
            rows = db.execute("SELECT * FROM workers WHERE director=? ORDER BY rowid", (director["id"],)).fetchall()
    native_by_id = native_threads([director["id"], *(r["thread_id"] for r in rows if r["thread_id"])])
    director_title = display_title(native_by_id.get(director["id"]), director["title"])
    result = {"paired": True, "role": role, "director_id": director["id"],
              "director_title": director_title, "view_key": own_key, "threads": []}
    if role == "director" and include_usage:
        result["token_usage"] = project_usage(director["id"], rows, native_by_id)
    renamed_workers = []
    for row, turn in observations(rows):
        native = native_by_id.get(row["thread_id"])
        title = display_title(native, row["title"])
        if title != row["title"]:
            renamed_workers.append((title, row["thread_id"], director["id"], row["title"]))
        status, summary, stamp = observed(row, turn, native)
        result["threads"].append({"thread_id": row["thread_id"], "pending_id": row["pending_id"],
                                  "title": title, "status": status, "summary": summary,
                                  "updated_at": datetime.fromtimestamp(stamp, timezone.utc).isoformat()})
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
    parser.add_argument("action", choices=["init", "track", "update", "show"])
    parser.add_argument("payload", nargs="?")
    parser.add_argument("--stdin", action="store_true", help="从标准输入读取 UTF-8 标题或 JSON")
    args = parser.parse_args()
    if args.stdin and (args.payload is not None or args.action == "show"):
        parser.error("--stdin 仅用于 init、track 或 update，且不能和位置参数一起使用。")
    raw = sys.stdin.buffer.read().decode("utf-8") if args.stdin else args.payload
    actor = uuid_text(os.environ.get("CODEX_THREAD_ID"))
    if args.action == "show":
        result = snapshot(actor)
    elif args.action == "init":
        result = initialize(actor, raw)
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
