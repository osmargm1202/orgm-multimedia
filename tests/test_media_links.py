import asyncio
from unittest.mock import AsyncMock
import pytest
from orgm_home.media_links import media_link
from orgm_home.protocol import ControlError

UUID='12345678-abcd-abcd-abcd-123456789012'

@pytest.mark.parametrize('url,app',[
 ('https://youtu.be/pM9H2Pvr_-s','youtube'),
 ('https://www.netflix.com/title/81234567?trackId=1','netflix'),
 ('https://www.netflix.com/es/watch/81234567','netflix'),
 ('https://www.netflix.com/browse?jbv=81234567','netflix'),
 ('https://www.disneyplus.com/es-419/browse/entity-'+UUID,'disney-plus'),
 ('https://www.disneyplus.com/play/'+UUID,'disney-plus'),
 ('https://www.disneyplus.com/movies/title/abcdefgh1234','disney-plus'),
 ('https://play.max.com/movie/'+UUID,'max'),
 ('https://www.crunchyroll.com/es/watch/G12345678/title','crunchyroll'),
 ('https://www.primevideo.com/detail/B012345678','prime-video'),
 ('https://open.spotify.com/intl-es/track/0123456789012345678901?si=discard','spotify'),
])
def test_content_services(url,app):
    target=media_link(url)
    assert target.app==app
    assert target.identity
    assert media_link(target.url)==target

@pytest.mark.parametrize('url',[
 'https://www.netflix.com/','https://www.netflix.com/search?q=123',
 'https://www.netflix.com.evil.test/title/81234567','https://user:pw@www.netflix.com/title/81234567',
 'https://www.netflix.com:8443/title/81234567','http://www.netflix.com/title/81234567',
 'https://127.0.0.1/title/81234567','https://www.disneyplus.com/account',
 'https://www.disneyplus.com/browse/entity-not-a-uuid',
 'https://www.netflix.com/title/81234567\nreboot','https://www.netflix.com/title/81234567\\x',
 'https://www.netflix.com/title/81234567 https://youtu.be/pM9H2Pvr_-s',
 'https://www.primevideo.com/detail/B012345678/%2Faccount','spotify:track:0123456789012345678901',
])
def test_invalid_or_unrelated_content_rejected(url):
    with pytest.raises(ControlError):media_link(url)

def test_spotify_native_uri():
    assert media_link('https://open.spotify.com/track/0123456789012345678901').spotify_uri=='spotify:track:0123456789012345678901'

def test_generic_api_uses_detected_app_and_rejects_invalid_without_dispatch(configured,paired):
    settings,agent,app,_=configured
    # The test catalogue has YouTube; a missing service cannot mutate the room.
    client,_,headers=paired
    assert client.post('/api/media/open-url',json={'url':'https://www.netflix.com/title/81234567'},headers=headers).status_code==404
    checkpoint=len(agent.calls)
    assert client.post('/api/media/open-url',json={'url':'https://127.0.0.1/private'},headers=headers).status_code==422
    assert len(agent.calls)==checkpoint
    assert client.post('/api/media/open-url',json={'url':'https://youtu.be/pM9H2Pvr_-s'},headers=headers).status_code==200
    assert agent.calls[-1]==('open-media',{'url':'https://www.youtube.com/watch?v=pM9H2Pvr_-s'})
    assert client.post('/api/media/open-url',json={'url':'https://youtu.be/pM9H2Pvr_-s'}).status_code==403

def test_generic_get_does_not_send_or_pair(configured):
    _,agent,_,client=configured
    r=client.get('/media/link/?key=https://www.netflix.com/title/81234567')
    assert r.status_code==200
    assert not agent.calls

BROWSER_URL='https://redirectus.net/us/us.html?p=us&d=redirectus.net&id=1817&v=20260917a&ref=gostreameast.one,,'

def test_unknown_web_link_keeps_all_query_and_fragment():
    target=media_link(BROWSER_URL+'#fragment')
    assert target.app=='browser'
    assert target.url==BROWSER_URL+'#fragment'
    assert media_link('http://example.com/path?q=1').app=='browser'

@pytest.mark.parametrize('url',['https://localhost/path','https://10.0.0.98/','https://100.122.22.48/', 'https://169.254.169.254/latest','file:///etc/passwd','javascript:alert(1)','https://user:password@example.com/','https://example.com:8765/'])
def test_browser_fallback_rejects_private_or_unsafe_destinations(url):
    with pytest.raises(ControlError):media_link(url)

def test_browser_endpoint_checks_dns_before_dispatch(paired,monkeypatch):
    client,agent,headers=paired
    check=AsyncMock(side_effect=ControlError('private resolution',422))
    monkeypatch.setattr('orgm_home.web.validate_url',check)
    checkpoint=len(agent.calls)
    assert client.post('/api/media/open-url',json={'url':BROWSER_URL},headers=headers).status_code==422
    assert len(agent.calls)==checkpoint

def test_browser_endpoint_dispatches_validated_link(paired,monkeypatch):
    client,agent,headers=paired
    monkeypatch.setattr('orgm_home.web.validate_url',AsyncMock(return_value=BROWSER_URL))
    response=client.post('/api/media/open-url',json={'url':BROWSER_URL},headers=headers)
    assert response.status_code==200
    assert response.json()['app']=='browser'
    assert agent.calls[-1]==('open-media',{'url':BROWSER_URL})
