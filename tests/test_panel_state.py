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
    def test_worker_sync_rev_and_delta(self):
        owner, worker, sibling, outsider = (str(uuid4()) for _ in range(4))
        with tempfile.TemporaryDirectory() as directory, patch.dict(environ, CODEX_HOME=directory):
            create_indexes(directory, [(uid, "user", name) for uid, name in
                                      [(owner,"总讨论"),(worker,"实现"),(sibling,"复核"),(outsider,"其他项目")]])
            with state.write_registry() as db:
                db.executemany("INSERT INTO directors VALUES(?,?,?)", [(owner,"总讨论","d"),(outsider,"其他项目","o")])
                db.executemany("INSERT INTO workers VALUES(?,?,NULL,?,?,'ready','',0,NULL)",
                               [(owner,worker,"w","实现"),(owner,sibling,"s","复核")])
            self.assertIsNone(state.sync_context_for_worker(worker))
            state.upsert_decision(outsider, content="其他项目保密")
            state.set_worker_role(owner, thread_id=worker, role="程序维护")
            state.set_worker_roles(owner,[{"thread_id":sibling,"role":"核对证明"}])
            decision = state.upsert_decision(owner, content="使用新基准",source_thread_id=sibling)["decisions"][0]
            first = state.sync_context_for_worker(worker)
            for phrase in ("首次同步","本串分工：程序维护","复核：核对证明","使用新基准"):
                self.assertIn(phrase,first)
            self.assertNotIn("其他项目保密",first)
            state.set_worker_role(owner, thread_id=worker, role="程序维护")
            state.upsert_decision(owner, id=decision["id"], content="使用新基准", source_thread_id=sibling)
            with patch.object(state,"write_registry",side_effect=AssertionError("无变更不应写库")):
                self.assertIsNone(state.sync_context_for_worker(worker))
            state.upsert_decision(owner,id=decision["id"],content="改用第二版",source_thread_id=worker)
            state.set_worker_role(owner,thread_id=sibling,role="第一次修订")
            state.set_worker_role(owner,thread_id=sibling,role="最终分工")
            state.delete_decision(owner,id=decision["id"])
            delta=state.sync_context_for_worker(worker)
            self.assertIn("共识更新",delta)
            self.assertIn("原决定「改用第二版」已废止",delta)
            self.assertIn("最终分工",delta)
            self.assertNotIn("第一次修订",delta)
            self.assertNotIn("已确认决定：",delta)
            for index in range(32):
                state.set_worker_role(owner,thread_id=sibling,role=f"版本 {index}")
            self.assertIn("以当前分工和决定为准",state.sync_context_for_worker(worker))
            with state.readonly(state.panel_db()) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM sync_log WHERE director=?",(owner,)).fetchone()[0],30)
            with state.write_registry() as db:
                for table in ("project_revisions","worker_sync","sync_log"):
                    db.execute("DROP TABLE "+table)
            self.assertIsNone(state.sync_context_for_worker(worker))
            with state.write_registry():
                pass
            self.assertIn("版本 31",state.sync_context_for_worker(worker))

    def test_review_summary_uses_final_answer_excerpt(self):
        row = {"status":"review","summary":"派工摘要","updated":2,"turn_id":"current","thread_id":"worker"}
        turn = {"status":"completed","turn_id":"current","started_at":1,"completed_at":2,"delivered":True,
                "previous_start":None,"request":"请复核模型","final_answer":"\n## 已修正边界\n\n共两处。\n\n"
                "[← 返回总讨论](codex://threads/1234-abcd)"}
        self.assertEqual(state.observed(row,turn,None)[:2], ("review","已修正边界 共两处。"))
        self.assertEqual(state.observed(dict(row,status="waiting",summary="用哪个版本？"),turn,None)[1],"用哪个版本？")
        self.assertEqual(state.observed(dict(row,status="waiting",summary=turn["request"]),turn,None)[1],"已修正边界 共两处。")
        self.assertEqual(state.observed(row,dict(turn,final_answer="[↩ 返回项目总讨论](codex://threads/1234-abcd)"),None)[1],
                         "派工摘要")

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
                queued = state.snapshot(owner)["threads"][0]
                self.assertEqual(queued["latest_assignment_at"], "1970-01-01T00:00:02+00:00")
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

            self.assertEqual((current()["status_turn_id"], current()["summary"]), (first, "本轮答复"))
            self.assertNotIn("status_turn_id", state.snapshot(view_key="owner-key")["threads"][0])
            self.assertNotIn("status_turn_id", state.snapshot(worker)["threads"][0])
            for actor in (None, worker, other):
                self.assertTrue(action("completed", actor)["isError"])
            self.assertTrue(action("completed", hostId="ssh-test")["isError"])
            self.assertEqual(action("completed")["structuredContent"]["status"], "completed")
            self.assertEqual((current()["status"], current()["summary"]), ("completed", "本轮答复"))
            with self.assertRaises(ValueError):
                state.update(worker, status="review", summary="补交说明")

            with closing(sqlite3.connect(queue_path)) as queue, queue:
                queue.execute("INSERT INTO queued_items VALUES(?,'queued')", (worker,))
            self.assertEqual(current()["status"], "queued")
            self.assertTrue(action("review")["isError"])
            with closing(sqlite3.connect(queue_path)) as queue, queue:
                queue.execute("DELETE FROM queued_items")
            self.assertEqual(action("review")["structuredContent"]["status"], "review")
            self.assertEqual((current()["status"], current()["summary"]), ("review", "本轮答复"))
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
            self.assertEqual((current()["status"], current()["summary"]), ("review", "新的答复"))
            with state.write_registry() as registry:
                registry.execute("UPDATE workers SET status='running',summary='上一轮进展',updated=2.5,turn_id=NULL")
            self.assertEqual((current()["status"], current()["summary"]), ("review", "新的答复"))
            self.assertEqual(action("completed", turn=new)["structuredContent"]["status"], "completed")
            self.assertEqual(action("review", turn=new)["structuredContent"]["status"], "review")
            self.assertEqual(current()["summary"], "新的答复")

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

    def test_worker_roles_persist_across_dispatches_and_turns(self):
        owner, worker, other = (str(uuid4()) for _ in range(3))
        with tempfile.TemporaryDirectory() as directory, patch.dict(environ, CODEX_HOME=directory):
            create_indexes(directory, [(uid, "user", uid) for uid in (owner, worker, other)])
            state.initialize(owner, owner)
            state.initialize(other, other)
            with patch.object(panel_onboarding, "listed_threads", return_value=(
                    {uid: {"title": uid, "projectId": "p"} for uid in (owner, worker)}, True)):
                adopted = panel_onboarding.adopt(owner, thread_id=worker, title=worker, project_id="p", role="原始分工")
            self.assertEqual(adopted["threads"][0]["role"], "原始分工")
            with self.assertRaisesRegex(ValueError, "正式聊天 ID"):
                state.track(owner, title="准备中", pending_id="client", role="任务")
            sent = state.time.time()+1
            with patch.object(state, "forward_receipts", return_value=[(worker, sent, "本轮任务", sent)]):
                row = state.track(owner, title=worker, thread_id=worker, role="核对\n  模型")["threads"][0]
            self.assertEqual((row["role"], row["latest_assignment"]), ("核对 模型", "本轮任务"))
            self.assertEqual(row["latest_assignment_at"], state.datetime.fromtimestamp(sent, state.timezone.utc).isoformat())
            with state.write_registry() as db:
                state.record_forward(db, owner, worker, (sent+1, "新任务"), worker, "本轮摘要")
                prior_stamp = db.execute("SELECT updated FROM worker_roles").fetchone()[0]
            with closing(sqlite3.connect(Path(directory) / "thread_history_1.sqlite")) as db, db:
                db.execute("INSERT INTO thread_turns VALUES(?, 'new','inProgress',?,NULL,1,NULL)", (worker, sent+2))
            state.update(worker, status="waiting", summary="等用户选择")
            self.assertEqual(state.snapshot(owner)["threads"][0]["role"], "核对 模型")
            saved = state.set_worker_roles(owner, [{"thread_id": worker, "role": "核对 模型"}])
            self.assertNotIn("token_usage", saved)
            with state.readonly(state.panel_db()) as db:
                self.assertEqual(db.execute("SELECT updated FROM worker_roles").fetchone()[0], prior_stamp)
            for target, actor in [(worker, other), (str(uuid4()), owner)]:
                with self.assertRaises(ValueError):
                    state.set_worker_role(actor, thread_id=target, role="错误的归属")
            for roles in ([{"thread_id": worker, "role": "重复"}]*2, [{"thread_id": worker, "role": "字"*161}]):
                with self.assertRaises(ValueError):
                    state.set_worker_roles(owner, roles)
            self.assertNotIn("role", state.set_worker_role(owner, thread_id=worker, role=" ")["threads"][0])
            with state.write_registry() as db:
                db.execute("DROP TABLE worker_roles")
                db.execute("DROP TABLE project_decisions")
            legacy = state.snapshot(owner)
            self.assertEqual(legacy["decisions"], [])
            self.assertNotIn("role", legacy["threads"][0])

    def test_director_roster_and_digest(self):
        owner, missing, filled, archived, outside = (str(uuid4()) for _ in range(5))
        with tempfile.TemporaryDirectory() as directory, patch.dict(environ, CODEX_HOME=directory):
            create_indexes(directory, [(uid, "user", uid) for uid in (owner, missing, filled, archived, outside)])
            with state.write_registry() as db:
                db.execute("INSERT INTO directors VALUES(?,?,'d')", (owner, owner))
                db.executemany("INSERT INTO workers VALUES(?,?,NULL,?,?,'ready','',0,NULL)",
                               [(owner, uid, uid, uid) for uid in (missing, filled, archived)])
                db.execute("INSERT INTO workers VALUES(?,NULL,'new','p','准备中','preparing','',0,NULL)", (owner,))
            with closing(sqlite3.connect(Path(directory) / "state_5.sqlite")) as db, db:
                db.execute("UPDATE threads SET archived=1 WHERE id=?", (archived,))
                db.execute("UPDATE threads SET title='项目总讨论' WHERE id=?", (owner,))
            state.set_worker_role(owner, thread_id=filled, role="已有手写分工")
            decision = state.upsert_decision(owner, content="保留四类", source_thread_id=filled)["decisions"][0]
            history_path = Path(directory) / "thread_history_1.sqlite"
            with closing(sqlite3.connect(history_path)) as db, db:
                db.executemany("INSERT INTO thread_turns VALUES(?,?,?,?,?,?,?)", [
                    (missing, "first", "completed", 1, 2, 10, "answer"),
                    (missing, "last", "inProgress", 3, None, 20, None)])
                def item(turn, kind, body, order):
                    db.execute("INSERT INTO thread_items VALUES(?,?,?,?,?,?,0,0,0)",
                               (missing, turn, str(order), kind, json.dumps(body), order))
                item("first", "userMessage", {"content": [{"text": "\n  "}]}, 1)
                item("first", "functionCallOutput", {"namespace": "codex_app", "name": "create_thread",
                     "output": "<codex_delegation><input>【Director 派工】审核 A &amp; B\n  模型</input></codex_delegation>"}, 2)
                item("last", "userMessage", {"content": [{"type": "image"}, {"text": " 复核\n "}, {"text": "新"*210}]}, 3)
                item("first", "agentMessage", {"phase": "final_answer", "text": "采用\n 四类。\n\n"
                     f"[← 返回总讨论](codex://threads/{owner})\n"}, 4)
                item("last", "agentMessage", {"phase": "commentary", "text": "当前进度"}, 5)
            with state.write_registry() as db:
                db.execute("UPDATE workers SET status='running',turn_id='last' WHERE thread_id=?", (missing,))
            titles = ["标题一", "标题二", "标题三", "标题四", "标题五", "标题六", "标题三"]
            receipts = [(missing, 100-index, subject, index+1) for index, subject in enumerate(titles)]
            with patch.object(state, "forward_receipts", return_value=receipts):
                result = state.digest(owner)
            self.assertEqual(result["director_title"], "项目总讨论")
            self.assertEqual([r["thread_id"] for r in result["threads"]], [missing])
            row = result["threads"][0]
            self.assertEqual(row["recent_dispatches"], ["标题三", "标题六", "标题五"])
            self.assertEqual(len(row["turns"]), 1)
            self.assertEqual(row["turns"][0]["reply"], "")
            roster = state.director_roster_hint(owner)
            self.assertIn(f"{filled} [未派工] ({filled})：已有手写分工", roster)
            self.assertIn("后台已记录 1 条", roster)
            self.assertNotIn(archived, roster)
            self.assertNotIn(outside, roster)
            with closing(sqlite3.connect(history_path)) as db, db:
                db.execute("UPDATE thread_items SET item_id='answer' WHERE turn_id='first' AND item_type='agentMessage'")
                db.execute("INSERT INTO thread_items VALUES(?, 'first','tool','functionCallOutput',?,0,0,0,0)",
                           (missing,json.dumps({"output":"不该出现在问答中的工具日志"})))
            single = state.digest(owner, thread_id=missing)["threads"][0]["turns"]
            self.assertEqual([entry["turn_id"] for entry in single], ["last","first"])
            self.assertEqual(single[1]["request"], "审核 A & B 模型")
            self.assertEqual(single[1]["reply"], "采用 四类。")
            self.assertNotIn("工具日志", str(single))
            all_info = state.digest(owner, all_threads=True)
            self.assertEqual([r["thread_id"] for r in all_info["threads"]], [missing, filled])
            self.assertEqual(all_info["existing_decisions"], [
                {"id": decision["id"], "content": "保留四类", "source_thread_id": filled}])
            for target in (outside, archived):
                with self.assertRaisesRegex(ValueError, "未归档执行串"):
                    state.digest(owner, thread_id=target)
            with self.assertRaisesRegex(ValueError, "只有已登记的总讨论"):
                state.digest(missing)
            def cli(actor, args, payload=None, check=True):
                return subprocess.run([sys.executable, "-B", str(Path(state.__file__)), *args], encoding="utf-8",
                                      input=json.dumps(payload, ensure_ascii=False) if payload is not None else None,
                                      env=dict(environ, CODEX_THREAD_ID=actor), capture_output=True, check=check)
            self.assertEqual(len(json.loads(cli(owner, ["digest","--all"]).stdout)["threads"]), 2)
            target = json.loads(cli(owner, ["digest","--thread",missing,"--turns","1"]).stdout)
            self.assertEqual(len(target["threads"][0]["turns"]), 1)
            self.assertNotEqual(cli(owner, ["show","--turns","2"], check=False).returncode, 0)
            self.assertNotEqual(cli(missing, ["digest"], check=False).returncode, 0)
            history_path.unlink()
            self.assertEqual(state.digest(owner, thread_id=missing)["threads"][0]["turns"], [])
            updates = [{"thread_id": missing, "role": "中文分工"}]
            self.assertNotIn("token_usage", json.loads(cli(owner, ["roles", "--stdin"], updates).stdout))
            cli(owner, ["roles", "--stdin"], {"roles": [{"thread_id": missing, "role": "迟到的草稿"}], "only_missing": True})
            self.assertEqual([r["role"] for r in state.digest(owner, all_threads=True)["threads"]],
                             ["中文分工", "已有手写分工"])

    def test_project_decisions_lifecycle_and_timestamps(self):
        owner, worker, other = (str(uuid4()) for _ in range(3))
        with tempfile.TemporaryDirectory() as directory, patch.dict(environ, CODEX_HOME=directory):
            create_indexes(directory, [(uid, "user", name) for uid, name in
                                      [(owner, "总讨论"), (worker, "实施"), (other, "其他项目")]])
            key = state.initialize(owner, "总讨论")["view_key"]
            state.initialize(other, "其他项目")
            with state.write_registry() as db:
                db.execute("INSERT INTO workers VALUES(?,?,NULL,'w','实施','ready','',0,NULL)", (owner, worker))
            state.set_worker_role(owner, thread_id=worker, role="完成实施")
            with patch.object(state.time, "time", return_value=10):
                first = state.upsert_decision(owner, content="按方案执行", source_thread_id=owner)["decisions"][0]
                second = state.upsert_decision(owner, content="初稿")["decisions"][1]
                removed = state.upsert_decision(owner, content="即将过期")["decisions"][2]
            self.assertRegex(first["id"], r"^[0-9a-f]{8}$")
            self.assertEqual(first["source_title"], "总讨论")
            with patch.object(state.time, "time", return_value=20):
                changed = state.upsert_decision(owner, id=second["id"], content="采用新方案", source_thread_id=worker)["decisions"][1]
                self.assertEqual(changed["source_title"], "实施")
                self.assertGreater(changed["updated_at"], second["updated_at"])
                state.upsert_decision(owner, id=first["id"], content="按方案执行", source_thread_id=owner)
            self.assertEqual(state.snapshot(owner)["decisions"][0], first)
            self.assertNotIn("role", state.snapshot(worker)["threads"][0])
            self.assertNotIn("decisions", state.snapshot(worker))
            self.assertNotIn("can_edit_project", state.snapshot(view_key=key))
            with self.assertRaises(ValueError):
                state.delete_decision(other, id=first["id"])
            with self.assertRaises(ValueError):
                state.upsert_decision(other, id=first["id"], content="其他项目的决定")
            for entry in ({"content":"字"*241}, {"content":"来源错误","source_thread_id":other}):
                with self.assertRaises(ValueError):
                    state.upsert_decision(owner, **entry)
            state.delete_decision(owner, id=removed["id"])
            with self.assertRaises(ValueError):
                state.delete_decision(owner, id=removed["id"])
            with closing(sqlite3.connect(Path(directory) / "state_5.sqlite")) as host, host:
                host.execute("UPDATE threads SET archived=1,title='已改名' WHERE id=?", (worker,))
            archived = state.snapshot(owner)["decisions"][1]
            self.assertEqual((archived["source_archived"], archived["source_title"]), (True,"已改名"))
            with self.assertRaisesRegex(ValueError, "已归档"):
                state.upsert_decision(owner, content="归档来源", source_thread_id=worker)
            with self.assertRaises(ValueError):
                state.set_worker_roles(owner, [{"thread_id":worker, "role":""}])
            for i in range(18):
                state.upsert_decision(owner, content=str(i))
            with self.assertRaisesRegex(ValueError, "20"):
                state.upsert_decision(owner, content="超出数量")

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
            worker = str(uuid4())
            with patch.dict(environ, CODEX_HOME=directory), state.write_registry() as db:
                db.execute("INSERT INTO workers VALUES(?,?,NULL,'w','旧串','ready','',0,NULL)", (root, worker))
            def command(action, payload):
                result = subprocess.run([sys.executable, "-B", "-X", "utf8", str(script), action, "--stdin"],
                                        input=json.dumps(payload, ensure_ascii=False), capture_output=True,
                                        encoding="utf-8", env=env, check=True)
                return json.loads(result.stdout)
            self.assertEqual(command("role", {"thread_id": worker, "role": "模型复核"})["threads"][0]["role"], "模型复核")
            decision = command("decision", {"content": "采用修订方案"})["decisions"][0]
            self.assertEqual(decision["content"], "采用修订方案")
            self.assertEqual(command("decision", {"action": "delete", "id": decision["id"]})["decisions"], [])

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
