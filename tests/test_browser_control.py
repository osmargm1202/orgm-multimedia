import asyncio
from unittest.mock import AsyncMock

import pytest

from orgm_home.browser_control import BrowserControl, PROFILES, allowed
from orgm_home.protocol import ControlError


def test_service_origins_do_not_allow_lookalikes():
    assert allowed('https://www.netflix.com/browse', PROFILES['netflix']['hosts'])
    assert not allowed('https://netflix.com.evil.test/', PROFILES['netflix']['hosts'])
    assert not allowed('http://netflix.com/browse', PROFILES['netflix']['hosts'])


def test_arbitrary_script_not_accepted():
    with pytest.raises(ControlError) as exc:
        asyncio.run(BrowserControl('netflix').act('alert(1)'))
    assert exc.value.status == 422


def test_missing_connection_reports_actionable_error(tmp_path, monkeypatch):
    monkeypatch.setattr('pathlib.Path.home', lambda: tmp_path)
    with pytest.raises(ControlError, match='Reabre'):
        asyncio.run(BrowserControl('netflix').act('right'))


def test_targets_reject_external_websockets(tmp_path, monkeypatch):
    import io
    import json
    from pathlib import Path
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    path=tmp_path/'.local/share/orgm-home/chrome/netflix'
    path.mkdir(parents=True)
    (path/'DevToolsActivePort').write_text('12345\n/devtools/browser/test')
    class Opener:
        def open(self, *args, **kwargs):
            return io.BytesIO(json.dumps([
                {'type':'page','webSocketDebuggerUrl':'ws://evil.test:12345/devtools/page/a'},
                {'type':'page','webSocketDebuggerUrl':'ws://127.0.0.1:12345/devtools/page/b'},
                {'type':'page','webSocketDebuggerUrl':'ws://127.0.0.1:3333/devtools/page/c'},
            ]).encode())
    monkeypatch.setattr('orgm_home.browser_control.build_opener', lambda *args: Opener())
    assert len(BrowserControl('netflix').targets()) == 1


def test_search_uses_authenticated_control_api(paired):
    client, agent, headers = paired
    response=client.post('/api/remote/key', json={'key':'search'}, headers=headers)
    assert response.status_code == 200
    assert agent.calls[-1] == ('key', {'key':'search'})
    assert client.post('/api/remote/key', json={'key':'search'}).status_code == 403
