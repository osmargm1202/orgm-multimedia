import io
import ipaddress
import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from orgm_home import cast
from orgm_home.protocol import ControlError


class Bridge:
    def __init__(self):
        self.calls = []
        self.offline = False

    def request(self, method, path, body):
        self.calls.append((method, path, body))
        if self.offline:
            raise ControlError("not ready", 503)
        base = "http://127.0.0.1:49999"
        return 201 if method == "POST" else 200, {"Location": base + "/apps/YouTube/run"}, (base + path).encode(), base


@pytest.fixture
def receiver():
    launcher, bridge = Mock(), Bridge()
    app = cast.create_app(launcher, bridge, [ipaddress.ip_network("10.0.0.0/24")], discovery=False)
    with TestClient(app, base_url="http://10.0.0.98:8766", client=("10.0.0.22", 40000)) as client:
        yield client, launcher, bridge


def test_discovery_description_does_not_launch_or_touch_native_receiver(receiver):
    client, launcher, bridge = receiver
    response = client.get("/")
    assert response.status_code == 200
    assert "ORGM Jarq" in response.text and "YouTube" in response.text
    assert response.headers["Application-URL"] == "http://10.0.0.98:8766/apps"
    launcher.activate.assert_not_called()
    assert not bridge.calls


def test_launch_activates_youtube_and_preserves_pairing_body(receiver):
    client, launcher, bridge = receiver
    response = client.post("/apps/YouTube", content="pairingCode=fixture-123&v=test")
    assert response.status_code == 201
    launcher.activate.assert_called_once_with()
    assert bridge.calls == [("POST", "/apps/YouTube", b"pairingCode=fixture-123&v=test")]
    assert response.headers["Location"] == "http://10.0.0.98:8766/apps/YouTube/run"
    assert "127.0.0.1" not in response.text


def test_status_poll_never_focuses_youtube(receiver):
    client, launcher, _bridge = receiver
    assert client.get("/apps/YouTube").status_code == 200
    launcher.activate.assert_not_called()


def test_closed_receiver_is_advertised_without_starting_it(receiver):
    client, launcher, bridge = receiver
    bridge.offline = True
    response = client.get("/apps/YouTube")
    assert response.status_code == 200 and "<state>stopped</state>" in response.text
    launcher.activate.assert_not_called()


@pytest.mark.parametrize("path", ["/apps/Netflix", "/apps/YouTube/other", "/api/status", "/apps/YouTube?url=http://127.0.0.1/"])
def test_only_youtube_protocol_paths_are_exposed(receiver, path):
    client, launcher, bridge = receiver
    assert client.post(path, content="v=fixture").status_code == 404
    launcher.activate.assert_not_called()
    assert not bridge.calls


def test_cross_site_and_oversized_requests_cannot_launch_youtube(receiver):
    client, launcher, _bridge = receiver
    assert client.post("/apps/YouTube", content="v=x", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/apps/YouTube", content="x" * 8193).status_code == 413
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 403
    launcher.activate.assert_not_called()


def test_public_or_other_lan_clients_are_rejected(receiver):
    client, _launcher, _bridge = receiver
    for address in ("192.168.1.10", "8.8.8.8"):
        with TestClient(client.app, base_url="http://10.0.0.98:8766", client=(address, 40000)) as outsider:
            assert outsider.get("/").status_code == 403


def test_discovery_only_answers_trusted_dial_searches(monkeypatch):
    reply = Mock()
    monkeypatch.setattr(cast.socket, "socket", lambda *a, **kw: reply)
    protocol = cast.Discovery([ipaddress.ip_network("10.0.0.0/24")], "test-uuid")
    protocol.addresses = {"10.0.0.98"}
    packet = f'M-SEARCH * HTTP/1.1\r\nMAN: "ssdp:discover"\r\nST: {cast.SERVICE}\r\n\r\n'.encode()
    protocol.datagram_received(packet, ("8.8.8.8", 1234))
    protocol.datagram_received(packet.replace(cast.SERVICE.encode(), b"ssdp:unknown"), ("10.0.0.22", 1234))
    reply.sendto.assert_not_called()
    protocol.datagram_received(packet, ("10.0.0.22", 1234))
    response, peer = reply.sendto.call_args.args
    assert peer == ("10.0.0.22", 1234)
    assert b"http://10.0.0.98:8766/" in response and b"uuid:test-uuid" in response
    protocol.datagram_received(packet, ("10.0.0.22", 1234))
    reply.sendto.assert_called_once()


def test_native_port_scan_only_selects_media_ephemeral_listeners(monkeypatch):
    rows = "header\n0: 00000000:A601 00000000:0000 0A 0:0 0:0 0 1100\n1: 00000000:A602 00000000:0000 0A 0:0 0:0 0 1000\n2: 00000000:1B59 00000000:0000 0A 0:0 0:0 0 1100\n"
    monkeypatch.setattr(cast.Path, "read_text", lambda _: rows)
    assert cast.native_ports() == [0xA601]


def test_launcher_pairs_once_then_reuses_its_cookie_and_csrf(monkeypatch, tmp_path):
    (tmp_path / "control-token").write_text("fixture-token-only")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    launcher = cast.Launcher()
    requests = []
    def open_request(request, timeout):
        requests.append(request)
        assert request.headers["Origin"] == "http://127.0.0.1:8765"
        if request.full_url.endswith("/api/session"):
            assert json.loads(request.data) == {"token": "fixture-token-only"}
            return io.BytesIO(b'{"csrf":"fixture-csrf"}')
        assert request.full_url.endswith("/api/apps/youtube/activate")
        assert request.headers["X-csrf-token"] == "fixture-csrf"
        return io.BytesIO(b'{"app":"youtube"}')
    launcher.client = Mock(open=open_request)
    launcher.activate()
    launcher.activate()
    assert len(requests) == 3
