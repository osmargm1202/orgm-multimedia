"""Real HTTP, real persistent cookies; a simulated room agent never plays media."""

from dataclasses import replace
import json
import socket
import threading
import time

from fastapi.testclient import TestClient
from fastapi.responses import RedirectResponse
import pytest
import uvicorn

from orgm_home.protocol import ControlError
from orgm_home.send import RemoteSender
from orgm_home.web import create_app

VIDEO = "https://www.youtube.com/watch?v=pM9H2Pvr_-s"


@pytest.fixture
def room(configured, monkeypatch):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    settings, agent, *_ = configured
    settings = replace(settings, origins=(base,), require_access=False)
    app = create_app(settings, agent)
    seen = []

    @app.middleware("http")
    async def record(request, call_next):
        seen.append((request.method, request.url.path))
        return await call_next(request)

    @app.get("/redirect")
    async def redirect():
        return RedirectResponse(base + "/unexpected")

    @app.get("/unexpected")
    async def unexpected():
        return {"ok": True}

    server = uvicorn.Server(
        uvicorn.Config(
            app, host="127.0.0.1", port=port, log_level="error", access_log=False
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.01)
    assert server.started
    monkeypatch.setattr("orgm_home.send.notify", lambda message: None)
    with TestClient(app, base_url=base, client=("127.0.0.1", 40000)) as admin:
        login = admin.post(
            "/api/session",
            json={"token": settings.token_file.read_text()},
            headers={"Origin": base},
        )
        assert login.status_code == 200
        headers = {"Origin": base, "X-CSRF-Token": login.json()["csrf"]}

        def decide(approve=True):
            pending = admin.get("/api/admin/pairing").json()["requests"]
            assert len(pending) == 1
            result = admin.post(
                "/api/admin/pairing/" + pending[0]["id"],
                json={"approve": approve},
                headers=headers,
            )
            assert result.status_code == 200

        yield base, admin, headers, app, agent, seen, decide
    server.should_exit = True
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_first_approval_persists_across_processes_without_another_request(
    room, tmp_path
):
    base, _, _, app, agent, seen, decide = room
    state = tmp_path / "sender"
    with RemoteSender(state, base=base, sleep=lambda _: decide()) as sender:
        sender.send(VIDEO)
    assert len(app.state.sessions.devices.items) == 1
    assert (state / "device.cookies").stat().st_mode & 0o777 == 0o600
    assert state.stat().st_mode & 0o777 == 0o700

    def no_more_approval(_):
        raise AssertionError("A saved sender must not request approval again")

    with RemoteSender(state, base=base, sleep=no_more_approval) as sender:
        sender.send(VIDEO)
    assert seen.count(("POST", "/api/pairing/request")) == 1
    assert agent.calls == [
        ("open-youtube", {"url": VIDEO}),
        ("open-youtube", {"url": VIDEO}),
    ]


def test_pair_only_does_not_change_the_room(room, tmp_path):
    base, _, _, _, agent, seen, decide = room
    with RemoteSender(
        tmp_path / "sender", base=base, sleep=lambda _: decide()
    ) as sender:
        sender.authorize()
    assert not agent.calls
    assert ("POST", "/api/apps/youtube/open-url") not in seen


def test_rejection_never_sends_a_video(room, tmp_path):
    base, _, _, app, agent, _, decide = room
    with RemoteSender(
        tmp_path / "sender", base=base, sleep=lambda _: decide(False)
    ) as sender:
        with pytest.raises(ControlError) as error:
            sender.send(VIDEO)
        assert error.value.status == 403
    assert not agent.calls and not app.state.sessions.devices.items


def test_revocation_requires_new_room_approval(room, tmp_path):
    base, admin, headers, app, agent, seen, decide = room
    state = tmp_path / "sender"
    with RemoteSender(state, base=base, sleep=lambda _: decide()) as sender:
        sender.send(VIDEO)
    previous = next(iter(app.state.sessions.devices.items))
    assert (
        admin.post(
            "/api/admin/devices/" + previous + "/revoke", json={}, headers=headers
        ).status_code
        == 200
    )
    with RemoteSender(state, base=base, sleep=lambda _: decide()) as sender:
        sender.send(VIDEO)
    assert previous not in app.state.sessions.devices.items
    assert len(app.state.sessions.devices.items) == 1
    assert seen.count(("POST", "/api/pairing/request")) == 2
    assert len(agent.calls) == 2


def test_expired_request_never_sends(room, tmp_path):
    base, _, _, app, agent, _, _ = room

    def expire(_):
        for item in app.state.pairing_requests.items.values():
            item["expires"] = 0

    with RemoteSender(tmp_path / "sender", base=base, sleep=expire) as sender:
        with pytest.raises(ControlError) as error:
            sender.send(VIDEO)
        assert error.value.status == 401
    assert not agent.calls


def test_invalid_video_never_starts_network_or_pairing(room, tmp_path):
    base, _, _, _, agent, seen, _ = room
    before = list(seen)
    with RemoteSender(tmp_path / "sender", base=base) as sender:
        with pytest.raises(ControlError):
            sender.send("https://youtube.com/not-a-video")
    assert seen == before and not agent.calls


def test_redirect_is_not_followed(room, tmp_path):
    base, _, _, _, _, seen, _ = room
    with RemoteSender(tmp_path / "sender", base=base) as sender:
        with pytest.raises(ControlError) as error:
            sender.request("/redirect")
        assert error.value.status == 307
    assert ("GET", "/unexpected") not in seen


def test_concurrent_shortcut_does_not_create_duplicate_approvals(tmp_path):
    state = tmp_path / "sender"
    with RemoteSender(state):
        with pytest.raises(ControlError) as error:
            with RemoteSender(state):
                pass
        assert error.value.status == 409


def test_timeout_after_send_is_never_retried(tmp_path, monkeypatch):
    sent = []
    with RemoteSender(tmp_path / "sender") as sender:

        def request(path, body=None, csrf=None):
            if path == "/api/session":
                return {"csrf": "fixture-csrf"}
            sent.append(path)
            raise ControlError("The response timed out", 503)

        monkeypatch.setattr(sender, "request", request)
        with pytest.raises(ControlError):
            sender.send(VIDEO)
    assert sent == ["/api/apps/youtube/open-url"]


def test_pair_cli_does_not_read_selection_or_open_a_browser(monkeypatch):
    from orgm_home import send

    monkeypatch.setattr("sys.argv", ["orgm-send-youtube", "--pair"])

    def forbidden():
        raise AssertionError("Pairing must not read selection")

    monkeypatch.setattr(send, "selection", forbidden)
    paired = []
    monkeypatch.setattr(send, "transmit", lambda video=None: paired.append(video))
    send.main()
    assert paired == [None]


def test_dry_run_prints_post_plan_without_creating_credentials(monkeypatch, capsys):
    from orgm_home import send

    monkeypatch.setattr("sys.argv", ["orgm-send-youtube", "--url", VIDEO, "--dry-run"])

    def forbidden(*_):
        raise AssertionError("Dry run must not connect")

    monkeypatch.setattr(send, "transmit", forbidden)
    send.main()
    assert json.loads(capsys.readouterr().out) == {
        "method": "POST",
        "url": "https://home.or-gm.com/api/apps/youtube/open-url",
        "body": {"url": VIDEO},
    }
