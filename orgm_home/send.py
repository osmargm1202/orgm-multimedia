"""Direct HTTPS YouTube sender with a persistent, individually approved identity."""

import argparse
import contextlib
import fcntl
import http.cookiejar
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import (
    HTTPCookieProcessor,
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
    build_opener,
)

from .protocol import ControlError
from .youtube import canonical_url


def notify(message):
    try:
        subprocess.run(
            ["notify-send", "--app-name=ORGM Home", "YouTube en Jarq", message],
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def selection():
    if os.environ.get("WAYLAND_DISPLAY"):
        args = ["wl-paste", "--primary", "--no-newline"]
    elif os.environ.get("DISPLAY"):
        args = ["xclip", "-selection", "primary", "-o"]
    else:
        raise ControlError(
            "No hay una sesión gráfica desde la que leer la selección.", 422
        )
    # Read only the selection. Never fall back to an old clipboard video.
    with subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    ) as process:
        try:
            import selectors

            raw = bytearray()
            deadline = time.monotonic() + 2
            with selectors.DefaultSelector() as ready:
                ready.register(process.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not ready.select(remaining):
                        raise ControlError(
                            "No se pudo leer el texto seleccionado.", 422
                        )
                    chunk = os.read(process.stdout.fileno(), 8193 - len(raw))
                    if not chunk:
                        break
                    raw.extend(chunk)
                    if len(raw) > 8192:
                        raise ControlError(
                            "La selección es demasiado larga para ser un enlace.", 422
                        )
            process.wait(timeout=2)
            if process.returncode:
                raise ControlError("Selecciona primero un enlace de YouTube.", 422)
            return raw.decode("utf-8")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


ROOM = "https://home.or-gm.com"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, target):
        return None


class RemoteSender:
    def __init__(self, state=None, *, base=ROOM, sleep=time.sleep):
        self.state = (
            state
            or Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
            / "orgm-home/youtube-send"
        )
        self.base = base
        self.sleep = sleep
        self.name = socket.gethostname().split(".")[0][:40].upper() + " · atajo YouTube"
        self.cookies = http.cookiejar.MozillaCookieJar()
        self.lock = None

    def __enter__(self):
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.state.chmod(0o700)
        descriptor = os.open(self.state / "sender.lock", os.O_RDWR | os.O_CREAT, 0o600)
        self.lock = os.fdopen(descriptor, "w")
        os.fchmod(self.lock.fileno(), 0o600)
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.lock.close()
            self.lock = None
            raise ControlError(
                "Ya hay un envío o una autorización pendiente del atajo.", 409
            ) from exc
        try:
            path = self.state / "device.cookies"
            if path.exists():
                path.chmod(0o600)
                self.cookies.load(str(path), ignore_discard=False, ignore_expires=False)
            self.client = build_opener(
                ProxyHandler({}), NoRedirect(), HTTPCookieProcessor(self.cookies)
            )
        except (OSError, http.cookiejar.LoadError):
            self.lock.close()
            self.lock = None
            raise ControlError(
                "No se pudo leer la autorización guardada del atajo.", 503
            ) from None
        return self

    def __exit__(self, *_):
        if self.lock:
            try:
                self.save()
            finally:
                self.lock.close()
                self.lock = None

    def save(self):
        descriptor, temporary = tempfile.mkstemp(prefix=".device-", dir=self.state)
        os.close(descriptor)
        try:
            self.cookies.save(temporary, ignore_discard=False, ignore_expires=False)
            os.chmod(temporary, 0o600)
            with open(temporary, "rb") as stream:
                os.fsync(stream.fileno())
            os.replace(temporary, self.state / "device.cookies")
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary)

    def request(self, path, body=None, csrf=None):
        headers = {"Origin": self.base, "User-Agent": "ORGM-YouTube-Sender/2 (Linux)"}
        if csrf:
            headers["X-CSRF-Token"] = csrf
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            self.base + path,
            data=None if body is None else json.dumps(body).encode(),
            headers=headers,
        )
        try:
            with self.client.open(request, timeout=30) as response:
                data = response.read(131073)
                if len(data) > 131072:
                    raise ControlError(
                        "Jarq devolvió una respuesta demasiado grande.", 503
                    )
                result = json.loads(data)
                if not isinstance(result, dict):
                    raise ValueError
                self.save()
                return result
        except HTTPError as exc:
            exc.close()
            # Never echo cookies, headers or the HTTP request in a notification/log.
            raise ControlError(
                {
                    401: "El atajo necesita autorización en Jarq.",
                    403: "Jarq rechazó el permiso de esta acción.",
                    429: "Hay demasiadas solicitudes; espera un momento.",
                }.get(exc.code, "Jarq no pudo completar el envío."),
                exc.code,
            ) from None
        except (URLError, TimeoutError, OSError):
            raise ControlError(
                "No hay conexión con Jarq. Comprueba Tailscale y vuelve a intentarlo.",
                503,
            ) from None
        except (ValueError, UnicodeError):
            raise ControlError("Jarq devolvió una respuesta no válida.", 503) from None

    def authorize(self):
        try:
            session = self.request("/api/session")
            if isinstance(session.get("csrf"), str) and session["csrf"]:
                return session["csrf"]
            raise ControlError("Jarq no confirmó la autorización del atajo.", 503)
        except ControlError as exc:
            if exc.status != 401:
                raise
        pending = self.request("/api/pairing/request", {"name": self.name})
        expires = pending.get("expires_in")
        if pending.get("status") != "pending" or type(expires) is not int:
            raise ControlError("Jarq no confirmó la solicitud de autorización.", 503)
        notify(
            "Acepta en Jarq la solicitud de «"
            + self.name
            + "». Después se guardará el permiso."
        )
        deadline = time.monotonic() + min(
            max(pending.get("expires_in", 120), 0) + 1, 120
        )
        while time.monotonic() < deadline:
            result = self.request("/api/pairing/status")
            status = result.get("status")
            if (
                status == "approved"
                and isinstance(result.get("csrf"), str)
                and result["csrf"]
            ):
                return result["csrf"]
            if status == "rejected":
                raise ControlError("La solicitud del atajo fue rechazada en Jarq.", 403)
            if status != "pending":
                raise ControlError(
                    "La solicitud venció. Pulsa el atajo para solicitar permiso de nuevo.",
                    401,
                )
            self.sleep(2)
        raise ControlError(
            "La solicitud venció. Pulsa el atajo para solicitar permiso de nuevo.", 401
        )

    def send(self, video):
        video = canonical_url(video)
        for attempt in range(2):
            csrf = self.authorize()
            try:
                result = self.request(
                    "/api/apps/youtube/open-url", {"url": video}, csrf
                )
                if result.get("url") != video:
                    raise ControlError("Jarq no confirmó el video solicitado.", 503)
                return
            except ControlError as exc:
                # A 401 is rejected before dispatch; it is safe to re-pair once.
                # A timeout is never retried: the first send might have arrived.
                if exc.status != 401 or attempt:
                    raise
                for cookie in list(self.cookies):
                    if cookie.name == "orgm_session":
                        self.cookies.clear(cookie.domain, cookie.path, cookie.name)
                self.save()


def transmit(video=None):
    with RemoteSender() as sender:
        if video is None:
            sender.authorize()
            notify("Atajo autorizado. Los próximos envíos irán directamente a Jarq.")
        else:
            sender.send(video)
            notify("Video enviado a YouTube en Jarq.")


def main():
    parser = argparse.ArgumentParser(
        description="Enviar a Jarq el enlace de YouTube seleccionado por HTTPS"
    )
    parser.add_argument(
        "--version", action="version", version="orgm-send-youtube 2 (HTTPS directo)"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--url", help="Usar este enlace en lugar de la selección")
    mode.add_argument(
        "--pair", action="store_true", help="Autorizar el atajo sin enviar un video"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validar y mostrar la petición sin enviarla",
    )
    args = parser.parse_args()
    if args.pair and args.dry_run:
        parser.error("--pair no necesita --dry-run")
    try:
        if args.pair:
            transmit()
            return
        # Invalid selections do not create a session, request approval or send HTTP.
        video = canonical_url(args.url if args.url is not None else selection())
        if args.dry_run:
            print(
                json.dumps(
                    {
                        "method": "POST",
                        "url": ROOM + "/api/apps/youtube/open-url",
                        "body": {"url": video},
                    }
                )
            )
            return
        transmit(video)
    except (ControlError, OSError, UnicodeError, subprocess.SubprocessError) as error:
        message = (
            str(error)
            if isinstance(error, ControlError)
            else "No se pudo enviar el enlace. Comprueba la selección y la conexión con Jarq."
        )
        notify(message)
        raise SystemExit(2)
