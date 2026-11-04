from unittest.mock import Mock

import pytest

from orgm_home import touch


@pytest.mark.parametrize('action',['poweroff','reboot'])
def test_power_leaves_wayland_before_stopping_the_computer(monkeypatch,action):
    run=Mock()
    monkeypatch.setattr(touch.subprocess,'run',run)
    getattr(touch,action)()
    assert len(run.call_args_list)==2
    first,last=run.call_args_list
    assert first.args[0][:3]==['systemctl','--user','stop']
    assert 'orgm-home-session.target' in first.args[0]
    assert 'xdg-desktop-portal-wlr.service' in first.args[0]
    assert last.args[0]==['systemctl',action,'--no-block']


@pytest.mark.parametrize('mode,enabled',[('on',True),('off',False)])
def test_local_touch_mode_uses_explicit_boolean(monkeypatch,tmp_path,mode,enabled):
    from unittest.mock import AsyncMock
    agent=Mock(call=AsyncMock(return_value={'touch_always_on':enabled}))
    monkeypatch.setattr(touch.sys,'argv',['orgm-home-control','touch-always-on',mode])
    monkeypatch.setattr(touch.Settings,'from_env',lambda:Mock(agent_socket=tmp_path/'agent.sock'))
    monkeypatch.setattr(touch,'AgentClient',lambda _:agent)
    touch.control()
    agent.call.assert_awaited_once_with('touch-always-on',enabled=enabled)


@pytest.mark.parametrize('args',[[],['true'],['on','off']])
def test_local_touch_mode_rejects_unknown_arguments(monkeypatch,args):
    monkeypatch.setattr(touch.sys,'argv',['orgm-home-control','touch-always-on',*args])
    client=Mock()
    monkeypatch.setattr(touch,'AgentClient',client)
    with pytest.raises(SystemExit):
        touch.control()
    client.assert_not_called()
