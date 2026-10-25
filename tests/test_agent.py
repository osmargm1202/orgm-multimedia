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
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    result = Controller(configured[0])
    result.sway = AsyncMock(return_value=[])
    result.mute_application = AsyncMock(return_value=True)
    result.native_key = AsyncMock()
    return result


def window(app="youtube", con_id=42):
    return {
        "type": "con",
        "id": con_id,
        "pid": 99999,
        "app_id": "rocks.shy.VacuumTube" if app == "youtube" else f"orgm-home-{app}",
        "name": app,
        "marks": [],
        "focused": True,
    }


def test_existing_windows_reused_after_agent_restart(controller):
    controller.tree = AsyncMock(return_value={"nodes": [window()]})
    controller.spawn = AsyncMock()
    result = run(controller.dispatch({"action": "activate", "id": "youtube"}))
    assert result["app"] == "youtube"
    controller.spawn.assert_not_called()
    calls = [str(call.args[0]) for call in controller.sway.call_args_list]
    assert "[con_id=42] focus" in calls
    assert "[con_id=42] move container to workspace number 2" in calls
    assert all("kill" not in call for call in calls)


def test_mark_identification_survives_title_class_changes(controller):
    item = window()
    item["app_id"] = "changed"
    item["name"] = "Untrusted ; exec reboot"
    item["marks"] = ["orgm-home-youtube"]
    assert controller.identify(item).id == "youtube"


def test_home_preserves_other_windows(controller):
    controller.tree = AsyncMock(return_value={"nodes": [window("home"), window()]})
    controller.active = "youtube"
    run(controller.dispatch({"action": "home"}))
    assert all("kill" not in call.args[0] for call in controller.sway.call_args_list)
    controller.mute_application.assert_any_await(controller.apps["youtube"], True)


@pytest.mark.parametrize("separator", [b"\0", b" "])
def test_chrome_app_mode_recovered_from_own_profile(controller, monkeypatch, separator):
    controller.apps["netflix"] = App(
        id="netflix",
        name="Netflix",
        type="chrome",
        workspace="4",
        match="orgm-home-netflix",
        url="https://www.netflix.com",
    )
    item = window("netflix")
    item["app_id"] = "chrome-www.netflix.com__-Default"
    item["name"] = "A redirected login page"
    profile = Path.home() / ".local/share/orgm-home/chrome/netflix"
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda self: (
            separator.join([b"chrome", str(f"--user-data-dir={profile}").encode()])
            + b"\0"
        ),
    )
    assert controller.identify(item).id == "netflix"
    monkeypatch.setattr(
        Path, "read_bytes", lambda self: b"chrome\0--user-data-dir=/unmanaged\0"
    )
    assert controller.identify(item) is None


def test_concurrent_activation_only_launches_once(controller):
    item = None

    async def find(app):
        return item

    async def spawn(args):
        nonlocal item
        await asyncio.sleep(0.01)
        item = window()
        return AsyncMock(returncode=None)

    controller.find = find
    controller.spawn = AsyncMock(side_effect=spawn)

    async def check():
        await asyncio.gather(
            *(
                controller.dispatch({"action": "activate", "id": "youtube"})
                for _ in range(3)
            )
        )

    run(check())
    controller.spawn.assert_awaited_once_with(
        ["flatpak", "run", "rocks.shy.VacuumTube"]
    )


def test_unknown_action_and_id_do_not_invoke_tools(controller):
    controller.spawn = AsyncMock()
    for request in [
        {"action": "shell", "command": "id"},
        {"action": "activate", "id": "x;reboot"},
    ]:
        with pytest.raises(ControlError):
            run(controller.dispatch(request))
    controller.spawn.assert_not_called()
    controller.sway.assert_not_called()


def test_agent_text_passes_verbatim_to_clipboard_stdin(controller, monkeypatch):
    controller.status = AsyncMock(return_value={"capabilities": {"text": True}})
    command = AsyncMock(return_value="")
    monkeypatch.setattr("orgm_home.agent.command", command)
    run(controller.dispatch({"action": "text", "text": "--help; $(id)"}))
    command.assert_any_await(
        "wl-copy", "--type", "text/plain", input_text="--help; $(id)", capture=False
    )


def test_private_files_and_path_traversal_rejected(controller, tmp_path):
    root = tmp_path / "Videos"
    root.mkdir()
    (root / "movie.mp4").write_bytes(b"")
    (root / "private.txt").write_text("private")
    (root / "link.mp4").symlink_to(root / "private.txt")
    assert run(controller.dispatch({"action": "local-files"})) == {
        "files": ["movie.mp4"]
    }
    for name in ["../private.mp4", "link.mp4", "private.txt"]:
        with pytest.raises(ControlError):
            run(controller.dispatch({"action": "play-file", "name": name}))


def test_new_browser_url_reuses_window(controller, monkeypatch):
    controller.tree = AsyncMock(return_value={"nodes": [window("browser")]})
    controller.spawn = AsyncMock()
    command = AsyncMock(return_value="")
    monkeypatch.setattr("orgm_home.agent.command", command)
    run(controller.activate("browser", "https://example.com/"))
    controller.spawn.assert_awaited_once()
    assert "--new-window" not in controller.spawn.call_args.args[0]
    assert controller.spawn.call_args.args[0][-1] == "https://example.com/"


def test_agent_client_timeout_and_response(tmp_path):
    path = tmp_path / "agent.sock"

    async def check():
        async def handler(reader, writer):
            req = json.loads(await reader.readline())
            writer.write(
                json.dumps({"ok": True, "data": {"action": req["action"]}}).encode()
                + b"\n"
            )
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_unix_server(handler, str(path))
        async with server:
            assert await AgentClient(path).call("status") == {"action": "status"}
        with pytest.raises(ControlError):
            await AgentClient(tmp_path / "missing").call("status")

    run(check())


def test_transport_controls_are_scoped_to_current_mpris_player(controller, monkeypatch):
    controller.apps["spotify"] = App(
        "spotify",
        "flatpak",
        "Spotify",
        "3",
        appId="com.spotify.Client",
        player="spotify",
    )
    controller.status = AsyncMock(
        return_value={"app": "spotify", "capabilities": {"stop": True, "next": True}}
    )
    command = AsyncMock(return_value="")
    monkeypatch.setattr("orgm_home.agent.command", command)
    for key in ("stop", "next", "previous"):
        run(controller.dispatch({"action": "key", "key": key}))
        command.assert_any_await("playerctl", "--player=spotify", key)


def test_unavailable_transport_controls_are_rejected(controller, monkeypatch):
    controller.status = AsyncMock(
        return_value={"app": "browser", "capabilities": {"stop": False, "next": False}}
    )
    command = AsyncMock()
    monkeypatch.setattr("orgm_home.agent.command", command)
    with pytest.raises(ControlError):
        run(controller.dispatch({"action": "key", "key": "next"}))
    command.assert_not_called()


def test_brightness_controls_only_fixed_internal_backlight(controller, monkeypatch):
    command = AsyncMock(return_value="")
    monkeypatch.setattr("orgm_home.agent.command", command)
    run(controller.dispatch({"action": "brightness", "value": 35}))
    command.assert_awaited_once_with(
        "brightnessctl", "--device=intel_backlight", "set", "35%"
    )
    for value in [0, True, "35", 101]:
        with pytest.raises(ControlError):
            run(controller.dispatch({"action": "brightness", "value": value}))


def test_rotation_toggles_only_internal_output_and_preserves_choice(
    controller, monkeypatch
):
    command = AsyncMock(
        return_value=json.dumps(
            [
                {"name": "eDP-1", "transform": "normal"},
                {"name": "HDMI-A-1", "transform": "normal"},
            ]
        )
    )
    monkeypatch.setattr("orgm_home.agent.command", command)
    assert run(controller.dispatch({"action": "rotate"})) == {"rotation": "180"}
    controller.sway.assert_any_await("output eDP-1 transform 180")
    controller.sway.assert_any_await("input type:touch map_to_output eDP-1")
    assert (controller.state_dir / "rotation").read_text() == "180"
    assert not any("HDMI" in call.args[0] for call in controller.sway.call_args_list)
    command.return_value = json.dumps([{"name": "eDP-1", "transform": "180"}])
    assert run(controller.dispatch({"action": "rotate"})) == {"rotation": "normal"}


def test_late_audio_recovers_active_chrome_and_silences_hidden_app(
    controller, monkeypatch
):
    controller.apps["netflix"] = App(
        id="netflix",
        name="Netflix",
        type="chrome",
        workspace="4",
        match="orgm-home-netflix",
    )
    netflix, youtube = window("netflix", 7), window("youtube", 8)
    netflix["pid"], youtube["pid"] = 100, 200
    youtube["focused"] = False
    controller.tree = AsyncMock(return_value={"nodes": [netflix, youtube]})
    monkeypatch.setattr(controller, "ancestors", lambda pid: {str(pid)})
    streams = [
        {"index": 1, "mute": True, "properties": {"application.process.id": "100"}},
        {"index": 2, "mute": False, "properties": {"application.process.id": "200"}},
    ]
    command = AsyncMock(return_value=json.dumps(streams))
    monkeypatch.setattr("orgm_home.agent.command", command)
    run(controller.reconcile_audio())
    command.assert_any_await("pactl", "set-sink-input-mute", "1", "0")
    command.assert_any_await("pactl", "set-sink-input-mute", "2", "1")
    assert not any(call.args[0] == "wpctl" for call in command.call_args_list)
    netflix["focused"], youtube["focused"] = False, True
    streams[0]["mute"], streams[1]["mute"] = False, True
    command.return_value = json.dumps(streams)
    command.reset_mock()
    run(controller.reconcile_audio())
    command.assert_any_await("pactl", "set-sink-input-mute", "2", "0")
    assert controller.active == "youtube"


def test_background_preference_is_validated_and_persisted(controller):
    assert run(controller.dispatch({"action": "preferences"}))["background"] == "costa"
    assert run(controller.dispatch({"action": "background", "id": "bosque"})) == {
        "background": "bosque"
    }
    assert run(controller.dispatch({"action": "preferences"}))["background"] == "bosque"
    for value in ["../../etc/passwd", "https://evil.example/a.png", None]:
        with pytest.raises(ControlError):
            run(controller.dispatch({"action": "background", "id": value}))


def test_web_back_uses_real_alt_left_keycode(controller, monkeypatch):
    controller.status = AsyncMock(
        return_value={"app": "browser", "capabilities": {"keys": True}}
    )
    controller.native_key = AsyncMock()
    run(controller.dispatch({"action": "key", "key": "back"}))
    controller.native_key.assert_awaited_once_with(105, modifiers=8)


@pytest.mark.parametrize("marked_popup", [False, True])
def test_activation_prefers_original_window_over_popup(controller, marked_popup):
    original, popup = window("browser", 50), window("browser", 51)
    original["marks"] = ["orgm-home-browser"]
    if marked_popup:
        popup["marks"] = ["orgm-home-browser"]
    controller.tree = AsyncMock(return_value={"nodes": [popup, original]})
    assert run(controller.find(controller.apps["browser"]))["id"] == 50


def test_close_targets_focused_popup_and_returns_to_original(controller):
    original, popup = window("browser", 50), window("browser", 51)
    original["focused"] = False
    original["marks"] = ["orgm-home-browser"]
    controller.tree = AsyncMock(side_effect=[
        {"nodes": [popup, original]},
        {"nodes": [original]},
        {"nodes": [original]},
    ])
    controller.activate = AsyncMock(return_value={"app": "browser"})
    assert run(controller.dispatch({"action": "close"})) == {"app": "browser"}
    controller.sway.assert_awaited_once_with("[con_id=51] kill")
    controller.activate.assert_awaited_once_with("browser")


def test_close_last_window_returns_home_without_relaunching(controller):
    controller.tree = AsyncMock(side_effect=[
        {"nodes": [window("youtube", 50)]}, {"nodes": []}, {"nodes": []}
    ])
    controller.activate = AsyncMock(return_value={"app": "home"})
    run(controller.dispatch({"action": "close"}))
    controller.sway.assert_awaited_once_with("[con_id=50] kill")
    controller.activate.assert_awaited_once_with("home")


@pytest.mark.parametrize("focused", [window("home"), {**window(), "app_id": "unmanaged"}])
def test_close_never_targets_home_or_an_unmanaged_window(controller, focused):
    controller.tree = AsyncMock(return_value={"nodes": [focused]})
    with pytest.raises(ControlError):
        run(controller.dispatch({"action": "close"}))
    controller.sway.assert_not_called()


def test_chrome_popup_with_generic_app_id_belongs_to_its_profile(controller, monkeypatch):
    popup = window("browser")
    popup["app_id"] = "google-chrome"
    profile = Path.home() / ".local/share/orgm-home/chrome/browser"
    monkeypatch.setattr(Path, "read_bytes", lambda self: f"chrome\0--user-data-dir={profile}\0".encode())
    assert controller.identify(popup).id == "browser"


def test_new_chrome_popup_is_visible_over_its_fullscreen_opener(controller):
    original, popup = window("browser", 50), window("browser", 51)
    popup["focused"] = False
    controller.known_windows = {50}
    controller.tree = AsyncMock(return_value={"nodes": [original, popup]})
    run(controller.reconcile_windows())
    controller.sway.assert_any_await("[con_id=51] fullscreen enable")
    controller.sway.assert_any_await("[con_id=51] focus")
    controller.sway.reset_mock()
    run(controller.reconcile_windows())
    controller.sway.assert_not_called()


@pytest.mark.parametrize("focused_app", ["home", "youtube"])
def test_background_popup_cannot_steal_focus(controller, focused_app):
    active, popup = window(focused_app, 50), window("browser", 51)
    popup["focused"] = False
    controller.known_windows = {50}
    controller.tree = AsyncMock(return_value={"nodes": [active, popup]})
    run(controller.reconcile_windows())
    controller.sway.assert_not_called()


def test_restarting_agent_does_not_focus_existing_popups(controller):
    original, popup = window("browser", 50), window("browser", 51)
    popup["focused"] = False
    controller.tree = AsyncMock(return_value={"nodes": [original, popup]})
    run(controller.reconcile_windows())
    controller.sway.assert_not_called()


def spotify_app(controller):
    controller.apps['spotify'] = App('spotify', 'flatpak', 'Spotify', '3', appId='com.spotify.Client', player='spotify', match='spotify')
    return controller.apps['spotify']


def test_leaving_spotify_does_not_pause_or_mute_it(controller, monkeypatch):
    spotify_app(controller)
    controller.active = 'spotify'
    command = AsyncMock(return_value='')
    monkeypatch.setattr('orgm_home.agent.command', command)
    run(controller.pause_previous(controller.apps['home']))
    command.assert_not_called()
    controller.mute_application.assert_not_called()


@pytest.mark.parametrize('foreground,has_sound', [('home', False), ('browser', False), ('browser', True)])
def test_spotify_yields_only_when_selected_app_has_a_running_audio_stream(controller, monkeypatch, foreground, has_sound):
    spotify_app(controller)
    view = window(foreground, 80)
    controller.tree = AsyncMock(return_value={'nodes':[view]})
    music={'index':1,'mute':False,'corked':False,'properties':{'application.name':'Spotify'}}
    other={'index':2,'mute':True,'corked':not has_sound,'properties':{}}
    controller.stream_app = lambda stream, views: controller.apps['spotify' if stream['index']==1 else foreground]
    command=AsyncMock(return_value=json.dumps([music,other]))
    monkeypatch.setattr('orgm_home.agent.command',command)
    run(controller.reconcile_audio())
    if has_sound:
        command.assert_any_await('playerctl','--player=spotify','pause',check=False)
        command.assert_any_await('pactl','set-sink-input-mute','1','1')
        assert controller.audio_app == foreground
        command.reset_mock()
        run(controller.reconcile_audio())
        assert not any(c.args[0]=='playerctl' for c in command.call_args_list)
    else:
        assert not any(c.args[0]=='playerctl' for c in command.call_args_list)
        assert not any(c.args==('pactl','set-sink-input-mute','1','1') for c in command.call_args_list)
        assert controller.audio_app == 'spotify'
    assert not any(c.args[0]=='wpctl' for c in command.call_args_list)


def test_airplay_starts_receiver_and_prefers_stream_over_waiting_page(controller, monkeypatch):
    controller.apps['airplay']=App('airplay','airplay','AirPlay','14',url='http://127.0.0.1:8765/airplay',match='uxplay|orgm-home-airplay',control='receiver')
    waiting,stream=window('airplay',100),window('airplay',101)
    waiting['marks']=['orgm-home-airplay']
    stream['app_id']='uxplay'
    controller.tree=AsyncMock(return_value={'nodes':[waiting,stream]})
    command=AsyncMock(return_value='')
    monkeypatch.setattr('orgm_home.agent.command',command)
    assert run(controller.find(controller.apps['airplay']))['id']==101
    run(controller.activate('airplay'))
    command.assert_any_await('systemctl','--user','start','orgm-home-airplay.service')
    controller.sway.assert_any_await('[con_id=101] focus')


def test_reboot_is_scheduled_outside_session_target(controller, monkeypatch):
    command=AsyncMock(return_value='')
    monkeypatch.setattr('orgm_home.agent.command',command)
    monkeypatch.setattr('orgm_home.agent.shutil.which',lambda name:'/fixed/bin/orgm-home-reboot')
    assert run(controller.dispatch({'action':'reboot'}))=={'accepted':True}
    assert command.call_args.args[0]=='systemd-run'
    assert command.call_args.args[-1]=='/fixed/bin/orgm-home-reboot'


def test_spotify_play_from_home_keeps_home_focused(controller,monkeypatch):
    command=AsyncMock(return_value='')
    monkeypatch.setattr('orgm_home.agent.command',command)
    controller.refresh_spotify=AsyncMock()
    controller.active='home'
    run(controller.dispatch({'action':'spotify-toggle'}))
    command.assert_awaited_once_with('playerctl','--player=spotify','play-pause')
    controller.sway.assert_not_called()
    assert controller.active=='home'


def test_terminal_paste_uses_ctrl_shift_v(controller,monkeypatch):
    command=AsyncMock(return_value='')
    monkeypatch.setattr('orgm_home.agent.command',command)
    run(controller.enter_text('texto literal',terminal=True))
    controller.native_key.assert_awaited_once_with(47,modifiers=5)
