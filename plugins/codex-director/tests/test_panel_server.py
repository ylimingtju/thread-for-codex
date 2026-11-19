"""Run with python3 -B tests/test_panel_server.py from the plugin directory."""
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import panel_server as server


def check():
    director = '514558bc-395b-4fd4-85de-8f771cf81c24'
    worker = '212014b6-77c5-4a06-8e3b-1b23867f3460'
    other = 'bec5cd75-fb52-4160-b9b9-4c44af5d43ef'
    data = {'paired': True, 'role': 'worker', 'director_id': director, 'director_title': '总讨论',
            'threads': [{'thread_id': worker, 'title': '核对模型', 'status': 'review'}]}
    panel = server.resource_content(server.PANEL)
    assert server.TOOLS['show_panel']['_meta']['openai/ui']['entrypoints'] == [{'type': 'thread'}]
    assert server.TOOLS['open_thread']['_meta']['ui']['visibility'] == ['app']
    assert panel['mimeType'] == server.MIME and '__DIRECTOR_' not in panel['text']
    with patch.object(server.panel_state, 'snapshot', return_value=data) as read, patch.object(subprocess, 'run') as launch:
        result = server.call({'name': 'open_thread', 'arguments': {'view_key': 'test', 'thread_id': director}, '_meta': {'threadId': worker}})
        read.assert_called_with(actor=worker, view_key='test', include_usage=False)
        assert result['structuredContent']['opened']
        assert launch.call_args.args[0] == ['/usr/bin/open', '-b', 'com.openai.codex', 'codex://threads/' + director]
        for forbidden in [other, 'https://example.com', '']:
            try:
                server.open_registered(data, forbidden)
            except ValueError:
                pass
            else:
                raise AssertionError('unexpected navigation')
        launch.assert_called_once()
        launch.side_effect = OSError()
        assert server.open_registered(data, worker) == {'opened': False, 'url': 'codex://threads/' + worker, 'title': '核对模型'}
        data['threads'][0]['status'] = 'archived'
        assert server.call({'name': 'open_thread', 'arguments': {'thread_id': worker}, '_meta': {'threadId': worker}})['isError']


if __name__ == '__main__':
    check()
