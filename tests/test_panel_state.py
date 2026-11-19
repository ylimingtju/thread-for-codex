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
                if actor == worker:
                    footer = f"[← 返回总讨论](codex://threads/{director})"
                    context = json.loads(output)["hookSpecificOutput"]["additionalContext"]
                    self.assertEqual(context.splitlines()[-1], footer)
                else:
                    self.assertEqual(output, "")

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
                self.assertEqual(state.snapshot(view_key=key)["threads"][0]["status"], "review")
                with patch.object(state.time, "time", return_value=19):
                    state.update(root, thread_id=worker, status="completed", summary="已确认")
                self.assertEqual(state.snapshot(view_key=key)["threads"][0]["status"], "completed")

                send(worker, 20, host=None, prompt="【Director 派工】复核修订后的证明")
                history.commit()
                self.assertEqual(state.snapshot(view_key=key)["threads"][0]["status"], "running")
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
