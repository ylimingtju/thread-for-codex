"""Run with Python from the plugin directory: python -B tests/test_panel_server.py."""
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
    assert set(server.TOOLS) == {'enqueue_task','show_entry','show_receipt','show_panel','open_panel_link',
                                 'snapshot','open_thread','set_thread_status'}
    assert "const groups = [['waiting','等你回复'],['running','进行中'],['review','已回复'],['completed','已完成']]" in panel['text']
    assert 'id="ready-drawer"' in panel['text'] and '未派工旧串' in panel['text']
    for removed in ('tab-info','card-roles','card-decisions','save_worker_roles','save_decisions','start_project_materials'):
        assert removed not in panel['text']
    assert server.TOOLS['show_panel']['_meta']['openai/ui']['entrypoints'] == [{'type': 'thread'}]
    assert server.TOOLS['open_thread']['_meta']['ui']['visibility'] == ['app']
    assert panel['mimeType'] == server.MIME and '__DIRECTOR_' not in panel['text']
    link = server.panel_state.PANEL_LINK
    meta = server.TOOLS['open_panel_link']['_meta']
    assert meta['ui'] == {'resourceUri': server.PANEL, 'visibility': ['app']}
    assert meta['openai/ui']['entrypoints'] == [{'type': 'deepLink', 'patterns': [link]}]
    request = {'name': 'open_panel_link', 'arguments': {'url': link}, '_meta': {'threadId': director}}
    with patch.object(server.panel_state, 'snapshot', return_value={**data, 'role': 'director'}) as read:
        assert server.handle('tools/call', request)['structuredContent']['director_id'] == director
        read.assert_called_once_with(actor=director, view_key=None, include_usage=True)
        read.reset_mock()
        assert server.call({**request, '_meta': {}})['isError']
        for args in ({'url': link + '?director=' + director}, {'url': link, 'view_key': 'other'}, {}):
            try:
                server.call({**request, 'arguments': args})
            except server.ProtocolError as exc:
                assert exc.code == -32602
            else:
                raise AssertionError('unexpected panel link accepted')
        read.assert_not_called()
        assert server.call({**request, '_meta': {'threadId': other}})['isError']
        read.return_value = data
        denied = server.call({**request, '_meta': {'threadId': worker}})
        assert denied['isError'] and 'structuredContent' not in denied
    with patch.object(server.sys, 'platform', 'darwin'), patch.object(
        server.panel_state, 'snapshot', return_value=data
    ) as read, patch.object(subprocess, 'run') as launch:
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

    with patch.object(server.sys, 'platform', 'win32'), patch.object(server.os, 'startfile', create=True) as launch:
        result = server.open_registered(data, director)
        assert result == {'opened': True, 'url': 'codex://threads/' + director, 'title': '总讨论'}
        try:
            server.open_registered(data, worker)
        except ValueError:
            pass
        else:
            raise AssertionError('archived thread opened')
        launch.assert_called_once_with('codex://threads/' + director)
        launch.side_effect = OSError()
        assert not server.open_registered(data, director)['opened']



if __name__ == '__main__':
    check()
