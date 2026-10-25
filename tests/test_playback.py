import asyncio
from pathlib import Path

from orgm_home.config import App
from orgm_home.playback import Playback


def backend(tmp_path, monkeypatch):
    apps={a.id:a for a in [App('home','internal','Home','1'),App('youtube','flatpak','YouTube','2',appId='rocks.shy.VacuumTube'),App('spotify','flatpak','Spotify','3',appId='com.spotify.Client'),App('netflix','chrome','Netflix','4'),App('browser','chrome','Browser','7')]}
    views=[{'pid':111,'app':'netflix'},{'pid':222,'app':'browser'}]
    states={'chromium.instance111':'Paused','chromium.instance222':'Playing','chromium.instance3':'Playing','spotify':'Playing'}
    calls=[]
    async def command(*args,**kw):
        calls.append(args)
        if args[0]=='busctl':return '\n'.join(['org.mpris.MediaPlayer2.chromium.instance111 111 chrome','org.mpris.MediaPlayer2.chromium.instance222 222 chrome','org.mpris.MediaPlayer2.chromium.instance3 333 xdg-dbus-proxy','org.mpris.MediaPlayer2.spotify 444 xdg-dbus-proxy'])
        name=args[1].split('=',1)[1]
        if args[2]=='status':return states[name]
        states[name]={'pause':'Paused','play':'Playing'}[args[2]]
        return ''
    real_read=Path.read_text
    def read(path,*args,**kw):
        if str(path)=='/proc/333/cgroup':return '0::/app.slice/app-flatpak-rocks.shy.VacuumTube-42.scope'
        if str(path)=='/proc/444/cgroup':return '0::/app.slice/app-flatpak-com.spotify.Client-43.scope'
        return real_read(path,*args,**kw)
    monkeypatch.setattr(Path,'read_text',read)
    playback=Playback(tmp_path,apps,command,lambda w:apps[w['app']],lambda pid:{pid},None)
    return playback,apps,views,states,calls


def test_pauses_all_background_video_players_but_preserves_spotify_and_manual_pause(tmp_path,monkeypatch):
    playback,apps,views,states,calls=backend(tmp_path,monkeypatch)
    views += [{'pid':555,'app':'youtube'},{'pid':666,'app':'spotify'}]
    asyncio.run(playback.background('home',views))
    assert states=={'chromium.instance111':'Paused','chromium.instance222':'Paused','chromium.instance3':'Paused','spotify':'Playing'}
    assert playback.paused=={'chromium.instance222':'browser','chromium.instance3':'youtube'}
    assert playback.path.stat().st_mode & 0o777==0o600
    asyncio.run(playback.resume(apps['netflix'],views))
    assert states['chromium.instance111']=='Paused'
    asyncio.run(playback.resume(apps['youtube'],views))
    assert states['chromium.instance3']=='Playing'
    assert not any('--all-players' in call for call in calls)
    # Agent restarts retain which pauses belong to the launcher.
    reloaded=Playback(tmp_path,apps,playback.run,playback.identify,playback.ancestors,None)
    asyncio.run(reloaded.resume(apps['browser'],views))
    assert states['chromium.instance222']=='Playing'


def test_foreground_video_keeps_playing_and_stale_closed_app_is_forgotten(tmp_path,monkeypatch):
    playback,apps,views,states,calls=backend(tmp_path,monkeypatch)
    asyncio.run(playback.background('browser',views))
    assert states['chromium.instance222']=='Playing'
    playback.paused['chromium.old']='youtube'
    asyncio.run(playback.background('browser',views))
    assert 'chromium.old' not in playback.paused


def test_mpv_only_resumes_playback_that_the_launcher_paused(tmp_path):
    app=App('videos','mpv','Videos','8');state={'pause':False,'idle-active':False}
    async def mpv(args):
        if args[0]=='get_property':return state[args[1]]
        state[args[1]]=args[2]
    async def command(*args,**kw):return ''
    policy=Playback(tmp_path,{'videos':app},command,lambda w:app,lambda pid:set(),mpv)
    asyncio.run(policy.pause(app,[]));assert state['pause'] and policy.mpv_paused
    asyncio.run(policy.resume(app,[]));assert not state['pause']
    state['pause']=True
    asyncio.run(policy.pause(app,[]));asyncio.run(policy.resume(app,[]));assert state['pause']
