import asyncio
from unittest.mock import AsyncMock

import pytest
from starlette.websockets import WebSocketDisconnect
from orgm_home.live_screen import LiveScreen
from orgm_home.protocol import ControlError
from test_screen import screen


def test_live_start_close_and_expiry(tmp_path, monkeypatch):
    path=tmp_path/'live.sock'
    monkeypatch.setattr('orgm_home.live_screen.SOCKET', str(path))
    monkeypatch.setattr('orgm_home.live_screen.Path.is_socket', lambda _:True)
    run=AsyncMock()
    live=LiveScreen(run)
    async def scenario():
        first=(await live.start())['viewer'];second=(await live.start())['viewer']
        assert first!=second
        with pytest.raises(ControlError):await live.start()
        await live.close(first)
        assert run.await_args.args==('systemctl','--user','start','orgm-home-live.service')
        live.renew(second)
        live.viewers[second]-=26
        await live.expire()
        assert not live.viewers
        assert run.await_args.args==('systemctl','--user','stop','orgm-home-live.service')
        with pytest.raises(ControlError):live.renew(second)
    asyncio.run(scenario())


def test_live_rejects_unauthorized_and_foreign_origins_before_start(configured):
    _,agent,_,client=configured
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('ws://127.0.0.1:8765/api/remote/live',headers={'origin':'http://127.0.0.1:8765'}):pass
    assert agent.calls==[]


def test_live_rejects_cross_origin_even_with_cookie(paired):
    client,agent,_=paired
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('ws://127.0.0.1:8765/api/remote/live',headers={'origin':'https://evil.example'}):pass
    assert not any(action=='live-start' for action,_ in agent.calls)


def test_live_relays_binary_and_releases_viewer(paired,monkeypatch):
    client,agent,headers=paired
    original=agent.call
    async def call(action,**data):
        if action=='live-start':agent.calls.append((action,data));return {'viewer':'a'*32}
        return await original(action,**data)
    agent.call=call
    class Writer:
        def __init__(self):self.data=b'';self.closed=False
        def write(self,data):self.data+=data
        async def drain(self):pass
        def close(self):self.closed=True
        async def wait_closed(self):pass
    writer=Writer()
    async def connect(_):
        reader=asyncio.StreamReader();reader.feed_data(b'RFB 003.008\n')
        return reader,writer
    monkeypatch.setattr('orgm_home.web.asyncio.open_unix_connection',connect)
    with client.websocket_connect('ws://127.0.0.1:8765/api/remote/live',headers={'origin':headers['origin']},subprotocols=['binary']) as socket:
        assert socket.receive_bytes()==b'RFB 003.008\n'
        socket.send_bytes(b'RFB 003.008\n')
    assert writer.closed
    assert ('live-close',{'viewer':'a'*32}) in agent.calls


def test_live_pointer_context_never_captures_a_frame(screen):
    async def scenario():
        frame=await screen.prepare()
        assert not screen.path.exists()
        await screen.click(frame['frame'],.5,.5)
        screen.context.return_value={**screen.layout,'view':88}
        with pytest.raises(ControlError):await screen.click(frame['frame'],.5,.5)
    asyncio.run(scenario())
