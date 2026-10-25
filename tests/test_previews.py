import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

from orgm_home.previews import capture, versions


def test_capture_uses_window_identifier_without_focus_and_keeps_unchanged_version(tmp_path,monkeypatch):
    monkeypatch.setenv('ORGM_PREVIEW_DIR',str(tmp_path))
    async def run(*args,**kwargs):
        assert args[:3]==('grim','-T','window-123')
        Path(args[-1]).write_bytes(b'\xff\xd8test-image')
    asyncio.run(capture('youtube','window-123',run))
    before=versions(['youtube'])
    asyncio.run(capture('youtube','window-123',run))
    assert versions(['youtube'])==before
    assert list(tmp_path.iterdir())==[tmp_path/'youtube.jpg']


def test_capture_ignores_disappearing_window_and_never_replaces_valid_preview(tmp_path,monkeypatch):
    monkeypatch.setenv('ORGM_PREVIEW_DIR',str(tmp_path))
    (tmp_path/'browser.jpg').write_bytes(b'\xff\xd8valid')
    asyncio.run(capture('browser','closed',AsyncMock(return_value='')))
    assert (tmp_path/'browser.jpg').read_bytes()==b'\xff\xd8valid'
    assert len(list(tmp_path.iterdir()))==1


def test_previews_require_pairing_and_only_catalog_ids_are_readable(configured,paired,tmp_path,monkeypatch):
    monkeypatch.setenv('ORGM_PREVIEW_DIR',str(tmp_path))
    client,_,headers=paired
    (tmp_path/'youtube.jpg').write_bytes(b'\xff\xd8private')
    response=client.get('/api/previews/youtube',headers=headers)
    assert response.status_code==200 and response.content==b'\xff\xd8private'
    assert client.get('/api/previews/unknown',headers=headers).status_code==404
    client.cookies.clear()
    assert client.get('/api/previews/youtube').status_code==401
