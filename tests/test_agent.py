import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from orgm_home.agent import Controller
from orgm_home.config import App
from orgm_home.protocol import AgentClient, ControlError


def run(awaitable):
    return asyncio.run(awaitable)


@pytest.fixture
def controller(configured, tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path))
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    result = Controller(configured[0])
    result.sway = AsyncMock(return_value=[])
    result.mute_application = AsyncMock(return_value=True)
    return result


def window(app='youtube', con_id=42):
    return {'type':'con','id':con_id,'pid':99999,'app_id': 'rocks.shy.VacuumTube' if app=='youtube' else f'orgm-home-{app}', 'name':app, 'marks':[], 'focused':True}


def test_existing_windows_reused_after_agent_restart(controller):
    controller.tree = AsyncMock(return_value={'nodes':[window()]})
    controller.spawn = AsyncMock()
    result = run(controller.dispatch({'action':'activate','id':'youtube'}))
    assert result['app']=='youtube'
    controller.spawn.assert_not_called()
    calls = [str(call.args[0]) for call in controller.sway.call_args_list]
    assert '[con_id=42] focus' in calls
    assert '[con_id=42] move container to workspace number 2' in calls
    assert all('kill' not in call for call in calls)


def test_mark_identification_survives_title_class_changes(controller):
    item=window()
    item['app_id']='changed'
    item['name']='Untrusted ; exec reboot'
    item['marks']=['orgm-home-youtube']
    assert controller.identify(item).id=='youtube'


def test_home_preserves_other_windows(controller):
    controller.tree=AsyncMock(return_value={'nodes':[window('home'), window()]})
    controller.active='youtube'
    run(controller.dispatch({'action':'home'}))
    assert all('kill' not in call.args[0] for call in controller.sway.call_args_list)
    controller.mute_application.assert_any_await(controller.apps['youtube'],True)


def test_concurrent_activation_only_launches_once(controller):
    item=None
    async def find(app): return item
    async def spawn(args):
        nonlocal item
        await asyncio.sleep(.01)
        item=window()
        return AsyncMock(returncode=None)
    controller.find=find
    controller.spawn=AsyncMock(side_effect=spawn)
    async def check():
        await asyncio.gather(*(controller.dispatch({'action':'activate','id':'youtube'}) for _ in range(3)))
    run(check())
    controller.spawn.assert_awaited_once_with(['flatpak','run','rocks.shy.VacuumTube'])


def test_unknown_action_and_id_do_not_invoke_tools(controller):
    controller.spawn=AsyncMock()
    for request in [{'action':'shell','command':'id'},{'action':'activate','id':'x;reboot'}]:
        with pytest.raises(ControlError):run(controller.dispatch(request))
    controller.spawn.assert_not_called()
    controller.sway.assert_not_called()


def test_agent_text_uses_argv_terminator(controller,monkeypatch):
    controller.status=AsyncMock(return_value={'capabilities':{'text':True}})
    command=AsyncMock(return_value='')
    monkeypatch.setattr('orgm_home.agent.command',command)
    run(controller.dispatch({'action':'text','text':'--help; $(id)'}))
    command.assert_awaited_once_with('wtype','-d','20','-s','150','--','--help; $(id)',timeout=25)


def test_private_files_and_path_traversal_rejected(controller,tmp_path):
    root=tmp_path/'Videos';root.mkdir()
    (root/'movie.mp4').write_bytes(b'')
    (root/'private.txt').write_text('private')
    (root/'link.mp4').symlink_to(root/'private.txt')
    assert run(controller.dispatch({'action':'local-files'}))=={'files':['movie.mp4']}
    for name in ['../private.mp4','link.mp4','private.txt']:
        with pytest.raises(ControlError):run(controller.dispatch({'action':'play-file','name':name}))


def test_new_browser_url_reuses_window(controller,monkeypatch):
    controller.tree=AsyncMock(return_value={'nodes':[window('browser')]})
    controller.spawn=AsyncMock()
    command=AsyncMock(return_value='')
    monkeypatch.setattr('orgm_home.agent.command',command)
    run(controller.activate('browser','https://example.com/'))
    controller.spawn.assert_not_called()
    command.assert_any_await('wtype','-d','10','-s','150','--','https://example.com/',timeout=25)


def test_agent_client_timeout_and_response(tmp_path):
    path=tmp_path/'agent.sock'
    async def check():
        async def handler(reader,writer):
            req=json.loads(await reader.readline())
            writer.write(json.dumps({'ok':True,'data':{'action':req['action']}}).encode()+b'\n')
            await writer.drain();writer.close();await writer.wait_closed()
        server=await asyncio.start_unix_server(handler,str(path))
        async with server:
            assert await AgentClient(path).call('status')=={'action':'status'}
        with pytest.raises(ControlError):await AgentClient(tmp_path/'missing').call('status')
    run(check())
