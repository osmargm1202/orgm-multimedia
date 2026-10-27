import asyncio
from dataclasses import replace
import socket
import time

from fastapi.testclient import TestClient
import pytest

from orgm_home.protocol import ControlError
from orgm_home.urls import validate_url
from orgm_home.web import Access, Sessions, create_app


def test_remote_requires_pairing_and_origin(configured):
    settings, agent, app, client = configured
    assert client.get("/api/apps").status_code == 401
    assert (
        client.post(
            "/api/session", json={"token": settings.token_file.read_text()}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/session",
            json={"token": settings.token_file.read_text()},
            headers={"origin": "https://evil.example"},
        ).status_code
        == 403
    )
    assert not agent.calls


def test_csrf_and_catalog_allowlist(paired):
    client, agent, headers = paired
    assert (
        client.post(
            "/api/apps/youtube/activate",
            json={},
            headers={"origin": "http://127.0.0.1:8765"},
        ).status_code
        == 403
    )
    assert (
        client.post("/api/apps/unknown/activate", json={}, headers=headers).status_code
        == 404
    )
    assert (
        client.post("/api/apps/youtube/activate", json={}, headers=headers).status_code
        == 200
    )
    assert agent.calls == [("activate", {"id": "youtube"})]


@pytest.mark.parametrize(
    "payload", [{"key": "exec reboot"}, {"key": "ok", "command": "id"}]
)
def test_no_arbitrary_commands(paired, payload):
    client, agent, headers = paired
    assert (
        client.post("/api/remote/key", json=payload, headers=headers).status_code == 422
    )
    assert not agent.calls


@pytest.mark.parametrize(
    "payload", [{"text": "hello\nreboot"}, {"text": "x" * 1001}, {"text": 12}]
)
def test_text_boundaries(paired, payload):
    client, agent, headers = paired
    assert (
        client.post("/api/remote/text", json=payload, headers=headers).status_code
        == 422
    )
    assert not agent.calls


def test_text_treated_as_data(paired):
    client, agent, headers = paired
    text = "-; $(touch /tmp/never) 'hola'"
    assert (
        client.post(
            "/api/remote/text", json={"text": text}, headers=headers
        ).status_code
        == 200
    )
    assert agent.calls == [("text", {"text": text})]


def test_switch_requires_pairing_and_csrf(configured, paired):
    client, agent, headers = paired
    assert client.post('/api/apps/youtube/switch', json={}, headers={'origin':'http://127.0.0.1:8765'}).status_code == 403
    assert not agent.calls
    assert client.post('/api/apps/unknown/switch', json={}, headers=headers).status_code == 404
    assert not agent.calls
    assert client.post('/api/apps/youtube/switch', json={}, headers=headers).status_code == 200
    assert agent.calls == [('switch-app', {'id':'youtube'})]
    client.cookies.clear()
    assert client.post('/api/apps/youtube/switch', json={}, headers=headers).status_code == 401


def test_remote_previous_element_is_a_fixed_key(paired):
    client, agent, headers = paired
    assert client.post('/api/remote/key',json={'key':'shift-tab'},headers=headers).status_code == 200
    assert agent.calls == [('key', {'key':'shift-tab'})]


@pytest.mark.parametrize(
    "payload",
    [
        {"value": -1},
        {"value": 101},
        {"value": True},
        {"delta": 100},
        {"value": 30, "delta": 5},
        {},
    ],
)
def test_volume_limits(paired, payload):
    client, agent, headers = paired
    assert (
        client.post("/api/audio/volume", json=payload, headers=headers).status_code
        == 422
    )
    assert not agent.calls


def test_public_fails_closed_without_access(configured):
    settings, agent, app, _ = configured
    with TestClient(app, base_url="https://home.or-gm.com") as client:
        assert client.get("/api/apps").status_code == 503
        response = client.post(
            "/api/session",
            json={"token": settings.token_file.read_text()},
            headers={"origin": "https://home.or-gm.com"},
        )
        assert response.status_code == 503
    assert not agent.calls


def test_invalid_access_signature_rejected(configured, monkeypatch):
    import jwt

    settings, agent, _, _ = configured
    settings = replace(
        settings,
        access_team="https://family.cloudflareaccess.com",
        access_aud="home-aud",
    )
    monkeypatch.setattr(
        "jwt.PyJWKClient.get_signing_key_from_jwt",
        lambda *args: (_ for _ in ()).throw(jwt.InvalidSignatureError()),
    )
    with TestClient(
        create_app(settings, agent), base_url="https://home.or-gm.com"
    ) as client:
        assert (
            client.get(
                "/api/apps", headers={"cf-access-jwt-assertion": "forged"}
            ).status_code
            == 401
        )


def test_access_claims_signature_and_authorization(configured, monkeypatch):
    from cryptography.hazmat.primitives.asymmetric import rsa
    from types import SimpleNamespace
    import jwt

    settings = replace(
        configured[0],
        access_team="https://family.cloudflareaccess.com",
        access_aud="home-aud",
        access_emails=("family@example.com",),
    )
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(
        "jwt.PyJWKClient.get_signing_key_from_jwt",
        lambda *args: SimpleNamespace(key=private.public_key()),
    )
    access = Access(settings)
    claims = {
        "iss": settings.access_team,
        "aud": "home-aud",
        "sub": "user",
        "email": "family@example.com",
        "exp": int(time.time()) + 100,
        "iat": int(time.time()),
    }
    asyncio.run(access.verify(jwt.encode(claims, private, algorithm="RS256")))
    for changes in [
        {"aud": "other-app"},
        {"iss": "https://evil.example"},
        {"exp": 1},
        {"email": "intruder@example.com"},
    ]:
        with pytest.raises(ControlError):
            asyncio.run(
                access.verify(
                    jwt.encode({**claims, **changes}, private, algorithm="RS256")
                )
            )


def test_signed_sessions_expire_and_reject_tampering():
    sessions = Sessions("x" * 40, 10)
    cookie, csrf = sessions.issue()
    assert sessions.verify(cookie) == csrf
    assert sessions.verify(cookie + "x") is None
    old = f"{int(time.time()) - 11}.{csrf}"
    assert sessions.verify(f"{old}.{sessions.sign(old)}") is None


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "javascript:alert(1)",
        "http://127.0.0.1/",
        "http://localhost/",
        "https://a.local/",
        "https://a.ts.net/",
        "https://user:password@example.com/",
        "https://example.com:8765",
        "https://example.com\\@127.0.0.1",
        "https://example.com/\n",
    ],
)
def test_unsafe_urls(paired, url):
    client, agent, headers = paired
    assert (
        client.post(
            "/api/browser/open-url", json={"url": url}, headers=headers
        ).status_code
        == 422
    )
    assert not agent.calls


def test_dns_private_and_mixed_answers_rejected(monkeypatch):
    async def fake(*args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.1", 443)),
        ]

    async def run():
        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", fake)
        with pytest.raises(ControlError):
            await validate_url("https://public.example.com/")

    asyncio.run(run())


def test_public_url_allowed(monkeypatch):
    async def fake(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 443))]

    async def run():
        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", fake)
        assert (
            await validate_url("https://example.com/watch?v=hello")
            == "https://example.com/watch?v=hello"
        )

    asyncio.run(run())


def test_body_limits_host_headers_and_pointer(paired):
    client, _, headers = paired
    assert (
        client.get("/api/health", headers={"host": "evil.example"}).status_code == 400
    )
    assert (
        client.post(
            "/api/remote/text",
            content=b"x" * 9000,
            headers={**headers, "content-type": "application/json"},
        ).status_code
        == 413
    )
    assert (
        client.post("/api/remote/pointer", json={}, headers=headers).status_code == 409
    )
    response = client.get("/")
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"


def test_login_rate_limit(configured):
    client = configured[3]
    for _ in range(5):
        assert (
            client.post(
                "/api/session",
                json={"token": "wrong" * 10},
                headers={"origin": "http://127.0.0.1:8765"},
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/session",
            json={"token": "wrong" * 10},
            headers={"origin": "http://127.0.0.1:8765"},
        ).status_code
        == 429
    )


def test_private_tailnet_mode_still_requires_pairing_and_csrf(configured):
    settings, agent, _, _ = configured
    settings = replace(settings, require_access=False)
    with TestClient(
        create_app(settings, agent), base_url="https://home.or-gm.com"
    ) as client:
        assert client.get("/api/apps").status_code == 401
        remote_app = client.app
        device = remote_app.state.sessions.devices.add('Teléfono de prueba', 'iPhone · Safari')
        cookie, csrf = remote_app.state.sessions.issue(device)
        client.cookies.set('orgm_session', cookie)
        response = client.get('/api/session')
        assert response.status_code == 200
        assert (
            client.post(
                "/api/apps/youtube/activate",
                json={},
                headers={"origin": "https://home.or-gm.com"},
            ).status_code
            == 403
        )
        headers = {
            "origin": "https://home.or-gm.com",
            "x-csrf-token": response.json()["csrf"],
        }
        assert (
            client.post(
                "/api/apps/youtube/activate", json={}, headers=headers
            ).status_code
            == 200
        )


@pytest.mark.parametrize("value", [0, 4, 101, True, "35", 35.5])
def test_brightness_rejects_invalid_and_blackout_values(paired, value):
    client, agent, headers = paired
    assert (
        client.post(
            "/api/display/brightness", json={"value": value}, headers=headers
        ).status_code
        == 422
    )
    assert not agent.calls


def test_brightness_forwards_only_percentage(paired):
    client, agent, headers = paired
    assert (
        client.post(
            "/api/display/brightness", json={"value": 35}, headers=headers
        ).status_code
        == 200
    )
    assert agent.calls == [("brightness", {"value": 35})]


def test_admin_routes_still_require_csrf(paired):
    client, agent, headers = paired
    for route in ["admin/reboot", "admin/poweroff", "admin/restart-launcher", "display/rotate"]:
        assert (
            client.post(
                "/api/" + route, json={}, headers={"origin": "http://127.0.0.1:8765"}
            ).status_code
            == 403
        )
    assert not agent.calls


def test_poweroff_requires_a_paired_session(paired):
    client,agent,headers=paired
    assert client.post('/api/admin/poweroff',json={},headers=headers).status_code==200
    assert agent.calls==[('poweroff',{})]
    client.cookies.clear()
    assert client.post('/api/admin/poweroff',json={},headers=headers).status_code==401
    assert agent.calls==[('poweroff',{})]


def test_close_by_id_requires_pairing_and_csrf(configured, paired):
    client, agent, headers = paired
    assert client.post("/api/apps/youtube/close", json={}, headers={"origin": "http://127.0.0.1:8765"}).status_code == 403
    assert client.post("/api/apps/unknown/close", json={}, headers=headers).status_code == 404
    assert not agent.calls
    assert client.post("/api/apps/youtube/close", json={}, headers=headers).status_code == 200
    assert agent.calls == [("close-app", {"id": "youtube"})]
