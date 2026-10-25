import asyncio
from pathlib import Path

import pytest

from orgm_home.protocol import ControlError
from orgm_home.wifi import Wifi, fields


def test_nmcli_escaped_network_names():
    assert fields(r'*:Casa\: sala\\wifi:86:WPA2') == ['*', 'Casa: sala\\wifi', '86', 'WPA2']


def backend(tmp_path, failure=False):
    calls, secrets = [], []

    async def run(*args, **kwargs):
        calls.append(args)
        if args[-2:] == ('device', 'status'):
            return 'wlp2s0:wifi:connected:Casa\n'
        if 'IN-USE,SSID,SIGNAL,SECURITY' in args:
            return '*:Casa:83:WPA2\n:Vecinos:92:WPA2\n:Casa:40:WPA2\n'
        if 'passwd-file' in args:
            path = Path(args[args.index('passwd-file') + 1])
            secrets.append((path, path.read_text(), path.stat().st_mode & 0o777))
            if failure:
                raise ControlError('Activation failed')
        return ''

    return Wifi(run, tmp_path/'runtime'), calls, secrets


def test_status_deduplicates_and_prioritizes_connected_network(tmp_path):
    wifi, _, _ = backend(tmp_path)
    result=asyncio.run(wifi.status())
    assert result['connected']
    assert [n['ssid'] for n in result['networks']] == ['Casa','Vecinos']
    assert result['networks'][0]['signal']==83


@pytest.mark.parametrize('failure',[False,True])
def test_password_uses_private_temporary_file_and_never_command_arguments(tmp_path,failure):
    wifi,calls,secrets=backend(tmp_path,failure)
    password='una clave: con símbolos $()'
    if failure:
        with pytest.raises(ControlError):
            asyncio.run(wifi.connect('Casa',password))
    else:
        asyncio.run(wifi.connect('Casa',password))
    assert secrets and secrets[0][1]==f'802-11-wireless-security.psk:{password}\n'
    assert secrets[0][2]==0o600
    assert not secrets[0][0].exists()
    assert all(password not in arg for args in calls for arg in args)
    assert any('delete' in args for args in calls)==failure


def test_saved_connection_does_not_create_or_modify_profiles(tmp_path):
    wifi,calls,secrets=backend(tmp_path)
    asyncio.run(wifi.connect('Casa'))
    assert not secrets
    assert not any('add' in args or 'modify' in args for args in calls)


@pytest.mark.parametrize('ssid,password',[('', ''),('x'*33,''),('Casa','abc\npassword'),(None,''),('Casa',object())])
def test_invalid_wifi_requests_do_not_invoke_networkmanager(tmp_path,ssid,password):
    wifi,calls,_=backend(tmp_path)
    with pytest.raises(ControlError):
        asyncio.run(wifi.connect(ssid,password))
    assert not calls


def test_open_network_creates_only_a_user_owned_profile(tmp_path):
    calls=[]
    async def run(*args, **kwargs):
        calls.append(args)
        if args[-2:] == ('device','status'):
            return 'wlp2s0:wifi:disconnected:\n'
        if 'IN-USE,SSID,SIGNAL,SECURITY' in args:
            return ':Invitados:70:--\n'
        return ''
    asyncio.run(Wifi(run,tmp_path).connect('Invitados'))
    add=next(args for args in calls if 'add' in args)
    assert add[add.index('connection.permissions')+1]=='user:media'
    assert not any('passwd-file' in args for args in calls)
