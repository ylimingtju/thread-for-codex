"""Supply the main chat link when Codex starts a turn in a registered worker."""
import json
import sqlite3
import sys

from panel_state import panel_db, readonly, uuid_text


def main():
    event = json.load(sys.stdin.buffer)
    if not isinstance(event, dict) or event.get("hook_event_name") != "UserPromptSubmit":
        return
    worker = uuid_text(event.get("session_id"))
    if not panel_db().is_file():
        return
    with readonly(panel_db()) as db:
        row = db.execute(
            "SELECT directors.id FROM workers JOIN directors ON directors.id = workers.director "
            "WHERE workers.thread_id = ?", (worker,),
        ).fetchone()
    if row:
        parent = uuid_text(row["id"])
        footer = f"[← 返回总讨论](codex://threads/{parent})"
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "本串面向用户的回复（包括提问和直接追问的答复）以空行和以下独立一行结束，"
                                 "链接只写一次。中途进展无需附链接。\n" + footer,
        }}))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, sqlite3.Error):
        # Navigation is optional when the registry is unavailable. Let the conversation continue.
        pass
