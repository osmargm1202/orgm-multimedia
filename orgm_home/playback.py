"""Pause the actual MPRIS player belonging to each application, never all players."""

import contextlib
import json
from pathlib import Path

from .protocol import ControlError

PREFIX = 'org.mpris.MediaPlayer2.'


class Playback:
    def __init__(self, state_dir, apps, run, identify, ancestors, mpv):
        self.path = state_dir / 'playback.json'
        self.apps, self.run, self.identify = apps, run, identify
        self.ancestors, self.mpv = ancestors, mpv
        self.paused = {}
        self.mpv_paused = False
        with contextlib.suppress(OSError, ValueError, TypeError):
            saved = json.loads(self.path.read_text())
            self.paused = {name: app for name, app in saved.get('players', {}).items() if isinstance(name, str) and app in apps}
            self.mpv_paused = saved.get('mpv') is True

    def save(self):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'players': self.paused, 'mpv': self.mpv_paused}))
        temporary.chmod(0o600)
        temporary.replace(self.path)

    async def players(self, views):
        try:
            raw = await self.run('busctl', '--user', 'list', '--no-legend', '--no-pager', timeout=3)
        except ControlError:
            return {}
        result = {}
        for line in raw.splitlines():
            row = line.split()
            if len(row) < 2 or not row[0].startswith(PREFIX) or not row[1].isdigit():
                continue
            pid = row[1]
            lineage = self.ancestors(pid)
            app = next((self.identify(view) for view in views if str(view.get('pid')) in lineage and self.identify(view)), None)
            if app is None:
                # Flatpak publishes MPRIS via an xdg-dbus-proxy sibling of the
                # application. Its cgroup identifies the real sandbox, even
                # when Electron calls itself chromium.instance3 inside it.
                with contextlib.suppress(OSError):
                    group = Path(f'/proc/{pid}/cgroup').read_text()
                    app = next((a for a in self.apps.values() if a.type == 'flatpak' and f'app-flatpak-{a.appId}-' in group), None)
            if app:
                result[row[0][len(PREFIX):]] = app
        return result

    async def pause(self, app, views, players=None):
        if app.id in {'home', 'spotify'}:
            return
        if app.type == 'mpv':
            with contextlib.suppress(ControlError, OSError, TimeoutError):
                if not await self.mpv(['get_property', 'idle-active']) and not await self.mpv(['get_property', 'pause']):
                    await self.mpv(['set_property', 'pause', True])
                    self.mpv_paused = True
                    self.save()
        players = await self.players(views) if players is None else players
        for name, owner in players.items():
            if owner != app:
                continue
            with contextlib.suppress(ControlError):
                status = await self.run('playerctl', f'--player={name}', 'status', timeout=2)
                if status.strip() == 'Playing':
                    await self.run('playerctl', f'--player={name}', 'pause', timeout=2)
                    self.paused[name] = app.id
                    self.save()

    async def resume(self, app, views):
        if app.type == 'mpv' and self.mpv_paused:
            await self.mpv(['set_property', 'pause', False])
            self.mpv_paused = False
            self.save()
        if app.id not in self.paused.values():
            return
        for name, owner in (await self.players(views)).items():
            if owner == app and self.paused.get(name) == app.id:
                await self.run('playerctl', f'--player={name}', 'play', timeout=2)
                del self.paused[name]
                self.save()

    async def background(self, active, views):
        players = await self.players(views)
        opened = {self.identify(view) for view in views}
        for app in opened:
            if app and app.id != active:
                await self.pause(app, views, players)
        # Discard only closed applications. Paused media sessions can briefly
        # disappear from D-Bus, and must remain resumable when they return.
        ids = {app.id for app in opened if app}
        kept = {name: app for name, app in self.paused.items() if app in ids}
        if kept != self.paused:
            self.paused = kept
            self.save()
