import asyncio
import json
from unittest.mock import AsyncMock

from orgm_home.display import update


def test_hdmi_enables_projector_and_selects_available_boolean_profile(monkeypatch):
    outputs=[{'name':'HDMI-A-1','active':False,'modes':[{}]},{'name':'eDP-1','active':True,'modes':[{}]}]
    cards=[{'index':1,'active_profile':'output:analog-stereo','profiles':{'output:hdmi-stereo':{'available':True},'output:hdmi-stereo-extra1':{'available':False}}}]
    graph=[{'id':23,'info':{'props':{'media.class':'Audio/Sink','node.name':'alsa_output.pci.hdmi-stereo'}}}]
    async def fake(*args,**kwargs):
        if args[0]=='swaymsg' and args[-1]=='get_outputs':return json.dumps(outputs)
        if args[0]=='pactl' and args[-1]=='cards':return json.dumps(cards)
        if args[0]=='pw-dump':return json.dumps(graph)
        return ''
    command=AsyncMock(side_effect=fake);monkeypatch.setattr('orgm_home.display.command',command)
    asyncio.run(update())
    command.assert_any_await('swaymsg','output HDMI-A-1 enable')
    command.assert_any_await('swaymsg','output eDP-1 disable')
    command.assert_any_await('pactl','set-card-profile','1','output:hdmi-stereo')
    command.assert_any_await('wpctl','set-default','23')


def test_disconnect_restores_internal_display_without_hdmi_audio(monkeypatch):
    command=AsyncMock(return_value=json.dumps([{'name':'eDP-1','active':False,'modes':[{}]}]))
    monkeypatch.setattr('orgm_home.display.command',command)
    asyncio.run(update())
    command.assert_any_await('swaymsg','output eDP-1 enable')
    assert all(call.args[0]=='swaymsg' for call in command.call_args_list)
