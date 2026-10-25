import asyncio
import json
from unittest.mock import AsyncMock, Mock

from orgm_home.display import DisplayManager, select_hdmi_audio


def test_hdmi_mirrors_fixed_touch_screen_without_disabling_it(monkeypatch):
    outputs = [
        {"name": "HDMI-A-1", "active": False, "modes": [{}]},
        {"name": "eDP-1", "active": True, "modes": [{}]},
    ]

    async def fake(*args, **kwargs):
        if args[0] == "swaymsg" and args[-1] == "get_outputs":
            return json.dumps(outputs)
        return ""

    command = AsyncMock(side_effect=fake)
    process = Mock(returncode=None)
    process.wait = AsyncMock()
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr("orgm_home.display.command", command)
    monkeypatch.setattr("orgm_home.display.asyncio.create_subprocess_exec", spawn)
    monkeypatch.setattr("orgm_home.display.select_hdmi_audio", AsyncMock())
    manager = DisplayManager()
    asyncio.run(manager.update())
    command.assert_any_await(
        "swaymsg", "output eDP-1 enable mode 1920x1080 scale 1 position 0 0 power on"
    )
    command.assert_any_await(
        "swaymsg",
        "output HDMI-A-1 enable mode 1920x1080 scale 1 position 1920 0 power on",
    )
    command.assert_any_await("swaymsg", "input type:touch map_to_output eDP-1")
    assert spawn.call_args.args[:3] == ("wl-mirror", "--fullscreen-output", "HDMI-A-1")
    assert spawn.call_args.args[-1] == "eDP-1"
    assert not any(" disable" in str(call) for call in command.call_args_list)
    outputs[:] = [{"name": "eDP-1", "active": True, "modes": [{}]}]
    asyncio.run(manager.update())
    process.terminate.assert_called_once()
    assert manager.mirror is None


def test_hdmi_audio_selects_available_boolean_profile(monkeypatch):
    cards = [
        {
            "index": 1,
            "active_profile": "output:analog-stereo",
            "profiles": {
                "output:hdmi-stereo": {"available": True},
                "output:hdmi-stereo-extra1": {"available": False},
            },
        }
    ]
    graph = [
        {
            "id": 23,
            "info": {
                "props": {
                    "media.class": "Audio/Sink",
                    "node.name": "alsa_output.pci.hdmi-stereo",
                }
            },
        }
    ]

    async def fake(*args, **kwargs):
        if args[0] == "pactl":
            return json.dumps(cards)
        if args[0] == "pw-dump":
            return json.dumps(graph)
        return ""

    command = AsyncMock(side_effect=fake)
    monkeypatch.setattr("orgm_home.display.command", command)
    asyncio.run(select_hdmi_audio())
    command.assert_any_await("pactl", "set-card-profile", "1", "output:hdmi-stereo")
    command.assert_any_await("wpctl", "set-default", "23")


def test_no_hdmi_keeps_internal_panel_and_does_not_launch_mirror(monkeypatch):
    command = AsyncMock(
        return_value=json.dumps([{"name": "eDP-1", "active": False, "modes": [{}]}])
    )
    spawn = AsyncMock()
    monkeypatch.setattr("orgm_home.display.command", command)
    monkeypatch.setattr("orgm_home.display.asyncio.create_subprocess_exec", spawn)
    asyncio.run(DisplayManager().update())
    command.assert_any_await(
        "swaymsg", "output eDP-1 enable mode 1920x1080 scale 1 position 0 0 power on"
    )
    spawn.assert_not_called()


def test_unrelated_outputs_are_not_reconfigured(monkeypatch):
    command = AsyncMock(
        return_value=json.dumps([{"name": "DP-1", "active": True, "modes": [{}]}])
    )
    monkeypatch.setattr("orgm_home.display.command", command)
    asyncio.run(DisplayManager().update())
    command.assert_awaited_once_with("swaymsg", "-r", "-t", "get_outputs")


def test_hdmi_reconnect_moves_existing_audio_and_unmutes_only_once(monkeypatch):
    async def fake(*args, **kwargs):
        if args[-1] == 'cards':
            return '[]'
        if args[-1] == 'sink-inputs':
            return '[{"index": 7}]'
        if args[0] == 'pw-dump':
            return json.dumps([{'id': 23, 'info': {'props': {'media.class': 'Audio/Sink', 'node.name': 'alsa_output.pci.hdmi-stereo'}}}])
        return ''
    command = AsyncMock(side_effect=fake)
    monkeypatch.setattr('orgm_home.display.command', command)
    asyncio.run(select_hdmi_audio(reconnect=True))
    command.assert_any_await('wpctl', 'set-mute', '23', '0')
    command.assert_any_await('pactl', 'move-sink-input', '7', 'alsa_output.pci.hdmi-stereo')
    command.reset_mock()
    asyncio.run(select_hdmi_audio(reconnect=False))
    assert not any('set-mute' in call.args or 'move-sink-input' in call.args for call in command.call_args_list)
