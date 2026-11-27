import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugins' / 'codex-director'))
import panel_state
import worker_reply


class WorkerReply(unittest.TestCase):
    def test_director_roster_and_worker_prompt_sync(self):
        from test_panel_state import create_indexes
        owner, worker = str(uuid4()), str(uuid4())
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, CODEX_HOME=directory):
            create_indexes(directory, [(owner,"user","总讨论"),(worker,"user","算法串")])
            with panel_state.write_registry() as db:
                db.execute("INSERT INTO directors VALUES(?,'总讨论','d')",(owner,))
                db.execute("INSERT INTO workers VALUES(?,?,NULL,'w','算法串','ready','',0,NULL)",(owner,worker))
            panel_state.set_worker_role(owner,thread_id=worker,role="核对算法")
            def context(actor, event, **extra):
                result=worker_reply.hook_result({"session_id":actor,"hook_event_name":event,**extra})
                return result["hookSpecificOutput"]["additionalContext"]
            director=context(owner,"UserPromptSubmit")
            self.assertIn("严禁总讨论读/搜业务源码",director)
            self.assertIn(f"算法串 [未派工] ({worker})：核对算法",director)
            self.assertNotIn("当前执行串花名册",context(owner,"SessionStart",source="resume"))
            self.assertNotIn("项目共享上下文",context(worker,"SessionStart",source="resume"))
            self.assertIn("本串分工：核对算法",context(worker,"UserPromptSubmit"))
            self.assertNotIn("项目共享上下文",context(worker,"UserPromptSubmit"))

    def test_selected_plugin_is_distinct_from_quoted_text(self):
        import json
        import sqlite3
        from contextlib import closing
        owner, turn = str(uuid4()), str(uuid4())
        mention = {"type": "mention", "path": "plugin://codex-director@director-local"}
        prompt = "[Thread for Codex](plugin://codex-director@director-local)"
        event = {"session_id": owner, "turn_id": turn, "hook_event_name": "UserPromptSubmit", "prompt": prompt}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, CODEX_HOME=directory):
            with closing(sqlite3.connect(Path(directory)/"thread_history_1.sqlite")) as db:
                db.execute("CREATE TABLE thread_items(thread_id,turn_id,item_type,rollout_ordinal,item_json)")
                for number, selected in enumerate(([], [mention])):
                    data = {"content": [{"type": "text", "text": prompt}, *selected]}
                    db.execute("INSERT INTO thread_items VALUES(?,?,'userMessage',?,?)",
                               (owner, turn, number, json.dumps(data)))
                    db.commit()
                    self.assertEqual(bool(worker_reply.hook_result(event)), bool(selected))
            self.assertIsNone(worker_reply.hook_result(dict(event, turn_id=str(uuid4()))))

    def test_resume_and_once_only_correction(self):
        parent, worker, ordinary = [str(uuid4()) for _ in range(3)]
        footer = f'[← 返回总讨论](codex://threads/{parent})'
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, CODEX_HOME=directory):
            with panel_state.write_registry() as db:
                db.execute("INSERT INTO directors VALUES(?, '总讨论', 'p')", (parent,))
                db.execute("INSERT INTO workers(director,thread_id,view_key,title,status,summary,updated) "
                           "VALUES(?,?,'w','旧执行串','completed','',0)", (parent, worker))
            def emit(name, **fields):
                return worker_reply.hook_result({'session_id': worker, 'hook_event_name': name, **fields})
            self.assertIsNone(emit('SessionStart', source='fork'))
            for name, fields in [('UserPromptSubmit', {}), ('SessionStart', {'source': 'resume'})]:
                result = emit(name, **fields)['hookSpecificOutput']
                self.assertEqual(result['hookEventName'], name)
                self.assertEqual(result['additionalContext'].splitlines()[-1], footer)
            for body in ['交付完成。', '原文\n\n' + footer.replace(parent, ordinary),
                         '原文\n\n```md\n\n' + footer, '原文\n\n> ' + footer,
                         '原文\n\n> 引用\n' + footer, '原文\n\n    ' + footer]:
                with self.subTest(body=body):
                    correction = emit('Stop', stop_hook_active=False, last_assistant_message=body)
                    self.assertEqual(correction['decision'], 'block')
                    self.assertTrue(correction['reason'].endswith(footer))
                    self.assertIn('完整答复', correction['reason'])
                    self.assertIsNone(emit('Stop', stop_hook_active=True, last_assistant_message=body))
            for body in [None, '', ' \n', '```md\n示例\n```\n\n' + footer, '正文\n\n' + footer + '\n',
                         '正文\n' + footer, '正文\n\n' + footer.replace('← 返回总讨论', '↩ 返回项目总讨论')]:
                self.assertIsNone(emit('Stop', stop_hook_active=False, last_assistant_message=body))
            panel = '[打开项目讨论串](https://thread-for-codex.invalid/panel)'
            for name, fields in [('UserPromptSubmit', {}), ('SessionStart', {'source': 'resume'})]:
                self.assertEqual(emit(name, session_id=parent, **fields)['hookSpecificOutput']
                                 ['additionalContext'].splitlines()[-1], panel)
                self.assertIsNone(emit(name, session_id=ordinary, **fields))
            for body in ['正文', '正文\n\n' + footer]:
                corrected = emit('Stop', session_id=parent, stop_hook_active=False, last_assistant_message=body)
                self.assertEqual(corrected['decision'], 'block')
                self.assertTrue(corrected['reason'].endswith(panel))
                self.assertIn('完整答复', corrected['reason'])
                self.assertIsNone(emit('Stop', session_id=parent, stop_hook_active=True, last_assistant_message=body))
            self.assertIsNone(emit('Stop', session_id=parent, stop_hook_active=False, last_assistant_message='正文\n\n' + panel))
            self.assertIsNone(emit('Stop', session_id=ordinary, stop_hook_active=False, last_assistant_message='正文'))
            self.assertIsNone(emit('Stop', last_assistant_message='正文'))
