import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from orgm_home.config import Settings
from orgm_home.web import create_app


class FakeAgent:
    def __init__(self):
        self.calls = []

    async def call(self, action, **data):
        self.calls.append((action, data))
        if action == "status":
            return {"session": True, "app": "home", "volume": 40, "muted": False, "title": "ORGM Home", "open": ["home"], "capabilities": {}}
        return {"done": True}


@pytest.fixture
def configured(tmp_path):
    catalog = tmp_path / "apps.json"
    catalog.write_text(json.dumps({"apps": [
        {"id": "home", "name": "ORGM Home", "workspace": "1", "type": "internal", "control": "internal", "match": "orgm-home-home"},
        {"id": "youtube", "name": "YouTube", "workspace": "2", "type": "flatpak", "appId": "rocks.shy.VacuumTube", "match": "VacuumTube"},
        {"id": "browser", "name": "Navegador", "workspace": "7", "type": "chrome", "url": "about:blank", "match": "orgm-home-browser"},
    ]}))
    token = tmp_path / "token"
    token.write_text("a-test-token-of-at-least-32-characters-long")
    settings = Settings(catalog, tmp_path / "agent.sock", token, ("http://testserver", "https://home.or-gm.com"))
    agent = FakeAgent()
    app = create_app(settings, agent)
    client = TestClient(app)
    yield settings, agent, app, client
    client.close()


@pytest.fixture
def paired(configured):
    settings, agent, app, client = configured
    response = client.post("/api/session", json={"token": settings.token_file.read_text()}, headers={"origin": "http://testserver"})
    assert response.status_code == 200, response.text
    return client, agent, {"origin": "http://testserver", "x-csrf-token": response.json()["csrf"]}
