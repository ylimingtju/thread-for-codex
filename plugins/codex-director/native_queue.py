"""Submit an authorized follow-up to Codex's durable queue without starting or steering a turn."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
from threading import Timer
from uuid import UUID, uuid5

import panel_state as state


def enqueue(actor, target, prompt):
    actor, target = state.uuid_text(actor), state.uuid_text(target)
    prompt = state.label(prompt, 60000)
    if not prompt.startswith(state.DISPATCH_PREFIX) or not prompt.splitlines()[0][len(state.DISPATCH_PREFIX):].strip():
        raise ValueError("派工消息首行须包含【Director 派工】和任务标题。")
    cli = os.environ.get("CODEX_APP_RUNTIME_CLI_PATH") or shutil.which("codex")
    if not cli or not Path(cli).is_file():
        raise ValueError("没有找到本机 Codex CLI，无法入队。")
    # Serialize simultaneous plugin retries. The only persistent queue is owned by Codex.
    with state.write_registry() as registry:
        row = registry.execute("SELECT 1 FROM directors d JOIN workers w ON w.director=d.id "
                               "WHERE d.id=? AND w.thread_id=? AND w.status!='archived'", (actor, target)).fetchone()
        if not row or state.local_thread(target)["archived"] or state.local_thread(actor)["archived"]:
            raise ValueError("只能向本总讨论名下未归档的执行串派工。")
        with state.readonly(state.home() / "thread_history_1.sqlite") as history:
            active = state.latest_turn(history, actor)
            if not active or active["status"] != "inProgress":
                raise ValueError("无法确认总讨论的本轮派工。")
            turn = active["turn_id"]
            key = str(uuid5(UUID(turn), target + "\n" + prompt))
            for _, receipt, _ in state.dispatch_receipts(history, actor, "enqueue_task", turn):
                if receipt["clientUserMessageId"] == key:
                    return receipt
            if state.queued_turn(history, target, key):
                raise ValueError("这项任务已经进入执行回合，请查看原串。")
        footer = f"[← 返回总讨论](codex://threads/{actor})"
        text = (prompt.removesuffix(footer).rstrip() + "\n\n此任务由项目总讨论通过 Thread for Codex 转交，"
                "请按已有用户授权执行。\n\n" + footer)
        submission = submit(cli, target, key, text)
        if submission.get("clientUserMessageId") != key or not submission.get("id"):
            raise ValueError("入队回执不完整，请先查看原串队列。")
        return {"threadId": target, "hostId": "local", "queuedSubmissionId": submission["id"],
                "clientUserMessageId": key, "status": "queued"}


def submit(cli, target, key, text):
    with subprocess.Popen([cli, "app-server", "--listen", "stdio://"], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, encoding="utf-8") as process:
        timeout = Timer(8, process.kill)
        timeout.start()
        def send(message):
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()

        def request(number, method, params):
            send({"id": number, "method": method, "params": params})
            for line in process.stdout:
                response = json.loads(line)
                if response.get("id") == number:
                    if "error" in response:
                        raise ValueError(response["error"]["message"])
                    return response["result"]
            raise ValueError("未取得 Codex 服务回执，请先查看原串队列。")
        try:
            request(1, "initialize", {"clientInfo": {"name": "director-local", "version": "1"},
                                      "capabilities": {"experimentalApi": True}})
            send({"method": "initialized"})
            cursor = None
            while True:
                page = request(2, "thread/queue/list", {"threadId": target, "cursor": cursor})
                for item in page["data"]:
                    if item.get("clientUserMessageId") == key:
                        return item
                cursor = page.get("nextCursor")
                if not cursor:
                    break
            return request(3, "thread/queue/add", {"threadId": target, "clientUserMessageId": key,
                           "input": [{"type": "text", "text": text, "text_elements": []}]})["queuedSubmission"]
        finally:
            timeout.cancel()
            process.terminate()


def pending(target, submission):
    try:
        with state.readonly(state.home() / "queue_1.sqlite") as db:
            return bool(db.execute("SELECT 1 FROM queued_items WHERE thread_id=? AND id=?",
                                   (target, submission)).fetchone())
    except sqlite3.Error:
        return None
