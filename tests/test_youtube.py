import asyncio
from unittest.mock import AsyncMock
from urllib.parse import quote

import pytest

from orgm_home.youtube import canonical_url
from orgm_home.protocol import ControlError
from pathlib import Path
from orgm_home.agent import Controller


@pytest.fixture
def controller(configured, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    result = Controller(configured[0])
    result.sway = AsyncMock(return_value=[])
    result.mute_application = AsyncMock(return_value=True)
    result.native_key = AsyncMock()
    return result


ID = "pM9H2Pvr_-s"
VIDEO = "https://www.youtube.com/watch?v=" + ID


@pytest.mark.parametrize(
    "link",
    [
        VIDEO,
        "https://youtu.be/" + ID + "?si=tracking",
        "https://www.youtube.com/shorts/" + ID,
        "https://m.youtube.com/live/" + ID + "/",
        "https://www.youtube.com/embed/" + ID,
        "  " + VIDEO + "\n",
    ],
)
def test_exact_youtube_video_canonicalization(link):
    assert canonical_url(link) == VIDEO


@pytest.mark.parametrize(
    "link",
    [
        None,
        "",
        "Hello " + VIDEO,
        VIDEO + " extra",
        "https://youtube.com.evil.example/watch?v=" + ID,
        "https://youtube.com@evil.example/watch?v=" + ID,
        "https://evil.example@youtube.com/watch?v=" + ID,
        "http://youtube.com/watch?v=" + ID,
        "file:///etc/passwd",
        "https://www.youtube.com/",
        "https://youtube.com/playlist?list=PLx",
        "https://youtube.com/watch?v=short",
        VIDEO + "&v=dQw4w9WgXcQ",
        "https://youtu.be/" + ID + "/extra",
        "https://youtube.com:9443/watch?v=" + ID,
        VIDEO + "\x00",
        VIDEO + "\\evil",
        VIDEO + "&t=bad",
        VIDEO + "&t=1&t=2",
    ],
)
def test_non_video_or_ambiguous_selection_is_rejected(link):
    with pytest.raises(ControlError):
        canonical_url(link)


def test_start_time_preserved_without_playlist_or_tracking():
    assert canonical_url(VIDEO + "&list=PLx&si=tracking&t=1m20s") == VIDEO + "&t=80"


def test_api_requires_pairing_and_csrf_and_never_calls_agent_for_invalid_link(
    configured, paired
):
    client, agent, headers = paired
    assert (
        client.post(
            "/api/apps/youtube/open-url",
            json={"url": VIDEO},
            headers={"Origin": headers["origin"]},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/apps/youtube/open-url",
            json={"url": "https://www.youtube.com/"},
            headers=headers,
        ).status_code
        == 422
    )
    assert not agent.calls
    response = client.post(
        "/api/apps/youtube/open-url",
        json={"url": "https://www.youtube.com/shorts/" + ID},
        headers=headers,
    )
    assert response.status_code == 200 and response.json()["url"] == VIDEO
    assert agent.calls == [("open-youtube", {"url": VIDEO})]
    client.cookies.clear()
    assert (
        client.post(
            "/api/apps/youtube/open-url", json={"url": VIDEO}, headers=headers
        ).status_code
        == 401
    )


def test_quick_link_get_never_mutates_and_previews_frames_do_not_auto_send(paired):
    client, agent, _headers = paired
    route = "/youtube/link/?key=" + quote(VIDEO, safe="")
    response = client.get(route)
    assert response.status_code == 200 and 'data-youtube-auto="no"' in response.text
    response = client.get(
        route,
        headers={
            "Sec-Fetch-User": "?1",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Dest": "iframe",
        },
    )
    assert 'data-youtube-auto="no"' in response.text
    response = client.get(
        route,
        headers={
            "Sec-Fetch-User": "?1",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Dest": "document",
        },
    )
    assert 'data-youtube-auto="yes"' in response.text
    assert (
        "Cache-Control" in response.headers
        and response.headers["Cache-Control"] == "no-store"
    )
    assert not agent.calls
    assert 'data-youtube-link=""' in client.get("/youtube/link/?key=not-a-url").text
    assert (
        'data-youtube-link=""'
        in client.get(route + "&key=" + quote(VIDEO, safe="")).text
    )


def test_existing_receiver_reuses_window_and_forwards_deeplink(controller, monkeypatch):
    from test_agent import window

    controller.tree = AsyncMock(return_value={"nodes": [window()]})
    controller.spawn = AsyncMock()
    command = AsyncMock(return_value="")
    monkeypatch.setattr("orgm_home.agent.command", command)
    result = asyncio.run(
        controller.dispatch(
            {"action": "open-youtube", "url": "https://www.youtube.com/shorts/" + ID}
        )
    )
    assert result["app"] == "youtube"
    controller.spawn.assert_not_called()
    command.assert_any_await(
        "flatpak",
        "run",
        "rocks.shy.VacuumTube",
        VIDEO,
        "--fullscreen",
        timeout=12,
    )
    assert not any("kill" in call.args[0] for call in controller.sway.call_args_list)


def test_invalid_deeplink_preserves_foreground_and_does_not_spawn(controller):
    controller.activate = AsyncMock()
    with pytest.raises(ControlError):
        asyncio.run(
            controller.dispatch(
                {"action": "open-youtube", "url": "https://example.com/"}
            )
        )
    controller.activate.assert_not_called()


def test_shortcut_invalid_selection_never_opens_browser(monkeypatch):
    from orgm_home import send

    monkeypatch.setattr("sys.argv", ["orgm-send-youtube"])
    monkeypatch.setattr(send, "selection", lambda: "This is not a link")
    opened = []
    monkeypatch.setattr(
        send.subprocess, "run", lambda args, **kwargs: opened.append(args)
    )
    with pytest.raises(SystemExit) as error:
        send.main()
    assert error.value.code == 2
    assert all(call[0] != "xdg-open" for call in opened)


def test_shortcut_valid_selection_passes_one_encoded_url_to_browser(monkeypatch):
    from orgm_home import send

    monkeypatch.setattr("sys.argv", ["orgm-send-youtube"])
    monkeypatch.setattr(
        send, "selection", lambda: "https://www.youtube.com/shorts/" + ID
    )
    opened = []
    monkeypatch.setattr(
        send.subprocess, "run", lambda args, **kwargs: opened.append(args)
    )
    send.main()
    assert opened == [
        [
            "xdg-open",
            "https://home.or-gm.com/youtube/link/?key=" + quote(VIDEO, safe=""),
        ]
    ]


def test_closed_receiver_launches_once_with_exact_deeplink(controller, monkeypatch):
    from test_agent import window

    current = None

    async def find(app):
        return current

    async def spawn(args):
        nonlocal current
        current = window()
        return AsyncMock(returncode=None)

    controller.find = find
    controller.tree = AsyncMock(
        side_effect=lambda: {"nodes": [current] if current else []}
    )
    controller.spawn = AsyncMock(side_effect=spawn)
    monkeypatch.setattr("orgm_home.agent.command", AsyncMock(return_value=""))
    result = asyncio.run(controller.dispatch({"action": "open-youtube", "url": VIDEO}))
    assert result["app"] == "youtube"
    controller.spawn.assert_awaited_once_with(
        ["flatpak", "run", "rocks.shy.VacuumTube", VIDEO, "--fullscreen"]
    )


@pytest.mark.parametrize(
    "text,valid", [(VIDEO, True), (VIDEO + " extra", False), ("", False)]
)
def test_selection_reads_primary_to_eof_without_clipboard_fallback(
    tmp_path, monkeypatch, text, valid
):
    from orgm_home import send
    import sys
    import json

    executable = tmp_path / "wl-paste"
    executable.write_text(
        "#!"
        + sys.executable
        + '\nimport sys,time\nassert sys.argv[1:]==["--primary","--no-newline"]\ntext='
        + json.dumps(text)
        + "\nsys.stdout.write(text[:30]);sys.stdout.flush();time.sleep(.02);sys.stdout.write(text[30:])\n"
    )
    executable.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("WAYLAND_DISPLAY", "fixture")
    selected = send.selection()
    assert selected == text
    if valid:
        assert canonical_url(selected) == VIDEO
    else:
        with pytest.raises(ControlError):
            canonical_url(selected)
