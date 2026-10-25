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

from .config import Settings, load_catalog
from .protocol import ControlError, MAX_MESSAGE
from .urls import validate_url

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
        if isinstance(pid, int) and pid > 0 and "chrome-" in value:
            try:
                args = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
            except OSError:
                return None
            # Chromium rewrites argv into a single display string on Linux.
            # Tokenize it only for comparison; it is never executed.
            args = [arg for arg in args if arg]
            if len(args) == 1:
                try:
                    args = [os.fsencode(arg) for arg in shlex.split(os.fsdecode(args[0]))]
                except ValueError:
                    return None
            for app in self.apps.values():
                if app.type == "chrome":
                    profile = Path.home() / ".local/share/orgm-home/chrome" / app.id
                    if os.fsencode(f"--user-data-dir={profile}") in args:
                        return app
        return None

    async def find(self, app):
        return next(
            (w for w in windows(await self.tree()) if self.identify(w) == app), None
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

    async def mute_application(self, app, muted):
        """Mute only matching Pulse streams; never mute every application."""
        raw = await command("pactl", "-f", "json", "list", "sink-inputs", check=False)
        try:
            streams = json.loads(raw)
        except ValueError:
            return False
        matched = False
        owned_pids = {
            str(w.get("pid"))
            for w in windows(await self.tree())
            if self.identify(w) == app
        }
        for stream in streams:
            props = stream.get("properties", {})
            app_name = props.get("application.name", "")
            proc_id = props.get("application.process.id", "")
            # Chromium's audio process may be a descendant of the window process.
            ancestor = proc_id
            for _ in range(12):
                if ancestor in owned_pids:
                    break
                try:
                    stat = Path(f"/proc/{int(ancestor)}/stat").read_text()
                    ancestor = stat[stat.rindex(")") + 2 :].split()[1]
                except (ValueError, OSError, IndexError):
                    ancestor = ""
                    break
            flatpak_match = app.type == "flatpak" and app_name.lower() in {
                app.name.lower(),
                app.appId.rsplit(".", 1)[-1].lower(),
            }
            if ancestor in owned_pids or flatpak_match:
                await command(
                    "pactl",
                    "set-sink-input-mute",
                    str(int(stream["index"])),
                    "1" if muted else "0",
                )
                matched = True
        return matched

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
        paused = False
        if previous.player:
            await command(
                "playerctl", f"--player={previous.player}", "pause", check=False
            )
            # A matching Pulse stream below also covers an unsupported MPRIS player.
        if previous.type == "mpv":
            with contextlib.suppress(OSError, TimeoutError, ControlError):
                await self.mpv(["set_property", "pause", True])
                paused = True
        muted = await self.mute_application(previous, True)
        if not paused and not muted:
            self.warning = (
                f"No se pudo confirmar la pausa de {previous.name}. Comprueba su audio."
            )

    async def enter_text(self, value, navigate=False):
        # The profile patch starts at evdev 30 (A). Register a stable US
        # printable row so Chromium sees both logical and physical L/V.
        physical = [
            "a",
            "s",
            "d",
            "f",
            "g",
            "h",
            "j",
            "k",
            "l",
            "semicolon",
            "apostrophe",
            "grave",
            "Shift_L",
            "backslash",
            "z",
            "x",
            "c",
            "v",
        ]
        prefix = [arg for name in physical for arg in ("-p", name)]
        keys = ["wtype", *prefix, "-s", "150"]
        if navigate:
            keys += ["-M", "ctrl", "-k", "l", "-m", "ctrl", "-s", "150"]
        keys += ["-M", "ctrl", "-k", "v", "-m", "ctrl", "-s", "250"]
        if navigate:
            keys += ["-k", "Return", "-s", "150"]
        # One virtual keyboard/keymap spans focus, paste and Enter: switching
        # keymaps while Chrome's address bar is focused can discard the URL.
        await command(
            "wl-copy", "--type", "text/plain", input_text=value, capture=False
        )
        try:
            await command(*keys)
            await asyncio.sleep(0.25)
        finally:
            await command("wl-copy", "--clear", capture=False)

    async def activate(self, app_id, url=None):
        if app_id not in self.apps:
            raise ControlError("Aplicación desconocida", 404)
        app = self.apps[app_id]
        await self.pause_previous(app)
        window = await self.find(app)
        navigate_existing = window is not None and url is not None
        if url is not None and app.id != "browser":
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
            elif app.type == "chrome":
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
        con_id = int(window["id"])
        await self.sway(f"[con_id={con_id}] mark --add orgm-home-{app.id}")
        await self.sway(
            f"[con_id={con_id}] move container to workspace number {app.workspace}"
        )
        await self.sway(f"[con_id={con_id}] focus")
        await self.sway(f"[con_id={con_id}] fullscreen enable")
        if navigate_existing and app.id == "browser":
            # Chrome forwards this URL as a tab to the same profile/window.
            await self.spawn(self.chrome_args(app, url, new_window=False))
        self.active = app.id
        await self.mute_application(app, False)
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
            brightness = round(100 * int((backlight / "brightness").read_text()) / int((backlight / "max_brightness").read_text()))
        except (OSError, ValueError, ZeroDivisionError):
            brightness = None
        return {
            "session": True,
            "app": app.id if app else None,
            "title": str((focused or {}).get("name", ""))[:256],
            "volume": round(float(match[1]) * 100) if match else None,
            "muted": "MUTED" in volume_raw,
            "brightness": brightness,
            "open": opened,
            "warning": self.warning,
            "capabilities": {
                "keys": bool(app and app.id != "home"),
                "text": bool(app and app.control not in {"internal", "mpv"}),
                "pointer": False,
                "play": bool(app and app.id != "home"),
                "close": bool(app and app.id != "home"),
                "stop": bool(app and (app.type == "mpv" or app.id == "spotify")),
                "next": bool(app and (app.type == "mpv" or app.id == "spotify")),
            },
        }

    async def dispatch(self, request):
        action = request.get("action")
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
            if action == "key":
                key = request.get("key")
                current = await self.status()
                app = self.apps.get(current["app"])
                if not app or app.id == "home":
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
                    await command("wtype", "-s", "100", "-k", KEYS[key])
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
                if not (await self.status())["capabilities"]["text"]:
                    raise ControlError("Esta aplicación no acepta texto", 409)
                await self.enter_text(value)
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
                await command("brightnessctl", "--device=intel_backlight", "set", f"{value}%")
                return {"updated": True}
            if action == "mute":
                await command("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle")
                return {"updated": True}
            if action == "close":
                current = await self.status()
                app = self.apps.get(current["app"])
                if not app or app.id == "home":
                    raise ControlError("El inicio permanece abierto", 409)
                window = await self.find(app)
                if window:
                    await self.sway(f"[con_id={int(window['id'])}] kill")
                return await self.activate("home")
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
    async with server:
        await stop.wait()
    path.unlink(missing_ok=True)


def main():
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve())
