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
