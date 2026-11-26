"""Regression test for project isolation, pending registration and the worker lifecycle."""
from contextlib import closing
import json
from os import environ
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "codex-director"))
import panel_state as state
import panel_server
import panel_onboarding


def create_indexes(directory, threads):
    with closing(sqlite3.connect(Path(directory) / "state_5.sqlite")) as host, host:
        host.execute("CREATE TABLE threads(id PRIMARY KEY, thread_source, source, archived, archived_at, title)")
        host.executemany("INSERT INTO threads VALUES(?, ?, 'vscode', 0, NULL, ?)", threads)
    with closing(sqlite3.connect(Path(directory) / "thread_history_1.sqlite")) as history, history:
        history.execute("""CREATE TABLE thread_turns(thread_id, turn_id, status, started_at,
                        completed_at, rollout_ordinal, final_agent_item_id)""")
        history.execute("""CREATE TABLE thread_items(thread_id, turn_id, item_id, item_type, item_json,
                        rollout_ordinal, created_at_ms, started_at_ms, completed_at_ms)""")


class PanelLifecycle(unittest.TestCase):
    def test_worker_reply_footer(self):
        director, worker, ordinary = (str(uuid4()) for _ in range(3))
        script = Path(state.__file__).with_name("worker_reply.py")
        with tempfile.TemporaryDirectory() as directory, patch.dict(environ, CODEX_HOME=directory):
            with state.write_registry() as db:
                db.execute("INSERT INTO directors VALUES(?, 'Project', 'main-key')", (director,))
                db.execute("""INSERT INTO workers(director, thread_id, view_key, title, status, summary, updated)
                              VALUES(?, ?, 'worker-key', 'Task', 'completed', 'Done', 1)""", (director, worker))
            for actor in (worker, director, ordinary):
                event = {"hook_event_name": "UserPromptSubmit", "session_id": actor, "prompt": "Continue"}
                output = subprocess.check_output([sys.executable, "-B", str(script)],
                                                 input=json.dumps(event), encoding="utf-8")
                if actor != ordinary:
                    footer = (f"[← 返回总讨论](codex://threads/{director})" if actor == worker
                              else f"[打开项目讨论串]({state.PANEL_LINK})")
                    context = json.loads(output)["hookSpecificOutput"]["additionalContext"]
                    self.assertEqual(context.splitlines()[-1], footer)
                else:
                    self.assertEqual(output, "")

    def test_inline_receipt_waits_for_idle_and_matches_the_original_dispatch(self):
        owner, worker, dispatch, followup, response = [str(uuid4()) for _ in range(5)]
        prompt = "【Director 派工】核对修改稿"
        envelope = f"<codex_delegation>\n  <source_thread_id>{owner}</source_thread_id>\n  <input>{prompt}</input>\n</codex_delegation>"
        with tempfile.TemporaryDirectory() as directory, patch.dict(environ, CODEX_HOME=directory):
            create_indexes(directory, [(owner, "user", "总讨论"), (worker, "agent_created_thread", "审核串")])
            with state.write_registry() as db:
                db.execute("INSERT INTO directors VALUES(?, '总讨论', 'main')", (owner,))
                db.execute("INSERT INTO workers VALUES(?,?,NULL,'worker','审核串','running','',0,NULL)", (owner, worker))
            with closing(sqlite3.connect(Path(directory) / "thread_history_1.sqlite")) as db:
                def turn(thread, turn_id, status, started, ended, final=None):
                    db.execute("INSERT INTO thread_turns VALUES(?,?,?,?,?,?,?)",
                               (thread, turn_id, status, started, ended, started, final))

                def item(thread, turn_id, item_id, kind, fields, ms):
                    db.execute("INSERT INTO thread_items VALUES(?,?,?,?,?,?,?,?,?)",
                               (thread, turn_id, item_id, kind, json.dumps(fields), ms, ms, ms, ms))

                turn(owner, dispatch, "inProgress", 3, None)
                item(owner, dispatch, "sent", "mcpToolCall", {
                    "server": "codex_app", "tool": "send_message_to_thread", "status": "completed",
                    "arguments": json.dumps({"threadId": worker, "prompt": prompt}),
                    "result": {"content": [{"type": "text", "text": json.dumps({"threadId": worker})}]}
                }, 3001)
                turn(worker, "old", "completed", 1, 2, "old-final")
                item(worker, "old", "old-final", "agentMessage", {"phase": "final_answer", "text": "旧答案"}, 2000)
                db.commit()
                show = {"name": "show_receipt", "arguments": {"view_key": "main"}, "_meta": {"threadId": owner}}
                seed = panel_server.call(show)["structuredContent"]
                self.assertEqual(seed["receipt_turn"], dispatch)
                read = {**show, "name": "snapshot", "arguments": {"view_key": "main", "receipt_turn": dispatch}}
                self.assertTrue(panel_server.call({**read, "_meta": {"threadId": worker}})["isError"])
                def status():
                    return panel_server.call(read)["structuredContent"]["threads"][0]["status"]
                self.assertEqual(status(), "running")
                turn(worker, response, "completed", 4, 6, "answer")
                item(worker, response, "incoming", "functionCallOutput", {
                    "namespace": "codex_app", "name": "send_message_to_thread", "output": envelope}, 4000)
                item(worker, response, "answer", "agentMessage", {"phase": "final_answer", "text": "本轮答复"}, 6000)
                db.execute("UPDATE thread_turns SET status='completed',completed_at=4 WHERE turn_id=?", (dispatch,))
                turn(owner, followup, "inProgress", 5, None)
                turn(worker, str(uuid4()), "inProgress", 7, None)
                db.commit()
                self.assertEqual(status(), "running")
                db.execute("UPDATE thread_turns SET status='completed',completed_at=8 WHERE turn_id=?", (followup,))
                db.commit()
                final = panel_server.call(read)["structuredContent"]
                self.assertTrue(final["finished"])
                self.assertEqual((final["threads"][0]["thread_id"], final["threads"][0]["status"]), (worker, "review"))
                self.assertEqual(panel_server.call(read)["structuredContent"], final)

    def test_queued_task_matches_only_its_new_worker_turn(self):
        owner, worker, dispatch, old, new = [str(uuid4()) for _ in range(5)]
        prompt = "【Director 派工】独立任务 B"
        with tempfile.TemporaryDirectory() as directory, patch.dict(environ, CODEX_HOME=directory):
            create_indexes(directory, [(owner, "user", "总讨论"), (worker, "user", "执行串")])
            with state.write_registry() as registry:
                registry.execute("INSERT INTO directors VALUES(?, '总讨论', 'main')", (owner,))
                registry.execute("INSERT INTO workers VALUES(?,?,NULL,'worker','执行串','running','A',0,?)", (owner, worker, old))
            with closing(sqlite3.connect(Path(directory) / "thread_history_1.sqlite")) as db:
                db.execute("INSERT INTO thread_turns VALUES(?,?,'inProgress',1,NULL,1,NULL)", (owner, dispatch))
                db.execute("INSERT INTO thread_turns VALUES(?,?,'inProgress',1,NULL,1,NULL)", (worker, old))
                db.commit()
                args = {"threadId": worker, "prompt": prompt}
                call = {"name": "enqueue_task", "arguments": args, "_meta": {"threadId": owner}}
                queue_id = str(uuid4())
                with patch.object(panel_server.native_queue, "submit",
                                  side_effect=lambda cli, target, key, text: {"clientUserMessageId": key, "id": queue_id}) as submit, \
                        patch.dict(environ, CODEX_APP_RUNTIME_CLI_PATH=sys.executable):
                    self.assertTrue(panel_server.call({**call, "_meta": {}})["isError"])
                    self.assertTrue(panel_server.call({**call, "_meta": {"threadId": worker}})["isError"])
                    reply = panel_server.call(call)
                    submit.assert_called_once()
                result = reply["structuredContent"]
                self.assertEqual(result["queuedSubmissionId"], queue_id)
                db.execute("INSERT INTO thread_items VALUES(?,?,'q','mcpToolCall',?,2,2000,2000,2000)",
                           (owner, dispatch, json.dumps({"server": "director-panel", "pluginId": "codex-director@director-local",
                            "tool": "enqueue_task", "status": "completed", "arguments": json.dumps(args), "result": reply})))
                db.execute("UPDATE thread_turns SET status='completed',completed_at=3 WHERE turn_id=?", (dispatch,))
                db.commit()
                read = {"name": "snapshot", "_meta": {"threadId": owner},
                        "arguments": {"receipt_turn": dispatch, "view_key": "main"}}
                with patch.object(panel_server.native_queue, "pending", return_value=True):
                    self.assertEqual(panel_server.call(read)["structuredContent"]["threads"][0]["status"], "queued")
                db.execute("UPDATE thread_turns SET status='completed',completed_at=4 WHERE turn_id=?", (old,))
                self.assertFalse(state.latest_forwards(owner))
                db.execute("UPDATE thread_turns SET final_agent_item_id='old-answer' WHERE turn_id=?", (old,))
                db.execute("INSERT INTO thread_items VALUES(?,?,'old-answer','agentMessage',?,4,4000,4000,4000)",
                           (worker, old, json.dumps({"phase": "final_answer", "text": "A 的答复"})))
                db.commit()
                self.assertEqual(state.snapshot(owner)["threads"][0]["status"], "unconfirmed")
                db.execute("INSERT INTO thread_turns VALUES(?,?,'completed',5,6,2,'answer')", (worker, new))
                db.execute("INSERT INTO thread_items VALUES(?,?,'input','userMessage',?,3,5000,5000,5000)",
                           (worker, new, json.dumps({"clientId": result["clientUserMessageId"]})))
                db.execute("INSERT INTO thread_items VALUES(?,?,'answer','agentMessage',?,4,6000,6000,6000)",
                           (worker, new, json.dumps({"phase": "final_answer", "text": "B 的答复"})))
                db.commit()
                self.assertEqual(state.latest_forwards(owner)[worker], (5, "独立任务 B"))
                self.assertEqual(panel_server.call(read)["structuredContent"]["threads"][0]["status"], "review")

    def test_manual_status_changes_only_the_current_idle_worker_turn(self):
        owner, other, worker, first, new = [str(uuid4()) for _ in range(5)]
        with tempfile.TemporaryDirectory() as directory, patch.dict(environ, CODEX_HOME=directory):
            create_indexes(directory, [(uid, "user", uid) for uid in (owner, other, worker)])
            queue_path = Path(directory) / "queue_1.sqlite"
            with closing(sqlite3.connect(queue_path)) as queue, queue:
                queue.execute("CREATE TABLE queued_items(thread_id, id)")
            with state.write_registry() as registry:
                registry.executemany("INSERT INTO directors VALUES(?,?,?)",
                                     [(owner, "总讨论", "owner-key"), (other, "其他总讨论", "other-key")])
                registry.execute("INSERT INTO workers VALUES(?,?,NULL,'worker-key','工作','running','已核对两处定义',2,?)",
                                 (owner, worker, first))
            history_path = Path(directory) / "thread_history_1.sqlite"
            with closing(sqlite3.connect(history_path)) as history, history:
                history.execute("INSERT INTO thread_turns VALUES(?,?,'completed',1,2,1,'answer')", (worker, first))
                history.execute("INSERT INTO thread_items VALUES(?,?,'answer','agentMessage',?,1,2000,2000,2000)",
                                (worker, first, json.dumps({"phase": "final_answer", "text": "本轮答复"})))

            def action(status, actor=owner, turn=first, **meta):
                return panel_server.call({"name": "set_thread_status",
                    "arguments": {"thread_id": worker, "expected_turn_id": turn, "status": status},
                    "_meta": {"threadId": actor, **meta} if actor else {}})

            def current():
                return state.snapshot(owner)["threads"][0]

            self.assertEqual((current()["status_turn_id"], current()["summary"]), (first, "已核对两处定义"))
            self.assertNotIn("status_turn_id", state.snapshot(view_key="owner-key")["threads"][0])
            self.assertNotIn("status_turn_id", state.snapshot(worker)["threads"][0])
            for actor in (None, worker, other):
                self.assertTrue(action("completed", actor)["isError"])
            self.assertTrue(action("completed", hostId="ssh-test")["isError"])
            self.assertEqual(action("completed")["structuredContent"]["status"], "completed")
            self.assertEqual((current()["status"], current()["summary"]), ("completed", "已核对两处定义"))
            with self.assertRaises(ValueError):
                state.update(worker, status="review", summary="补交说明")

            with closing(sqlite3.connect(queue_path)) as queue, queue:
                queue.execute("INSERT INTO queued_items VALUES(?,'queued')", (worker,))
            self.assertEqual(current()["status"], "queued")
            self.assertTrue(action("review")["isError"])
            with closing(sqlite3.connect(queue_path)) as queue, queue:
                queue.execute("DELETE FROM queued_items")
            self.assertEqual(action("review")["structuredContent"]["status"], "review")
            self.assertEqual((current()["status"], current()["summary"]), ("review", "已核对两处定义"))
            self.assertEqual(action("completed")["structuredContent"]["status"], "completed")
            with closing(sqlite3.connect(history_path)) as history, history:
                history.execute("INSERT INTO thread_turns VALUES(?,?,'inProgress',3,NULL,2,NULL)", (worker, new))
                history.execute("""INSERT INTO thread_items(thread_id,turn_id,item_id,item_type,item_json)
                                   VALUES(?,?,'question','userMessage',?)""",
                                (worker, new, json.dumps({"content": [{"text": "再检查第三处定义\n附录供参考"}]})))
            self.assertEqual((current()["status"], current()["summary"]), ("running", "再检查第三处定义"))
            self.assertTrue(action("review")["isError"])
            self.assertTrue(action("completed", turn=new)["isError"])
            with closing(sqlite3.connect(history_path)) as history, history:
                history.execute("UPDATE thread_turns SET status='completed',completed_at=4,final_agent_item_id='new-answer' WHERE turn_id=?", (new,))
                history.execute("""INSERT INTO thread_items(thread_id,turn_id,item_id,item_type,item_json)
                                   VALUES(?,?,'new-answer','agentMessage','{"phase":"final_answer","text":"新的答复"}')""",
                                (worker, new))
            self.assertEqual((current()["status"], current()["summary"]), ("review", "再检查第三处定义"))
            with state.write_registry() as registry:
                registry.execute("UPDATE workers SET status='running',summary='上一轮进展',updated=2.5,turn_id=NULL")
            self.assertEqual((current()["status"], current()["summary"]), ("review", "再检查第三处定义"))
            self.assertEqual(action("completed", turn=new)["structuredContent"]["status"], "completed")
            self.assertEqual(action("review", turn=new)["structuredContent"]["status"], "review")
            self.assertEqual(current()["summary"], "再检查第三处定义")

    def test_select_existing_project_chat_without_dispatch(self):
        owner, worker, other, outside = [str(uuid4()) for _ in range(4)]
        with tempfile.TemporaryDirectory() as directory, patch.dict(environ, CODEX_HOME=directory):
            create_indexes(directory, [(uid, "user", uid) for uid in (owner, worker, other, outside)])
            state.initialize(owner, owner)
            with closing(sqlite3.connect(Path(directory) / "state_5.sqlite")) as db, db:
                db.execute("ALTER TABLE threads ADD COLUMN project_id TEXT")
                db.execute("UPDATE threads SET project_id=CASE WHEN id=? THEN 'other' ELSE 'project' END", (outside,))
            with self.assertRaisesRegex(ValueError, "已有总讨论"):
                state.initialize(other, other)
            state.initialize(outside, outside)
            with closing(sqlite3.connect(Path(directory) / "thread_history_1.sqlite")) as db, db:
                db.execute("INSERT INTO thread_turns VALUES(?, 'onboard','inProgress',1,NULL,1,NULL)", (owner,))
                for index, (cursor, following, ids) in enumerate([(None, "p2", [owner, other]), ("p2", None, [worker, outside])]):
                    args = {"mode": "history", "hostId": "local", "archived": False, "cursor": cursor}
                    content = {"threads": [{"id": uid, "title": uid, "kind": "codex", "hostId": "local",
                                             "projectId": "other" if uid == outside else "project"} for uid in ids],
                               "nextCursor": following}
                    item = {"server": "codex_app", "tool": "list_threads", "status": "completed",
                            "arguments": json.dumps(args), "result": {"content": [{"type": "text", "text": json.dumps(content)}]}}
                    db.execute("INSERT INTO thread_items VALUES(?,'onboard',?,'mcpToolCall',?,?,?,?,?)",
                               (owner, str(index), json.dumps(item), index, 1000, 1000, 1000))
            with state.readonly(state.panel_db()) as registry:
                result = panel_onboarding.scope(owner, registry, candidates=True)
            self.assertTrue(result["complete"])
            self.assertEqual({r["thread_id"] for r in result["candidates"]}, {worker, other})
            result = panel_onboarding.adopt(owner, thread_id=worker, title=worker, project_id="project")
            self.assertEqual([r["status"] for r in result["threads"]], ["ready"])
            with self.assertRaises(ValueError):
                state.track(owner, thread_id=worker, title=worker)
            with self.assertRaises(ValueError):
                panel_onboarding.adopt(outside, thread_id=worker, title=worker, project_id="other")
            with closing(sqlite3.connect(Path(directory) / "state_5.sqlite")) as db, db:
                db.execute("UPDATE threads SET archived=1 WHERE id=?", (other,))
            with self.assertRaises(ValueError):
                panel_onboarding.adopt(owner, thread_id=other, title=other, project_id="project")
            with state.write_registry() as registry:
                state.record_forward(registry, owner, worker, (state.time.time()+1, "审查指定版本"), worker, "")
            self.assertEqual(state.snapshot(owner)["threads"][0]["status"], "unconfirmed")

    def test_utf8_payload_over_stdin(self):
        root = str(uuid4())
        script = Path(state.__file__)
        with tempfile.TemporaryDirectory() as directory:
            create_indexes(directory, [(root, "user", None)])
            env = dict(environ, CODEX_HOME=directory, CODEX_THREAD_ID=root)
            result = subprocess.run(
                [sys.executable, "-B", "-X", "utf8", str(script), "init", "--stdin"],
                input='总讨论 "路线" — 复核\n', capture_output=True, encoding="utf-8", env=env, check=True,
            )
            self.assertEqual(json.loads(result.stdout)["director_title"], '总讨论 "路线" — 复核')

    def test_lifecycle(self):
        root, worker, other, ordinary, wrong = [str(uuid4()) for _ in range(5)]
        with tempfile.TemporaryDirectory() as directory, patch.dict(environ, {"CODEX_HOME": directory}):
            create_indexes(directory, [(root, "user", "第五章"), (worker, "agent_created_thread", "下界"),
                                      (other, None, "同目录的其他项目"), (ordinary, "user", "普通聊天"),
                                      (wrong, "agent_created_thread", "其他总串的执行串")])
            with closing(sqlite3.connect(Path(directory) / "thread_history_1.sqlite")) as history, history:
                history.execute("INSERT INTO thread_turns VALUES(?, 'turn1','inProgress',10,NULL,1,NULL)", (worker,))
                def receipt(owner, result, kind="mcpToolCall", status="completed"):
                    native = {"server": "codex_app", "tool": "create_thread", "status": status,
                              "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
                    history.execute("INSERT INTO thread_items(thread_id,turn_id,item_id,item_type,item_json) VALUES(?, 'dispatch', ?, ?, ?)",
                                    (owner, str(uuid4()), kind, json.dumps(native)))
                receipt(root, {"clientThreadId": "setup-1", "hostId": "local"})
                receipt(other, {"threadId": wrong, "hostId": "local"})
                receipt(root, {"threadId": wrong, "hostId": "local"}, kind="agentMessage")
                receipt(root, {"threadId": wrong, "hostId": "local"}, status="failed")
                receipt(root, {"threadId": wrong, "hostId": "ssh-remote"})
                (Path(directory) / ".codex-global-state.json").write_text(json.dumps({
                    "electron-owner-atoms:account": {"client-thread-bindings-v1": {"setup-1": worker},
                        "thread-client-id-v1:local%3A"+worker: "setup-1"}}))
                history.commit()
                root_key = state.initialize(root, "第五章")["view_key"]
                state.initialize(other, "同目录的其他项目")
                state.track(root, title="下界", pending_id="setup-1")
                with patch.object(state.time, "sleep"):
                    with self.assertRaises(ValueError):
                        state.track(root, title="另一个总讨论已创建、尚未登记的串", thread_id=wrong)
                    with self.assertRaises(ValueError):
                        state.track(root, title="无关串", pending_id="setup-1", thread_id=wrong)
                    with self.assertRaises(ValueError):
                        state.track(root, title="并不存在的排队记录", pending_id="fake")
                worker_row = state.track(root, title="下界", thread_id=worker)["threads"][0]
                self.assertEqual(worker_row["status"], "running")
                self.assertEqual(state.usage_starts(root, {worker: "setup-1"})[worker], 0)
                with closing(sqlite3.connect(Path(directory) / "state_5.sqlite")) as native, native:
                    native.execute("ALTER TABLE threads ADD COLUMN name TEXT")
                    native.executemany("UPDATE threads SET name=?,title='聊天的第一条消息' WHERE id=?",
                                       [("论文总讨论", root), ("审核专员", worker)])
                renamed = state.snapshot(view_key=root_key)
                self.assertEqual(renamed["director_title"], "论文总讨论")
                self.assertEqual(renamed["threads"][0], dict(worker_row, title="审核专员"))
                self.assertEqual(state.snapshot(worker)["director_title"], "论文总讨论")
                state.track(root, title="下界", thread_id=worker)
                self.assertEqual(state.snapshot(worker)["threads"][0]["title"], "审核专员")
                self.assertEqual(len(state.snapshot(view_key=root_key)["threads"]), 1)
                self.assertFalse(state.snapshot(ordinary)["paired"])
                with self.assertRaises(ValueError):
                    state.track(other, title="错误归属", thread_id=worker)
                with patch.object(state.time, "sleep"), self.assertRaises(ValueError):
                    state.track(root, title="普通聊天", thread_id=ordinary)
                other_workers = state.track(other, title="其他总串的执行串", thread_id=wrong)["threads"]
                self.assertEqual([w["thread_id"] for w in other_workers], [wrong])
                with self.assertRaises(ValueError):
                    state.snapshot(other, root_key)

                state.update(worker, status="waiting", summary="选择哪个定义？")
                history.execute("UPDATE thread_turns SET status='completed',completed_at=11,final_agent_item_id='x'")
                history.execute("""INSERT INTO thread_items(thread_id,turn_id,item_id,item_type,item_json) VALUES(?, 'turn1','x','agentMessage',
                                '{"phase":"final_answer"}')""", (worker,))
                history.commit()
                self.assertEqual(state.snapshot(root)["threads"][0]["status"], "waiting")
                with self.assertRaises(ValueError):
                    state.update(worker, status="completed", summary="自行验收")
                state.update(worker, status="review", summary="已交付")
                state.update(root, thread_id=worker, status="completed", summary="已确认")
                self.assertEqual(state.snapshot(worker)["threads"][0]["status"], "completed")
                history.execute("INSERT INTO thread_turns VALUES(?,'turn2','inProgress',20,NULL,2,NULL)", (worker,))
                history.commit()
                self.assertEqual(state.snapshot(root)["threads"][0]["status"], "running")
                history.execute("UPDATE thread_turns SET status='completed',completed_at=22,final_agent_item_id='z' WHERE turn_id='turn2'")
                history.execute("""INSERT INTO thread_items(thread_id,turn_id,item_id,item_type,item_json) VALUES(?, 'turn2','z','agentMessage',
                                '{"phase":"final_answer"}')""", (worker,))
                history.commit()
                self.assertEqual(state.snapshot(root)["threads"][0]["status"], "review")
            with closing(sqlite3.connect(Path(directory) / "state_5.sqlite")) as host, host:
                host.execute("UPDATE threads SET archived=1,archived_at=25 WHERE id=?", (worker,))
            self.assertEqual(state.snapshot(root)["threads"][0]["status"], "archived")
            self.assertEqual(state.snapshot(view_key=state.snapshot(worker)["view_key"])["role"], "worker")

    def test_forward_into_existing_chat(self):
        root, other, worker, legacy, unrelated = [str(uuid4()) for _ in range(5)]
        with tempfile.TemporaryDirectory() as directory, patch.dict(environ, {"CODEX_HOME": directory}):
            create_indexes(directory, [(root, "user", "总讨论"), (other, "user", "另一个总讨论"), (worker, "user", "论文审核"),
                                      (legacy, "user", "原实验串"), (unrelated, "user", "其他聊天")])
            key = state.initialize(root, "总讨论")["view_key"]
            state.initialize(other, "另一个总讨论")
            with closing(sqlite3.connect(Path(directory) / "thread_history_1.sqlite")) as history, history:
                def send(target, seconds, *, prompt="【Director 派工】审核第三章\n请核对证明。",
                         host="local", result_id=None, status="completed", error=False, kind="mcpToolCall", owner=root):
                    args = {"threadId": target, "prompt": prompt}
                    if host is not None:
                        args["hostId"] = host
                    result = {"threadId": result_id or target}
                    uid = str(uuid4())
                    item = {"id": uid, "type": kind, "server": "codex_app", "tool": "send_message_to_thread",
                            "status": status, "arguments": args, "error": None, "result": {"isError": error,
                            "content": [{"type": "text", "text": json.dumps(result)}]}}
                    history.execute("""INSERT INTO thread_items VALUES(?, 'dispatch', ?, ?, ?, ?, ?, ?, ?)""",
                                    (owner, uid, kind, json.dumps(item), seconds, seconds * 1000,
                                     seconds * 1000, seconds * 1000 + 10))

                send(worker, 8, prompt="进展如何？")
                send(worker, 10)
                send(legacy, 11, host=None, prompt="请继续原来的实验。")
                send(unrelated, 12, status="failed")
                send(unrelated, 13, error=True)
                send(unrelated, 14, host="ssh-remote")
                send(unrelated, 15, result_id=worker)
                send(unrelated, 16, kind="agentMessage")
                send(unrelated, 17, prompt="进展如何？")
                history.execute("INSERT INTO thread_turns VALUES(?, 'first','inProgress',10,NULL,1,NULL)", (worker,))
                history.commit()

                rows = state.snapshot(view_key=key)["threads"]
                self.assertEqual([(w["thread_id"], w["status"]) for w in rows], [(worker, "running")])
                self.assertEqual(state.snapshot(worker)["director_id"], root)
                history.execute("UPDATE thread_turns SET status='completed',completed_at=18,final_agent_item_id='answer' WHERE thread_id=?", (worker,))
                history.execute("""INSERT INTO thread_items(thread_id,turn_id,item_id,item_type,item_json)
                                VALUES(?, 'first','answer','agentMessage','{"phase":"final_answer"}')""", (worker,))
                history.commit()
                row = state.snapshot(view_key=key)["threads"][0]
                self.assertEqual((row["status"], row["summary"]), ("review", "审核第三章"))
                with patch.object(state.time, "time", return_value=19):
                    state.update(root, thread_id=worker, status="completed", summary="已确认")
                self.assertEqual(state.snapshot(view_key=key)["threads"][0]["status"], "completed")

                send(worker, 20, host=None, prompt="【Director 派工】复核修订后的证明")
                history.commit()
                self.assertEqual(state.snapshot(view_key=key)["threads"][0]["status"], "pending")
                history.execute("INSERT INTO thread_turns VALUES(?, 'second','inProgress',20,NULL,2,NULL)", (worker,))
                history.commit()
                rows = state.snapshot(view_key=key)["threads"]
                self.assertEqual([(w["thread_id"], w["status"]) for w in rows], [(worker, "running")])
                saved = state.track(root, title="原实验串", thread_id=legacy, summary="实验已派工")
                with closing(sqlite3.connect(Path(directory) / "state_5.sqlite")) as native, native:
                    native.execute("ALTER TABLE threads ADD COLUMN rollout_path TEXT")
                    native.execute("UPDATE threads SET rollout_path=id")
                # Old panels may predate usage metadata. Recover the first assignment once.
                with state.write_registry() as db:
                    db.execute("DELETE FROM worker_usage_start WHERE thread_id=?", (worker,))
                with patch.object(state, "usage_for_threads", return_value={}) as count:
                    self.assertIn("token_usage", state.snapshot(view_key=key, include_usage=True))
                    self.assertEqual(count.call_args.args[0], [(root, None), (worker, 10), (legacy, 11)])
                    self.assertNotIn("token_usage", state.snapshot(worker, include_usage=True))
                    count.assert_called_once()
                send(legacy, 21)
                history.commit()
                self.assertEqual(state.usage_starts(root, {worker: None, legacy: None}), {worker: 10, legacy: 11})
                self.assertNotIn("return_panel_path", saved)
                self.assertFalse(list(Path(directory).rglob("返回项目总讨论.md")))
                self.assertEqual({w["thread_id"] for w in state.snapshot(root)["threads"]}, {worker, legacy})
                send(worker, 22, owner=other)
                history.commit()
                self.assertEqual(state.snapshot(other)["threads"], [])
                with self.assertRaises(ValueError):
                    state.track(other, thread_id=worker, title="论文审核")
                self.assertEqual(state.snapshot(worker)["director_id"], root)


if __name__ == "__main__":
    unittest.main()
