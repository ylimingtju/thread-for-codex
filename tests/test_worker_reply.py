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
