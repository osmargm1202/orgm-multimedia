import asyncio
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
from orgm_home.screen import ScreenControl
from orgm_home.protocol import ControlError

@pytest.fixture
def screen(tmp_path,monkeypatch):
    monkeypatch.setenv('ORGM_PREVIEW_DIR',str(tmp_path))
    layout={'output':'HDMI-A-1','rect':{'x':1920,'y':0,'width':1920,'height':1080},'view':42}
    async def run(*args,**kwargs):
        assert args[:4]==('grim','-c','-o','HDMI-A-1')
        assert args[args.index('-q')+1]=='55'
        Path(args[-1]).write_bytes(b'\xff\xd8test')
    return ScreenControl(run,AsyncMock(return_value=[]),AsyncMock(return_value=layout))

def test_capture_click_geometry_and_release(screen):
    async def scenario():
        frame=await screen.capture()
        assert len(frame['frame'])==32
        await screen.click(frame['frame'],.5,.5)
        assert screen.sway.await_args_list[0].args==('seat seat0 cursor set 2880 540',)
        assert screen.sway.await_args_list[-1].args==('seat seat0 cursor release BTN_LEFT',)
        screen.close('wrong-frame')
        assert screen.path.exists()
        screen.close(frame['frame'])
        assert not screen.path.exists()
        with pytest.raises(ControlError):await screen.click(frame['frame'],.5,.5)
    asyncio.run(scenario())

@pytest.mark.parametrize('point',[(float('nan'),.5),(-.1,.5),(.5,2),(True,.5),('0.5',.5)])
def test_rejects_invalid_point_before_input(screen,point):
    async def scenario():
        frame=await screen.capture()
        with pytest.raises(ControlError):await screen.click(frame['frame'],*point)
        screen.sway.assert_not_awaited()
    asyncio.run(scenario())

def test_changed_window_rejects_stale_click(screen):
    async def scenario():
        frame=await screen.capture()
        screen.context.return_value={**screen.layout,'view':99}
        with pytest.raises(ControlError,match='Cambió'):await screen.click(frame['frame'],.5,.5)
        screen.sway.assert_not_awaited()
    asyncio.run(scenario())

def test_capture_throttles_and_failed_press_still_releases(screen):
    async def scenario():
        frame=await screen.capture()
        with pytest.raises(ControlError) as error:await screen.capture()
        assert error.value.status==429
        screen.sway.side_effect=[[],ControlError('input failed'),[]]
        with pytest.raises(ControlError):await screen.click(frame['frame'],.5,.5)
        assert screen.sway.await_args_list[-1].args==('seat seat0 cursor release BTN_LEFT',)
    asyncio.run(scenario())

def test_screen_endpoints_enforce_auth_csrf_bounds_and_frame(paired,tmp_path,monkeypatch):
    client,agent,headers=paired
    assert client.post('/api/remote/pointer',json={'frame':'a'*32,'x':.5,'y':.5},headers=headers).status_code==200
    assert agent.calls[-1]==('pointer',{'frame':'a'*32,'x':.5,'y':.5})
    assert client.post('/api/remote/pointer',json={'frame':'a'*32,'x':2,'y':.5},headers=headers).status_code==422
    assert client.post('/api/remote/screen/close',json={'frame':'a'*32}).status_code==403
    assert client.get('/api/remote/screen.jpg?frame=../../secret').status_code==422
    monkeypatch.setenv('ORGM_PREVIEW_DIR',str(tmp_path));(tmp_path/'.screen.jpg').write_bytes(b'\xff\xd8private')
    assert client.get('/api/remote/screen.jpg?frame='+'a'*32).content==b'\xff\xd8private'
    client.cookies.clear()
    assert client.get('/api/remote/screen.jpg?frame='+'a'*32).status_code==401
    assert client.post('/api/remote/screen',json={}).status_code==403
