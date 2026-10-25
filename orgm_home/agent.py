"""Session-owned controller. No shell, arbitrary programs or network listener."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from pathlib import Path
import re
import shlex
import signal
import socket
import struct
import subprocess
import time
import shutil

from .config import Settings, load_catalog
from .protocol import ControlError, MAX_MESSAGE
from .urls import validate_url, validate_max_url
from .preferences import BACKGROUNDS, gallery, read_background, write_background
from .wifi import Wifi
from .previews import capture, versions
from .playback import Playback

LOG = logging.getLogger(__name__)
KEYS = {
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
    "ok": "Return",
    "back": "Escape",
    "backspace": "BackSpace",
    "tab": "Tab",
    "space": "space",
}


async def command(
    *args: str,
    timeout: float = 8,
    check: bool = True,
    input_text: str | None = None,
    capture: bool = True,
):
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE if input_text is not None else None,
            stdout=asyncio.subprocess.PIPE if capture else asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE if capture else asyncio.subprocess.DEVNULL,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(
                    input_text.encode() if input_text is not None else None
                ),
                timeout,
            )
        except BaseException:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
            raise
    except (OSError, TimeoutError) as exc:
        raise ControlError("No respondió una herramienta de la sesión") from exc
    if check and proc.returncode:
        LOG.warning(
            "%s exited %s: %s",
            args[0],
            proc.returncode,
            (stderr or b"").decode(errors="replace")[:300],
        )
        raise ControlError("La aplicación no pudo completar la acción")
    return (stdout or b"").decode(errors="replace")


def windows(tree):
    if tree.get("type") in {"con", "floating_con"} and (
        tree.get("app_id") or tree.get("window")
    ):
        yield tree
    for node in tree.get("nodes", []) + tree.get("floating_nodes", []):
        yield from windows(node)


class Controller:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.apps = load_catalog(settings.catalog)
        self.lock = asyncio.Lock()
        self.state_dir = (
            Path(os.getenv("XDG_STATE_HOME", str(Path.home() / ".local/state")))
            / "orgm-home"
        )
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.children = set()
        self.active = "home"
        self.warning = None
        self.processes = {}
        self.keyboard = None
        self.known_windows = None
        self.spotify_interrupted = False
        self.audio_app = None
        self.wifi = Wifi(command, Path(os.getenv("XDG_RUNTIME_DIR", str(self.state_dir))) / "orgm-home-wifi")
        self.spotify = {"available": False, "playing": False, "title": "", "artist": ""}
        self.playback = Playback(self.state_dir, self.apps, lambda *a, **k: command(*a, **k), self.identify, self.ancestors, self.mpv)

    async def refresh_media(self):
        views = list(windows(await self.tree()))
        for app in self.apps.values():
            if app.id == "home":
                continue
            matches = [w for w in views if self.identify(w) == app]
            if matches:
                item = min(matches, key=lambda w: (f"orgm-home-{app.id}" not in w.get("marks", []), w["id"]))
                if app.type == "airplay":
                    item = max(matches, key=lambda w: ("uxplay" in (w.get("app_id") or "").lower(), w["id"]))
                with contextlib.suppress(ControlError, OSError):
                    await capture(app.id, item.get("foreign_toplevel_identifier"), command)

    async def refresh_spotify(self):
        status = (await command("playerctl", "--player=spotify", "status", check=False)).strip()
        if status not in {"Playing", "Paused", "Stopped"}:
            self.spotify = {"available": False, "playing": False, "title": "", "artist": ""}
            return
        metadata = await command("playerctl", "--player=spotify", "metadata", "--format", "{{artist}}\n{{title}}", check=False)
        parts = metadata.splitlines()
        self.spotify = {"available": True, "playing": status == "Playing", "artist": (parts[0] if parts else "")[:256], "title": (parts[1] if len(parts)>1 else "")[:256]}

    async def sway(self, value):
        raw = await command("swaymsg", "-r", value)
        result = json.loads(raw)
        if not all(row.get("success") for row in result):
            raise ControlError("Sway rechazó la acción")
        return result

    async def tree(self):
        return json.loads(await command("swaymsg", "-r", "-t", "get_tree"))

    def identify(self, window):
        marks = window.get("marks", [])
        for app in self.apps.values():
            if f"orgm-home-{app.id}" in marks:
                return app
        value = " ".join(str(window.get(k) or "") for k in ("app_id",))
        props = window.get("window_properties") or {}
        value += " " + " ".join(str(props.get(k) or "") for k in ("class", "instance"))
        for app in self.apps.values():
            if app.match and re.search(app.match, value, re.IGNORECASE):
                return app
        # Chrome app-mode Wayland windows replace --class with a URL-derived
        # app_id. Match the compositor-owned PID to its dedicated profile;
        # titles and redirects must not affect application identity.
        pid = window.get("pid")
        if isinstance(pid, int) and pid > 0:
            try:
                args = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
            except OSError:
                return None
            # Chromium rewrites argv into a single display string on Linux.
            # Tokenize it only for comparison; it is never executed.
            args = [arg for arg in args if arg]
            if len(args) == 1:
                try:
                    args = [
                        os.fsencode(arg) for arg in shlex.split(os.fsdecode(args[0]))
                    ]
                except ValueError:
                    return None
            if args and Path(os.fsdecode(args[0])).name.lstrip(".") in {"uxplay", "uxplay-wrapped"}:
                return next((app for app in self.apps.values() if app.type == "airplay"), None)
            for app in self.apps.values():
                if app.type in {"chrome", "airplay"}:
                    profile = Path.home() / ".local/share/orgm-home/chrome" / app.id
                    if os.fsencode(f"--user-data-dir={profile}") in args:
                        return app
        return None

    async def find(self, app):
        matches = [w for w in windows(await self.tree()) if self.identify(w) == app]
        if app.type == "airplay":
            stream = next((w for w in matches if "uxplay" in (w.get("app_id") or "").lower()), None)
            if stream:
                return stream
        # A popup may precede its opener in Sway's tree. Keep activation tied
        # to the original marked window rather than replacing it with an ad.
        return min(
            matches,
            key=lambda w: (f"orgm-home-{app.id}" not in w.get("marks", []), w["id"]),
            default=None,
        )

    async def spawn(self, args):
        log = (self.state_dir / "applications.log").open("ab")
        try:
            # Popen is intentional: asyncio subprocess transports kill their
            # child on interpreter shutdown, closing apps on agent restart.
            proc = subprocess.Popen(
                args, stdout=log, stderr=log, start_new_session=True
            )
        finally:
            log.close()
        self.children.add(proc)

        async def reap():
            while proc.poll() is None:
                await asyncio.sleep(1)
            self.children.discard(proc)

        asyncio.create_task(reap())
        return proc

    def chrome_args(self, app, url, new_window=True):
        profile = Path.home() / ".local/share/orgm-home/chrome" / app.id
        profile.mkdir(parents=True, exist_ok=True)
        return [
            "google-chrome-stable",
            "--ozone-platform=wayland",
            "--no-first-run",
            "--no-default-browser-check",
            "--password-store=basic",
            "--blink-settings=hideScrollbars=true",
            f"--class=orgm-home-{app.id}",
            f"--user-data-dir={profile}",
            *(
                [*(["--kiosk"] if new_window else []), url]
                if app.id == "browser"
                else [f"--app={url}"]
            ),
        ]

    @staticmethod
    def ancestors(pid):
        result = set()
        for _ in range(16):
            try:
                pid = str(int(pid))
                if pid in result or int(pid) < 1:
                    break
                result.add(pid)
                stat = Path(f"/proc/{pid}/stat").read_text()
                pid = stat[stat.rindex(")") + 2 :].split()[1]
            except (OSError, ValueError, IndexError):
                break
        return result

    def stream_app(self, stream, views):
        props = stream.get("properties", {})
        ancestors = self.ancestors(props.get("application.process.id", ""))
        for view in views:
            if str(view.get("pid")) in ancestors:
                app = self.identify(view)
                if app:
                    return app
        identifiers = {
            str(props.get(key, "")).lower()
            for key in (
                "application.name",
                "application.id",
                "flatpak.app_id",
                "pipewire.access.portal.app_id",
            )
        }
        for app in self.apps.values():
            if app.type == "airplay" and identifiers.intersection(
                {"uxplay", "orgm airplay", "orgm-home-airplay"}
            ):
                return app
            if app.type == "flatpak" and identifiers.intersection(
                {
                    app.name.lower(),
                    app.appId.lower(),
                    app.appId.rsplit(".", 1)[-1].lower(),
                }
            ):
                return app
        return None

    async def audio_streams(self):
        streams = json.loads(await command("pactl", "-f", "json", "list", "sink-inputs"))
        # Native PipeWire nodes can omit the PID; their client retains it.
        # Flatpak's application PID is namespaced, so use its host security PID.
        if any(not stream.get("properties", {}).get("application.process.id") for stream in streams):
            clients = {}
            with contextlib.suppress(ControlError, ValueError):
                clients = {str(client["index"]): client.get("properties", {}) for client in json.loads(await command("pactl", "-f", "json", "list", "clients"))}
            for stream in streams:
                props = {**clients.get(str(stream.get("client")), {}), **stream.get("properties", {})}
                if str(props.get("pipewire.sec.flatpak", "")).lower() == "true" and props.get("pipewire.sec.pid"):
                    props["application.process.id"] = props["pipewire.sec.pid"]
                stream["properties"] = props
        return streams

    async def mute_application(self, app, muted):
        streams = await self.audio_streams()
        views = list(windows(await self.tree()))
        matched = False
        for stream in streams:
            if self.stream_app(stream, views) == app:
                await command(
                    "pactl",
                    "set-sink-input-mute",
                    str(int(stream["index"])),
                    "1" if muted else "0",
                )
                matched = True
        return matched

    async def reconcile_audio(self):
        # Spotify retains audio on Home and quiet apps. Only an uncorked stream
        # from the selected media app takes audio focus away from the music.
        views = list(windows(await self.tree()))
        focused = next((w for w in views if w.get("focused")), None)
        active = self.identify(focused) if focused else self.apps.get(self.active)
        if active:
            self.active = active.id
        streams = await self.audio_streams()
        owned = [(stream, self.stream_app(stream, views)) for stream in streams]
        interrupts_music = bool(
            active and active.id not in {"home", "spotify"}
            and any(owner == active and not stream.get("corked", True) for stream, owner in owned)
        )
        if interrupts_music and not self.spotify_interrupted and "spotify" in self.apps:
            with contextlib.suppress(ControlError):
                await command("playerctl", "--player=spotify", "pause", check=False)
        self.spotify_interrupted = interrupts_music
        self.audio_app = None
        for stream, owner in owned:
            if owner:
                muted = interrupts_music if owner.id == "spotify" else owner != active
                if not muted and not stream.get("corked", True):
                    self.audio_app = owner.id
                if bool(stream.get("mute")) != muted:
                    await command(
                        "pactl",
                        "set-sink-input-mute",
                        str(int(stream["index"])),
                        "1" if muted else "0",
                    )

    async def reconcile_windows(self):
        views = list(windows(await self.tree()))
        current_ids = {w["id"] for w in views}
        previous, self.known_windows = self.known_windows, current_ids
        if previous is None:
            return
        focused = next((w for w in views if w.get("focused")), None)
        active = self.identify(focused) if focused else self.apps.get(self.active)
        # Chromium popups can map behind a fullscreen opener. Show a new
        # window only for the app currently in use; background ads cannot
        # switch the household away from Home or a different application.
        fresh = [
            w for w in views
            if w["id"] not in previous
            and (owner := self.identify(w))
            and owner.type in {"chrome", "airplay"} and owner == active
        ]
        if fresh:
            popup = max(fresh, key=lambda w: w["id"])
            con_id = int(popup["id"])
            await self.sway(
                f"[con_id={con_id}] move container to workspace number {active.workspace}"
            )
            await self.sway(f"[con_id={con_id}] fullscreen enable")
            await self.sway(f"[con_id={con_id}] focus")

    async def close_keyboard(self):
        process, self.keyboard = self.keyboard, None
        if process and process.returncode is None:
            process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), 2)
            except TimeoutError:
                process.kill()
                await process.wait()

    async def native_key(self, code, modifiers=0):
        # Keep one complete native keymap alive. Removing a synthetic keyboard
        # between actions can crash Electron's libxkbcommon on keymap changes.
        try:
            if self.keyboard is None or self.keyboard.returncode is not None:
                self.keyboard = await asyncio.create_subprocess_exec(
                    os.getenv("ORGM_OSK_ENGINE", "orgm-osk-engine"),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                ready = json.loads(
                    await asyncio.wait_for(self.keyboard.stdout.readline(), 4)
                )
                if ready.get("event") != "ready":
                    raise ValueError("Keyboard unavailable")
            self.keyboard.stdin.write(
                (
                    json.dumps(
                        {
                            "action": "tap",
                            "code": code,
                            "modifiers": modifiers,
                            "text": "",
                        }
                    )
                    + "\n"
                ).encode()
            )
            await self.keyboard.stdin.drain()
            result = json.loads(
                await asyncio.wait_for(self.keyboard.stdout.readline(), 4)
            )
            if result.get("event") != "done":
                raise ValueError("Keyboard action failed")
        except (OSError, ValueError, TimeoutError) as exc:
            await self.close_keyboard()
            raise ControlError("No se pudo enviar la tecla a la aplicación") from exc

    async def mpv(self, payload):
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(str(self.state_dir / "mpv.sock")), 2
        )
        try:
            writer.write(json.dumps({"command": payload}).encode() + b"\n")
            await writer.drain()
            for _ in range(30):
                result = json.loads(await asyncio.wait_for(reader.readline(), 2))
                if "error" in result:
                    if result["error"] != "success":
                        raise ControlError("mpv rechazó la acción", 409)
                    return result.get("data")
            raise ControlError("mpv no confirmó la acción")
        finally:
            writer.close()
            await writer.wait_closed()

    async def pause_previous(self, app):
        previous = self.apps.get(self.active)
        self.warning = None
        if previous is None or previous.id in {"home", app.id}:
            return
        if previous.id == "spotify":
            return
        await self.playback.pause(previous, list(windows(await self.tree())))
        await self.mute_application(previous, True)

    async def reconcile_playback(self):
        views = list(windows(await self.tree()))
        focused = next((w for w in views if w.get("focused")), None)
        active = self.identify(focused) if focused else self.apps.get(self.active)
        await self.playback.background(active.id if active else self.active, views)

    async def enter_text(self, value, navigate=False, terminal=False):
        await command(
            "wl-copy", "--type", "text/plain", input_text=value, capture=False
        )
        try:
            if navigate:
                await self.native_key(38, modifiers=4)  # Ctrl+L
                await asyncio.sleep(0.15)
            await self.native_key(47, modifiers=5 if terminal else 4)
            await asyncio.sleep(0.25)
            if navigate:
                await self.native_key(28)
        finally:
            await command("wl-copy", "--clear", capture=False)

    async def activate(self, app_id, url=None):
        if app_id not in self.apps:
            raise ControlError("Aplicación desconocida", 404)
        app = self.apps[app_id]
        if app.type == "airplay":
            await command("systemctl", "--user", "start", "orgm-home-airplay.service")
        window = await self.find(app)
        navigate_existing = window is not None and url is not None
        if url is not None and app.id not in {"browser", "max"}:
            raise ControlError("Destino de navegador inválido", 422)
        if not window:
            await self.sway(f"workspace number {app.workspace}")
            if app.type == "internal":
                # Kiosk has its own restarting systemd user service.
                await command(
                    "systemctl", "--user", "restart", "orgm-home-kiosk.service"
                )
            elif app.type == "flatpak":
                proc = await self.spawn(["flatpak", "run", app.appId])
                self.processes[app.id] = proc
            elif app.type in {"chrome", "airplay"}:
                self.processes[app.id] = await self.spawn(
                    self.chrome_args(app, url or app.url)
                )
            elif app.type == "mpv":
                self.processes[app.id] = await self.spawn(
                    [
                        "mpv",
                        "--idle=yes",
                        "--force-window=yes",
                        "--fullscreen",
                        "--title=ORGM Videos",
                        f"--input-ipc-server={self.state_dir / 'mpv.sock'}",
                    ]
                )
            elif app.type == "terminal":
                self.processes[app.id] = await self.spawn(["kitty", "--class", f"orgm-home-{app.id}", "--title", app.name, "--override", "confirm_os_window_close=0"])
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                window = await self.find(app)
                if window:
                    break
                proc = self.processes.get(app.id)
                if proc and proc.returncode is not None and proc.returncode != 0:
                    raise ControlError(
                        f"No arrancó {app.name}. Comprueba que esté instalada."
                    )
                await asyncio.sleep(0.2)
            if not window:
                raise ControlError(f"No apareció la ventana de {app.name}", 504)
        with contextlib.suppress(ControlError):
            await self.pause_previous(app)
        con_id = int(window["id"])
        await self.sway(f"[con_id={con_id}] mark --add orgm-home-{app.id}")
        await self.sway(
            f"[con_id={con_id}] move container to workspace number {app.workspace}"
        )
        await self.sway(f"workspace number {app.workspace}")
        await self.sway(f"[con_id={con_id}] focus")
        await self.sway(f"[con_id={con_id}] fullscreen enable")
        if navigate_existing:
            # Chrome forwards this URL as a tab to the same profile/window.
            await self.spawn(self.chrome_args(app, url, new_window=False))
        self.active = app.id
        with contextlib.suppress(ControlError):
            await self.mute_application(app, False)
        with contextlib.suppress(ControlError, OSError, TimeoutError):
            await self.playback.resume(app, list(windows(await self.tree())))
        return {"app": app.id, "warning": self.warning}

    async def status(self):
        tree = await self.tree()
        focused = next((w for w in windows(tree) if w.get("focused")), None)
        app = self.identify(focused) if focused else None
        if app:
            self.active = app.id
        volume_raw = await command(
            "wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@", check=False
        )
        match = re.search(r"Volume: ([0-9.]+)", volume_raw)
        opened = list(
            dict.fromkeys(a.id for w in windows(tree) if (a := self.identify(w)))
        )
        try:
            backlight = Path("/sys/class/backlight/intel_backlight")
            brightness = round(
                100
                * int((backlight / "brightness").read_text())
                / int((backlight / "max_brightness").read_text())
            )
        except (OSError, ValueError, ZeroDivisionError):
            brightness = None
        return {
            "session": True,
            "app": app.id if app else None,
            "title": str((focused or {}).get("name", ""))[:256],
            "volume": round(float(match[1]) * 100) if match else None,
            "muted": "MUTED" in volume_raw,
            "brightness": brightness,
            "background": read_background(self.state_dir),
            "audio_app": self.audio_app,
            "previews": versions(opened),
            "spotify": self.spotify,
            "open": opened,
            "warning": self.warning,
            "capabilities": {
                "keys": bool(app and app.id != "home" and app.type != "airplay"),
                "text": bool(app and app.control not in {"internal", "mpv"} and app.type != "airplay"),
                "pointer": False,
                "play": bool(app and app.id != "home" and app.type not in {"airplay", "terminal"}),
                "close": bool(app and app.id != "home"),
                "stop": bool(app and (app.type == "mpv" or app.id == "spotify")),
                "next": bool(app and (app.type == "mpv" or app.id == "spotify")),
            },
        }

    async def dispatch(self, request):
        action = request.get("action")
        if action in {"wifi-status", "wifi-scan"}:
            return await self.wifi.status(rescan=action == "wifi-scan")
        if action == "wifi-connect":
            return await self.wifi.connect(request.get("ssid"), request.get("password", ""))
        if action == "wifi-reconnect":
            return await self.wifi.reconnect()
        async with self.lock:
            if action == "status":
                return await self.status()
            if action == "activate":
                return await self.activate(request.get("id"))
            if action == "home":
                return await self.activate("home")
            if action == "open-url":
                return await self.activate(
                    "browser", await validate_url(request.get("url", ""))
                )
            if action == "open-max":
                return await self.activate("max", await validate_max_url(request.get("url", "")))
            if action == "key":
                key = request.get("key")
                current = await self.status()
                app = self.apps.get(current["app"])
                if not app or app.id == "home" or app.type == "airplay":
                    raise ControlError(
                        "Selecciona una aplicación para usar el mando", 409
                    )
                if key in {"stop", "next", "previous"}:
                    if not current["capabilities"]["stop" if key == "stop" else "next"]:
                        raise ControlError("Este servicio no ofrece ese control", 409)
                    if app.type == "mpv":
                        await self.mpv(
                            [
                                {
                                    "stop": "stop",
                                    "next": "playlist-next",
                                    "previous": "playlist-prev",
                                }[key]
                            ]
                        )
                    else:
                        await command("playerctl", f"--player={app.player}", key)
                elif key == "play":
                    if app.type == "mpv":
                        await self.mpv(["cycle", "pause"])
                    elif app.player:
                        await command(
                            "playerctl", f"--player={app.player}", "play-pause"
                        )
                    else:
                        await command("wtype", "-s", "100", "-k", "space")
                elif key in KEYS:
                    if key == "back" and (app.type == "chrome" or app.id == "spotify"):
                        await self.native_key(105, modifiers=8)
                    else:
                        codes = {
                            "up": 103,
                            "down": 108,
                            "left": 105,
                            "right": 106,
                            "ok": 28,
                            "back": 1,
                            "backspace": 14,
                            "tab": 15,
                            "space": 57,
                        }
                        await self.native_key(codes[key])
                else:
                    raise ControlError("Tecla no permitida", 422)
                return {"sent": key}
            if action == "text":
                value = request.get("text")
                if (
                    not isinstance(value, str)
                    or not 1 <= len(value) <= 1000
                    or any(ord(c) < 32 or ord(c) == 127 for c in value)
                ):
                    raise ControlError(
                        "Texto inválido: máximo 1000 caracteres sin controles", 422
                    )
                current = await self.status()
                if not current["capabilities"]["text"]:
                    raise ControlError("Esta aplicación no acepta texto", 409)
                app = self.apps.get(current.get("app"))
                await self.enter_text(value, terminal=bool(app and app.type == "terminal"))
                return {"sent": True}
            if action == "volume":
                value = request.get("value")
                delta = request.get("delta")
                if (
                    isinstance(value, (float, int))
                    and not isinstance(value, bool)
                    and 0 <= value <= 100
                    and delta is None
                ):
                    await command(
                        "wpctl",
                        "set-volume",
                        "--limit",
                        "1",
                        "@DEFAULT_AUDIO_SINK@",
                        f"{value}%",
                    )
                elif delta in {-5, 5} and value is None:
                    await command(
                        "wpctl",
                        "set-volume",
                        "--limit",
                        "1",
                        "@DEFAULT_AUDIO_SINK@",
                        f"5%{'+' if delta > 0 else '-'}",
                    )
                else:
                    raise ControlError("Volumen fuera de rango", 422)
                return {"updated": True}
            if action == "brightness":
                value = request.get("value")
                if type(value) is not int or not 5 <= value <= 100:
                    raise ControlError("El brillo debe estar entre 5 y 100", 422)
                await command(
                    "brightnessctl", "--device=intel_backlight", "set", f"{value}%"
                )
                return {"updated": True}
            if action == "preferences":
                return {
                    "background": read_background(self.state_dir),
                    "backgrounds": gallery(),
                }
            if action == "background":
                value = request.get("id")
                if not isinstance(value, str) or value not in BACKGROUNDS:
                    raise ControlError("Fondo desconocido", 422)
                write_background(self.state_dir, value)
                return {"background": value}
            if action == "restart-launcher":
                await command(
                    "systemctl",
                    "--user",
                    "--no-block",
                    "restart",
                    "orgm-home-kiosk",
                    "orgm-home-display",
                    "orgm-home-touch",
                )
                return {"accepted": True}
            if action == "reboot":
                helper = shutil.which("orgm-home-reboot")
                if not helper:
                    raise ControlError("No está disponible el reinicio del equipo")
                await command("systemd-run", "--user", "--collect", "--on-active=1s", "--timer-property=AccuracySec=1s", "--unit=orgm-home-reboot", helper)
                return {"accepted": True}
            if action == "wifi-open":
                ui = Path(__file__).parent / "touch/shell.qml"
                await command("qs", "--path", str(ui), "ipc", "call", "--", "touch", "wifi")
                return {"accepted": True}
            if action in {"spotify-toggle", "spotify-next", "spotify-previous"}:
                try:
                    await command("playerctl", "--player=spotify", {"spotify-toggle":"play-pause", "spotify-next":"next", "spotify-previous":"previous"}[action])
                except ControlError as exc:
                    raise ControlError("Abre Spotify y elige música primero", 409) from exc
                await self.refresh_spotify()
                return {"spotify": self.spotify}
            if action == "rotate":
                outputs = json.loads(
                    await command("swaymsg", "-r", "-t", "get_outputs")
                )
                output = next((o for o in outputs if o.get("name") == "eDP-1"), None)
                if output is None:
                    raise ControlError("No está disponible la pantalla táctil", 409)
                rotation = "normal" if output.get("transform") == "180" else "180"
                await self.sway(f"output eDP-1 transform {rotation}")
                await self.sway("input type:touch map_to_output eDP-1")
                (self.state_dir / "rotation").write_text(rotation)
                return {"rotation": rotation}
            if action == "mute":
                await command("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle")
                return {"updated": True}
            if action == "close-app":
                app = self.apps.get(request.get("id"))
                if not app:
                    raise ControlError("Aplicación desconocida", 404)
                if app.id == "home":
                    raise ControlError("El inicio permanece abierto", 409)
                tree = await self.tree()
                targets = [w for w in windows(tree) if self.identify(w) == app]
                focused = next((w for w in windows(tree) if w.get("focused")), None)
                was_focused = focused is not None and self.identify(focused) == app
                if app.type == "airplay":
                    await command("systemctl", "--user", "stop", "orgm-home-airplay.service")
                ids = {int(w["id"]) for w in targets}
                for con_id in ids:
                    await self.sway(f"[con_id={con_id}] kill")
                if app.type == "flatpak":
                    # Spotify can keep playing after its last window closes.
                    # Closing a dashboard source also ends its own sandbox.
                    await command("flatpak", "kill", app.appId, check=False)
                deadline = time.monotonic() + 3
                while any(w["id"] in ids for w in windows(await self.tree())):
                    if time.monotonic() >= deadline:
                        raise ControlError("La aplicación no se cerró. Revisa si pide confirmación.", 409)
                    await asyncio.sleep(0.1)
                self.processes.pop(app.id, None)
                if was_focused:
                    return await self.activate("home")
                return {"closed": app.id}
            if action == "close":
                focused = next(
                    (w for w in windows(await self.tree()) if w.get("focused")), None
                )
                app = self.identify(focused) if focused else None
                if not app or app.id == "home":
                    raise ControlError("El inicio permanece abierto", 409)
                if app.type == "airplay":
                    await command("systemctl", "--user", "stop", "orgm-home-airplay.service")
                    for view in list(windows(await self.tree())):
                        if self.identify(view) == app:
                            await self.sway(f"[con_id={int(view['id'])}] kill")
                    return await self.activate("home")
                con_id = int(focused["id"])
                await self.sway(f"[con_id={con_id}] kill")
                # xdg_toplevel.close is asynchronous: wait for this exact
                # window to leave before selecting a surviving sibling.
                deadline = time.monotonic() + 3
                while any(w["id"] == con_id for w in windows(await self.tree())):
                    if time.monotonic() >= deadline:
                        raise ControlError("La página no se cerró. Inténtalo de nuevo.", 409)
                    await asyncio.sleep(0.1)
                return await self.activate(app.id if await self.find(app) else "home")
            if action == "local-files":
                return await self.list_files()
            if action == "play-file":
                name = request.get("name")
                if (
                    not isinstance(name, str)
                    or name not in (await self.list_files())["files"]
                ):
                    raise ControlError("Archivo desconocido", 404)
                path = Path.home() / "Videos" / name
                await self.activate("videos")
                await self.mpv(["loadfile", str(path), "replace"])
                await self.mpv(["set_property", "pause", False])
                return {"playing": name}
            raise ControlError("Acción no permitida", 422)

    async def list_files(self):
        root = Path.home() / "Videos"
        root.mkdir(exist_ok=True)
        return {
            "files": sorted(
                p.name
                for p in root.iterdir()
                if p.is_file()
                and not p.is_symlink()
                and p.suffix.lower()
                in {".mp4", ".mkv", ".webm", ".avi", ".mp3", ".flac", ".ogg", ".mov"}
            )[:200]
        }


async def serve():
    if not os.environ.get("SWAYSOCK") or not os.environ.get("WAYLAND_DISPLAY"):
        raise RuntimeError("Start the agent inside the media Sway session")
    settings = Settings.from_env()
    controller = Controller(settings)
    path = settings.agent_socket
    path.parent.mkdir(parents=True, exist_ok=True)
    # Never unlink an active agent's socket.
    if path.exists():
        try:
            _, writer = await asyncio.open_unix_connection(str(path))
        except (ConnectionRefusedError, FileNotFoundError):
            path.unlink(missing_ok=True)
        else:
            writer.close()
            await writer.wait_closed()
            raise RuntimeError("A session agent is already running")

    async def handle(reader, writer):
        try:
            peer = writer.get_extra_info("socket").getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, 12
            )
            _, uid, _ = struct.unpack("3i", peer)
            if uid != os.getuid():
                raise ControlError("Peer UID denied", 403)
            raw = await asyncio.wait_for(reader.readline(), 3)
            if len(raw) > MAX_MESSAGE:
                raise ControlError("Request too large", 413)
            request = json.loads(raw)
            if not isinstance(request, dict):
                raise ControlError("Invalid request", 422)
            data = await controller.dispatch(request)
            result = {"ok": True, "data": data}
        except ControlError as exc:
            result = {"ok": False, "error": str(exc), "status": exc.status}
        except Exception:
            LOG.exception("Session command failed")
            result = {
                "ok": False,
                "error": "Falló el controlador de sesión",
                "status": 503,
            }
        try:
            writer.write(json.dumps(result).encode() + b"\n")
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    old_mask = os.umask(0o077)
    try:
        server = await asyncio.start_unix_server(handle, str(path), limit=MAX_MESSAGE)
    finally:
        os.umask(old_mask)
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)

    async def audio_policy():
        while not stop.is_set():
            try:
                async with controller.lock:
                    await controller.reconcile_windows()
                    await controller.reconcile_playback()
                    await controller.reconcile_audio()
            except (ControlError, ValueError, OSError):
                LOG.warning("Audio reconciliation unavailable; retrying")
            await asyncio.sleep(1)

    audio_task = asyncio.create_task(audio_policy())
    async def media_policy():
        while not stop.is_set():
            with contextlib.suppress(ControlError, ValueError, OSError):
                await controller.refresh_media()
            await asyncio.sleep(10)

    async def music_policy():
        while not stop.is_set():
            with contextlib.suppress(ControlError, ValueError, OSError):
                await controller.refresh_spotify()
            await asyncio.sleep(2)

    media_task = asyncio.create_task(media_policy())
    music_task = asyncio.create_task(music_policy())
    async with server:
        await stop.wait()
    audio_task.cancel()
    media_task.cancel()
    music_task.cancel()
    await asyncio.gather(media_task, music_task, return_exceptions=True)
    with contextlib.suppress(asyncio.CancelledError):
        await audio_task
    await controller.close_keyboard()
    path.unlink(missing_ok=True)


def main():
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve())
