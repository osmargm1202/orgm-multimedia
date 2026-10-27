from dataclasses import replace
import json
import stat

import pytest
from fastapi.testclient import TestClient

from orgm_home.pairing import Devices, PairingRequests, Sessions
from orgm_home.protocol import ControlError
from orgm_home.web import create_app

LOCAL = "http://127.0.0.1:8765"
PUBLIC = "https://home.or-gm.com"


@pytest.fixture
def screen(configured):
    settings, agent, _app, _client = configured
    settings = replace(settings, origins=(LOCAL, PUBLIC), require_access=False)
    app = create_app(settings, agent)
    with TestClient(app, base_url=LOCAL, client=("127.0.0.1", 50000)) as screen:
        result = screen.post(
            "/api/session",
            json={"token": settings.token_file.read_text()},
            headers={"Origin": LOCAL},
        )
        assert result.status_code == 200
        headers = {"Origin": LOCAL, "X-CSRF-Token": result.json()["csrf"]}
        # Requests arriving through Nginx also have a loopback peer; Host must not grant local privileges.
        with TestClient(app, base_url=PUBLIC, client=("127.0.0.1", 50001)) as phone:
            yield screen, headers, phone, settings, agent


def request(phone, name="iPhone de Osmar"):
    result = phone.post(
        "/api/pairing/request",
        json={"name": name},
        headers={"Origin": PUBLIC, "User-Agent": "iPhone Safari"},
    )
    assert result.status_code == 200
    return result


def approve(screen, headers):
    pending = screen.get("/api/admin/pairing").json()["requests"]
    assert pending
    response = screen.post(
        "/api/admin/pairing/" + pending[0]["id"],
        json={"approve": True},
        headers=headers,
    )
    assert response.status_code == 200
    return pending[0]["id"]


def pair(screen, headers, phone):
    request(phone)
    approve(screen, headers)
    result = phone.get("/api/pairing/status")
    assert result.status_code == 200 and result.json()["status"] == "approved"
    return {"Origin": PUBLIC, "X-CSRF-Token": result.json()["csrf"]}


def test_room_approval_grants_persistent_individual_access(screen):
    local, headers, phone, settings, agent = screen
    assert phone.get("/api/status").status_code == 401
    response = request(phone)
    assert set(response.json()) == {"status", "name", "expires_in"}
    assert (
        "HttpOnly" in response.headers["set-cookie"]
        and "Secure" in response.headers["set-cookie"]
    )
    assert phone.get("/api/pairing/status").json()["status"] == "pending"
    assert phone.get("/api/status").status_code == 401
    approve(local, headers)
    response = phone.get("/api/pairing/status")
    assert response.json()["status"] == "approved"
    assert "Max-Age=34560000" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    assert phone.get("/api/status").status_code == 200
    csrf = response.json()["csrf"]
    assert (
        phone.get("/api/session").json()["csrf"] == csrf
    )  # session refresh must not invalidate other UI scripts
    assert (
        phone.post("/api/remote/home", json={}, headers={"Origin": PUBLIC}).status_code
        == 403
    )
    assert (
        phone.post(
            "/api/remote/home",
            json={},
            headers={"Origin": PUBLIC, "X-CSRF-Token": csrf},
        ).status_code
        == 200
    )
    path = settings.token_file.with_name("devices.json")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert len(json.loads(path.read_text())) == 1
    assert settings.token_file.read_text() not in response.text + path.read_text()


def test_authorizations_survive_restart_and_revoke_immediately(screen):
    local, headers, phone, settings, agent = screen
    pair(local, headers, phone)
    cookie = phone.cookies.get("orgm_session")
    new_app = create_app(settings, agent)
    with TestClient(new_app, base_url=PUBLIC) as after:
        after.cookies.set("orgm_session", cookie)
        assert after.get("/api/status").status_code == 200
        with TestClient(
            new_app, base_url=LOCAL, client=("127.0.0.1", 50100)
        ) as computer:
            login = computer.post(
                "/api/session",
                json={"token": settings.token_file.read_text()},
                headers={"Origin": LOCAL},
            )
            local_headers = {"Origin": LOCAL, "X-CSRF-Token": login.json()["csrf"]}
            devices = computer.get("/api/admin/devices").json()["devices"]
            assert devices[0]["name"] == "iPhone de Osmar"
            assert (
                computer.post(
                    "/api/admin/devices/" + devices[0]["id"] + "/revoke",
                    json={},
                    headers=local_headers,
                ).status_code
                == 200
            )
        assert after.get("/api/status").status_code == 401
        assert after.get("/api/session").status_code == 401
    assert create_app(settings, agent).state.sessions.verify(cookie) is None


def test_rejection_and_expiry_do_not_authorize(screen):
    local, headers, phone, *_ = screen
    request(phone)
    pending = local.get("/api/admin/pairing").json()["requests"][0]
    assert (
        local.post(
            "/api/admin/pairing/" + pending["id"],
            json={"approve": False},
            headers=headers,
        ).status_code
        == 200
    )
    assert phone.get("/api/pairing/status").json()["status"] == "rejected"
    assert phone.get("/api/status").status_code == 401
    request(phone)
    for item in local.app.state.pairing_requests.items.values():
        item["expires"] = 0
    assert phone.get("/api/pairing/status").json()["status"] == "expired"
    assert local.get("/api/admin/pairing").json() == {"requests": []}
    assert local.get("/api/admin/devices").json() == {"devices": []}
    assert (
        local.post(
            "/api/admin/pairing/" + pending["id"],
            json={"approve": True},
            headers=headers,
        ).status_code
        == 409
    )


def test_remote_cannot_approve_list_revoke_or_use_local_secret(screen):
    local, headers, phone, settings, _ = screen
    request(phone)
    pending = local.get("/api/admin/pairing").json()["requests"][0]
    path = "/api/admin/pairing/" + pending["id"]
    assert (
        phone.post(path, json={"approve": True}, headers={"Origin": PUBLIC}).status_code
        == 401
    )
    assert (
        phone.post(
            "/api/session",
            json={"token": settings.token_file.read_text()},
            headers={"Origin": PUBLIC},
        ).status_code
        == 401
    )
    approve(local, headers)
    response = phone.get("/api/pairing/status")
    remote_headers = {"Origin": PUBLIC, "X-CSRF-Token": response.json()["csrf"]}
    device = local.get("/api/admin/devices").json()["devices"][0]
    for route in ["/api/admin/pairing", "/api/admin/devices"]:
        assert phone.get(route).status_code == 403
    assert (
        phone.post(path, json={"approve": True}, headers=remote_headers).status_code
        == 403
    )
    assert (
        phone.post(
            "/api/admin/devices/" + device["id"] + "/revoke",
            json={},
            headers=remote_headers,
        ).status_code
        == 403
    )
    # Replaying a genuine local cookie through the public proxy must also fail.
    phone.cookies.clear()
    phone.cookies.set("orgm_session", local.cookies.get("orgm_session"))
    assert phone.get("/api/admin/devices").status_code == 401


def test_decision_requires_local_session_csrf_and_boolean(screen):
    local, headers, phone, *_ = screen
    request(phone)
    identity = local.get("/api/admin/pairing").json()["requests"][0]["id"]
    route = "/api/admin/pairing/" + identity
    assert (
        local.post(route, json={"approve": True}, headers={"Origin": LOCAL}).status_code
        == 403
    )
    assert (
        local.post(route, json={"approve": "false"}, headers=headers).status_code == 422
    )
    assert (
        phone.post(
            "/api/pairing/request",
            json={"name": "test"},
            headers={"Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    local.cookies.clear()
    assert local.post(route, json={"approve": True}, headers=headers).status_code == 401


def test_pending_request_is_idempotent_and_never_discloses_others(screen):
    local, headers, phone, *_ = screen
    request(phone)
    request(phone)
    assert len(local.get("/api/admin/pairing").json()["requests"]) == 1
    assert phone.get("/api/admin/pairing").status_code == 401
    with TestClient(local.app, base_url=PUBLIC) as other:
        assert other.get("/api/pairing/status").json() == {"status": "expired"}
        assert other.get("/api/status").status_code == 401


def test_approved_grant_cannot_be_claimed_twice_or_after_revocation(screen):
    local, headers, phone, *_ = screen
    request(phone)
    pending_cookie = phone.cookies.get("orgm_pairing")
    approve(local, headers)
    assert phone.get("/api/pairing/status").json()["status"] == "approved"
    with TestClient(local.app, base_url=PUBLIC) as replay:
        replay.cookies.set("orgm_pairing", pending_cookie, path="/api/pairing")
        assert replay.get("/api/pairing/status").json()["status"] == "claimed"
        assert replay.get("/api/status").status_code == 401
    request(phone)
    approve(local, headers)
    new_device = local.get("/api/admin/devices").json()["devices"][-1]
    # Revoke both to make this independent of equal timestamp ordering.
    for device in local.get("/api/admin/devices").json()["devices"]:
        local.post(
            "/api/admin/devices/" + device["id"] + "/revoke", json={}, headers=headers
        )
    assert phone.get("/api/pairing/status").json()["status"] == "revoked"
    assert new_device


def test_names_and_queue_are_bounded(screen):
    local, headers, phone, *_ = screen
    for name in ["x" * 65, "hello\nworld", "hello\x00world"]:
        assert (
            phone.post(
                "/api/pairing/request", json={"name": name}, headers={"Origin": PUBLIC}
            ).status_code
            == 422
        )
    registry = Devices(local.app.state.sessions.devices.path)
    pending = PairingRequests(registry)
    for _ in range(3):
        pending.request("", "<script>untrusted</script>", "iPhone · Safari")
    with pytest.raises(ControlError) as error:
        pending.request("", "Fourth", "Browser")
    assert error.value.status == 429


def test_remote_cookie_is_not_expired_by_short_local_session_age(tmp_path, monkeypatch):
    registry = Devices(tmp_path / "devices.json")
    identity = registry.add("Phone", "Browser")
    sessions = Sessions("x" * 40, 10, registry)
    remote, _ = sessions.issue(identity)
    local, _ = sessions.issue()
    import time

    now = time.time()
    monkeypatch.setattr("orgm_home.pairing.time.time", lambda: now + 50000)
    assert sessions.verify(remote)
    assert sessions.verify(local) is None
    assert sessions.verify(remote + "x") is None
    registry.revoke(identity)
    assert sessions.verify(remote) is None
