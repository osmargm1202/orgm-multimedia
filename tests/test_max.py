import asyncio
import json
import socket

import pytest
from fastapi.testclient import TestClient

from orgm_home.protocol import ControlError
from orgm_home.urls import validate_max_url
from orgm_home.web import create_app


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))])


@pytest.mark.parametrize("url", ["https://play.max.com/video/fixture", "https://play.hbomax.com/episode/fixture", "https://www.max.com/movies/fixture"])
def test_valid_max_links(public_dns, url):
    assert asyncio.run(validate_max_url(url)) == url


@pytest.mark.parametrize("url", ["https://max.com.evil.example/video", "https://evilmax.com/", "http://play.max.com/", "file:///etc/passwd", "https://user:pass@max.com/", None])
def test_unrelated_or_unsafe_max_links(public_dns, url):
    with pytest.raises(ControlError):
        asyncio.run(validate_max_url(url))


def test_max_link_requires_pairing_and_csrf_and_targets_max(configured, public_dns):
    settings, agent, _app, _client = configured
    data = json.loads(settings.catalog.read_text())
    data["apps"].append({"id": "max", "name": "Max", "type": "chrome", "workspace": "5", "url": "https://play.max.com"})
    settings.catalog.write_text(json.dumps(data))
    with TestClient(create_app(settings, agent)) as client:
        url = "https://play.max.com/video/fixture"
        route = "/api/apps/max/open-url"
        headers = {"Origin": "http://testserver"}
        assert client.post(route, json={"url": url}, headers=headers).status_code == 401
        session = client.post("/api/session", json={"token": settings.token_file.read_text()}, headers=headers).json()
        assert client.post(route, json={"url": url}, headers=headers).status_code == 403
        headers["X-CSRF-Token"] = session["csrf"]
        assert client.post(route, json={"url": "https://evil.example/"}, headers=headers).status_code == 422
        assert not agent.calls
        assert client.post(route, json={"url": url}, headers=headers).status_code == 200
        assert agent.calls == [("open-max", {"url": url})]
