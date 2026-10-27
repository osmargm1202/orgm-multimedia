import pytest

from orgm_home.protocol import ControlError


class FakePump:
    def __init__(self):
        self.calls = []

    async def call(self, action, minutes=None):
        self.calls.append((action, minutes))
        return {"state": "on" if action == "time" else "off", "remaining_seconds": (minutes or 0) * 60, "native_timer": True}


def test_pump_cannot_be_controlled_without_pairing(configured):
    _, _, app, client = configured
    app.state.pump = FakePump()
    assert client.get("/api/pump/status").status_code == 401
    assert client.post("/api/pump/time", json={"minutes": 10}, headers={"origin": "http://127.0.0.1:8765"}).status_code == 401
    assert app.state.pump.calls == []


@pytest.mark.parametrize("minutes", [5, 10, 15, 20, 30, 40])
def test_duration_choices_and_stop_are_authenticated(paired, minutes):
    client, _, headers = paired
    pump = FakePump()
    client.app.state.pump = pump
    response = client.post("/api/pump/time", json={"minutes": minutes}, headers=headers)
    assert response.status_code == 200
    assert response.json()["remaining_seconds"] == minutes * 60
    assert client.post("/api/pump/off", json={}, headers=headers).status_code == 200
    assert pump.calls == [("time", minutes), ("down", None)]


@pytest.mark.parametrize("payload", [
    {"minutes": True}, {"minutes": "10"}, {"minutes": 0}, {"minutes": 60},
    {"minutes": 10, "entity_id": "switch.casa_switch"}, {"command": "up"},
])
def test_pump_rejects_other_commands_and_invalid_times(paired, payload):
    client, _, headers = paired
    pump = FakePump()
    client.app.state.pump = pump
    assert client.post("/api/pump/time", json=payload, headers=headers).status_code == 422
    assert pump.calls == []


def test_pump_requires_csrf_and_same_origin(paired):
    client, _, headers = paired
    pump = FakePump()
    client.app.state.pump = pump
    assert client.post("/api/pump/off", json={}, headers={"origin": "http://127.0.0.1:8765"}).status_code == 403
    assert client.post("/api/pump/off", json={}, headers={**headers, "origin": "https://evil.example"}).status_code == 403
    assert pump.calls == []


def test_pump_errors_do_not_claim_success(paired):
    client, _, headers = paired
    class OfflinePump:
        async def call(self, *_):
            raise ControlError("Bomba sin conexión", 503)
    client.app.state.pump = OfflinePump()
    response = client.post("/api/pump/time", json={"minutes": 10}, headers=headers)
    assert response.status_code == 503
    assert response.json()["detail"] == "Bomba sin conexión"
