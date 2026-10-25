from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from orgm_home.web import PairingCodes, create_app


def test_short_code_is_single_use_and_expires():
    codes = PairingCodes()
    first = codes.issue()
    assert len(first['code']) == 6 and first['code'].isdigit() and first['expires_in'] == 120
    assert codes.redeem(first['code'])
    assert not codes.redeem(first['code'])
    second = codes.issue()
    codes.expires = 0
    assert not codes.redeem(second['code'])


def test_wrong_guesses_are_globally_bounded_for_each_invitation():
    codes = PairingCodes()
    issued = codes.issue()['code']
    wrong = '000000' if issued != '000000' else '111111'
    for _ in range(10):
        assert not codes.redeem(wrong)
    assert not codes.redeem(issued)


def test_generating_another_code_replaces_the_previous_one(monkeypatch):
    sequence = iter([123456, 654321])
    monkeypatch.setattr('orgm_home.web.secrets.randbelow', lambda _: next(sequence))
    codes = PairingCodes()
    first, second = codes.issue()['code'], codes.issue()['code']
    assert not codes.redeem(first) and codes.redeem(second)


@pytest.fixture
def screen(configured):
    settings, agent, _app, _client = configured
    settings = replace(settings, origins=('http://127.0.0.1:8765', 'https://home.or-gm.com'), require_access=False)
    app = create_app(settings, agent)
    with TestClient(app, base_url='http://127.0.0.1:8765', client=('127.0.0.1', 50000)) as client:
        headers = {'Origin': 'http://127.0.0.1:8765'}
        session = client.post('/api/session', json={'token': settings.token_file.read_text()}, headers=headers)
        assert session.status_code == 200
        headers['X-CSRF-Token'] = session.json()['csrf']
        yield client, headers, settings


def test_local_screen_issues_code_without_disclosing_the_room_key(screen):
    client, headers, settings = screen
    response = client.post('/api/pairing/code', json={}, headers=headers)
    assert response.status_code == 200
    assert set(response.json()) == {'code', 'expires_in'}
    assert settings.token_file.read_text() not in response.text
    with TestClient(client.app, base_url='https://home.or-gm.com', client=('127.0.0.1', 50001)) as phone:
        request_headers = {'Origin': 'https://home.or-gm.com'}
        login = phone.post('/api/session', json={'token': response.json()['code']}, headers=request_headers)
        assert login.status_code == 200
        assert 'Secure' in login.headers['set-cookie'] and 'HttpOnly' in login.headers['set-cookie']
        assert phone.get('/api/status').status_code == 200
        assert phone.post('/api/session', json={'token': response.json()['code']}, headers=request_headers).status_code == 401


def test_remote_paired_mando_cannot_generate_codes_even_through_loopback_proxy(screen):
    client, _headers, settings = screen
    with TestClient(client.app, base_url='https://home.or-gm.com', client=('127.0.0.1', 50001)) as phone:
        headers = {'Origin': 'https://home.or-gm.com'}
        login = phone.post('/api/session', json={'token': settings.token_file.read_text()}, headers=headers)
        assert login.status_code == 200
        headers['X-CSRF-Token'] = login.json()['csrf']
        assert phone.post('/api/pairing/code', json={}, headers=headers).status_code == 403


def test_code_generation_requires_session_and_csrf(screen):
    client, headers, _settings = screen
    assert client.post('/api/pairing/code', json={}, headers={'Origin': headers['Origin']}).status_code == 403
    client.cookies.clear()
    assert client.post('/api/pairing/code', json={}, headers=headers).status_code == 401
