"""One FastAPI app serves the launcher, remote and authenticated control API."""

from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
import hmac
import ipaddress
import logging
import os
from pathlib import Path
import time
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.gzip import GZipMiddleware
import jwt
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from .agent import KEYS
from .assets import asset_url, cache_control, MANIFEST
from .config import Settings, load_catalog
from .protocol import AgentClient, ControlError
from .pump import install_routes as install_pump_routes
from .urls import validate_url, validate_max_url
from .pairing import Devices, PairingRequests, Sessions, device_browser
from .preferences import gallery
from .previews import directory as preview_directory

ROOT = Path(__file__).parent
LOG = logging.getLogger(__name__)


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Payload):
    token: StrictStr = Field(min_length=6, max_length=256)


class PairRequest(Payload):
    name: StrictStr = Field(default="", max_length=64)


class PairDecision(Payload):
    approve: bool = Field(strict=True)


class Key(Payload):
    key: StrictStr = Field(max_length=20)


class Text(Payload):
    text: StrictStr = Field(min_length=1, max_length=1000)


class Volume(Payload):
    value: StrictInt | None = Field(default=None, ge=0, le=100)
    delta: StrictInt | None = None


class Url(Payload):
    url: StrictStr = Field(min_length=1, max_length=2048)


class Background(Payload):
    id: StrictStr = Field(max_length=20)


class Brightness(Payload):
    value: StrictInt = Field(ge=5, le=100)


class LocalFile(Payload):
    name: StrictStr = Field(min_length=1, max_length=255)


class RateLimit:
    def __init__(self):
        self.buckets = OrderedDict()

    def allow(self, key, count, seconds):
        now = time.monotonic()
        bucket = self.buckets.setdefault(key, deque())
        self.buckets.move_to_end(key)
        while bucket and bucket[0] <= now - seconds:
            bucket.popleft()
        if len(self.buckets) > 2048:
            self.buckets.popitem(last=False)
        if len(bucket) >= count:
            return False
        bucket.append(now)
        return True


class Access:
    def __init__(self, settings):
        self.settings = settings
        self.keys = None
        if settings.access_team:
            issuer = urlsplit(settings.access_team)
            if (
                issuer.scheme != "https"
                or not issuer.hostname
                or not issuer.hostname.endswith(".cloudflareaccess.com")
                or issuer.path
                or issuer.query
                or issuer.fragment
                or issuer.username
                or issuer.port
            ):
                raise ValueError(
                    "ORGM_ACCESS_TEAM must be an HTTPS Cloudflare Access team origin"
                )
            self.keys = jwt.PyJWKClient(
                f"{settings.access_team}/cdn-cgi/access/certs",
                cache_keys=True,
                lifespan=300,
                timeout=4,
            )

    async def verify(self, token):
        if not self.keys or not self.settings.access_aud:
            raise ControlError("Falta configurar Cloudflare Access en el origen", 503)
        if not token or len(token) > 8192:
            raise ControlError("Se requiere acceso familiar autorizado", 401)
        try:
            key = await asyncio.to_thread(self.keys.get_signing_key_from_jwt, token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                audience=self.settings.access_aud,
                issuer=self.settings.access_team,
                options={"require": ["exp", "iat", "iss", "aud", "sub", "email"]},
            )
            if (
                self.settings.access_emails
                and claims["email"].lower() not in self.settings.access_emails
            ):
                raise ControlError("Esta cuenta no está autorizada", 403)
        except (jwt.PyJWTError, ValueError, KeyError) as exc:
            raise ControlError(
                "La sesión de Cloudflare Access no es válida", 401
            ) from exc


def create_app(settings=None, agent=None):
    settings = settings or Settings.from_env()
    apps = load_catalog(settings.catalog)
    devices = Devices(settings.token_file.with_name("devices.json"))
    sessions = Sessions(settings.token_file.read_text().strip(), settings.cookie_age, devices)
    client = agent or AgentClient(settings.agent_socket)
    access = Access(settings)
    limits = RateLimit()
    origins = set(settings.origins)
    hosts = {urlsplit(origin).netloc for origin in origins}
    templates = Jinja2Templates(directory=str(ROOT / "templates"))
    templates.env.globals.update(asset=asset_url, assets_version=MANIFEST['version'], asset_files=MANIFEST['files'])
    app = FastAPI(title="ORGM Home", docs_url=None, redoc_url=None, openapi_url=None)
    install_pump_routes(app)
    app.state.sessions = sessions
    app.state.pairing_requests = PairingRequests(devices)
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=4)

    @app.exception_handler(ControlError)
    async def control_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        def reject(message, code):
            return JSONResponse({"detail": message}, status_code=code, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

        host = request.headers.get("host", "")
        if host not in hosts:
            return reject("Host no permitido", 400)
        public = host.split(":")[0] == settings.public_host
        is_api = request.url.path.startswith("/api/")
        peer = request.client.host if request.client else "unknown"
        # Nginx overwrites this header; only loopback proxy connections may use it.
        if public and peer in {"127.0.0.1", "::1"} and request.headers.get("x-real-ip"):
            try:
                peer = str(ipaddress.ip_address(request.headers['x-real-ip']))
            except ValueError:
                return reject("Dirección del proxy no válida", 400)
        if is_api:
            if not limits.allow((peer, "api"), 180, 60):
                return reject("Demasiadas acciones; espera unos segundos", 429)
            if public and settings.require_access:
                try:
                    await access.verify(request.headers.get("cf-access-jwt-assertion"))
                except ControlError as exc:
                    return reject(str(exc), exc.status)
        mutating = request.method not in {"GET", "HEAD", "OPTIONS"}
        if mutating:
            origin = request.headers.get("origin")
            if origin not in origins or urlsplit(origin).netloc != host:
                return reject("Origen no permitido", 403)
            if not request.headers.get("content-type", "").startswith(
                "application/json"
            ):
                return reject("Se requiere JSON", 415)
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 8192:
                    return reject("Petición demasiado grande", 413)
            request._body = bytes(body)
        if is_api and request.url.path not in {"/api/health", "/api/session", "/api/pairing/request", "/api/pairing/status"}:
            csrf = sessions.verify(request.cookies.get("orgm_session", ""))
            if not csrf or (sessions.identity(request.cookies.get("orgm_session", "")) == "local" and not local_request(request)):
                return reject("Vincula este mando para continuar", 401)
            if mutating and not hmac.compare_digest(
                request.headers.get("x-csrf-token", ""), csrf
            ):
                return reject("La sesión del mando cambió; recarga la página", 403)
        try:
            response = await call_next(request)
        except ControlError as exc:
            response = reject(str(exc), exc.status)
        response.headers.update(
            {
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
                "Cache-Control": cache_control(request.query_params.get('v')) if request.url.path.startswith('/static/') and response.status_code < 400 else "no-store",
                "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
            }
        )
        return response

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "apps": [a.public() for a in apps.values() if a.id != "home"],
                "backgrounds": gallery(),
            },
        )

    @app.get("/airplay", response_class=HTMLResponse)
    async def airplay(request: Request):
        return templates.TemplateResponse(
            request=request, name="airplay.html",
            context={"receiver": os.getenv("ORGM_AIRPLAY_NAME", "ORGM Jarq")},
        )

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    @app.post("/api/wifi/open")
    async def wifi_open():
        return await client.call("wifi-open")

    @app.get("/api/previews/{app_id}")
    async def preview(app_id: str):
        if app_id not in apps or app_id == "home":
            raise ControlError("Aplicación desconocida", 404)
        path = preview_directory()/f'{app_id}.jpg'
        if not path.is_file():
            raise ControlError("Todavía no hay captura", 404)
        return FileResponse(path, media_type="image/jpeg")

    @app.post("/api/spotify/{action}")
    async def spotify_control(action: str):
        if action not in {"toggle", "next", "previous"}:
            raise ControlError("Control de Spotify desconocido", 404)
        return await client.call("spotify-" + action)

    def local_request(request):
        return urlsplit(str(request.url)).hostname in {"127.0.0.1", "localhost"} and request.client and request.client.host in {"127.0.0.1", "::1"}

    def local_admin(request):
        if not local_request(request) or sessions.identity(request.cookies.get("orgm_session", "")) != "local":
            raise ControlError("Esta autorización se gestiona en la pantalla de Jarq", 403)

    def session_response(request, device=None, existing=None, **extra):
        cookie, csrf = (existing, sessions.verify(existing)) if existing else sessions.issue(device)
        response = JSONResponse({"csrf": csrf, "local": device is None, **extra})
        response.set_cookie(
            "orgm_session", cookie, httponly=True,
            secure=request.url.scheme == "https" or (not local_request(request) and f"https://{request.headers['host']}" in origins),
            samesite="strict", max_age=34560000 if device else settings.cookie_age, path="/",
        )
        return response

    @app.post("/api/session")
    async def login(request: Request, payload: Login):
        peer = request.client.host if request.client else "unknown"
        if not limits.allow((peer, "login"), 5, 60):
            raise ControlError("Demasiados intentos; espera un minuto", 429)
        if not local_request(request) or not hmac.compare_digest(payload.token.encode(), sessions.token.encode()):
            raise ControlError("Solicita permiso desde home.or-gm.com", 401)
        return session_response(request)

    @app.get("/api/session")
    async def session(request: Request):
        identity = sessions.identity(request.cookies.get("orgm_session", ""))
        if not identity or (identity == "local" and not local_request(request)):
            raise ControlError("Vincula este mando para continuar", 401)
        return session_response(request, None if identity == "local" else identity, existing=request.cookies["orgm_session"])

    @app.post("/api/pairing/request")
    async def pairing_request(request: Request, payload: PairRequest):
        name = payload.name.strip()
        if any(ord(char) < 32 or ord(char) == 127 for char in name):
            raise ControlError("Usa un nombre sin caracteres de control", 422)
        credential = request.cookies.get("orgm_pairing", "")
        previous = app.state.pairing_requests.get(credential)
        # Proxy peers can be shared by the household. Bound fresh requests, not polls/retries.
        if not previous or previous['status'] != 'pending':
            if not limits.allow(("pairing", "room"), 12, 600):
                raise ControlError("Demasiadas solicitudes. Espera unos minutos.", 429)
        browser = device_browser(request.headers.get("user-agent", ""))
        credential, item = app.state.pairing_requests.request(credential, name, browser)
        response = JSONResponse({"status": "pending", "name": item['name'], "expires_in": max(0, int(item['expires'] - time.monotonic()))})
        response.set_cookie("orgm_pairing", credential, httponly=True, secure=request.url.scheme == "https" or request.headers["origin"].startswith("https:"), samesite="strict", max_age=120, path="/api/pairing")
        return response

    @app.get("/api/pairing/status")
    async def pairing_status(request: Request):
        item = app.state.pairing_requests.get(request.cookies.get("orgm_pairing", ""))
        if not item:
            return {"status": "expired"}
        if item['status'] == 'approved':
            device = item.get('device')
            if device not in devices.items:
                return {"status": "revoked"}
            response = session_response(request, device, status="approved")
            response.delete_cookie("orgm_pairing", path="/api/pairing")
            # Consume the approval; a second request cannot mint another session.
            item['status'] = 'claimed'
            return response
        return {"status": item['status'], "name": item['name'], "expires_in": max(0, int(item['expires'] - time.monotonic()))}

    @app.get("/api/admin/pairing")
    async def pending_pairing(request: Request):
        local_admin(request)
        return {"requests": app.state.pairing_requests.pending()}

    @app.post("/api/admin/pairing/{identity}")
    async def decide_pairing(identity: str, request: Request, payload: PairDecision):
        local_admin(request)
        app.state.pairing_requests.decide(identity, payload.approve)
        return {"ok": True}

    @app.get("/api/admin/devices")
    async def authorized_devices(request: Request):
        local_admin(request)
        return {"devices": sorted(devices.items.values(), key=lambda item: item['approved_at'], reverse=True)}

    @app.post("/api/admin/devices/{identity}/revoke")
    async def revoke_device(identity: str, request: Request):
        local_admin(request)
        devices.revoke(identity)
        return {"ok": True}

    @app.get("/api/apps")
    async def catalog():
        return {"apps": [a.public() for a in apps.values()]}

    @app.get("/api/status")
    async def status(previews: bool = False):
        try:
            if previews:
                await client.call('preview-demand')
            return await client.call("status")
        except ControlError as exc:
            return {
                "session": False,
                "app": None,
                "title": "",
                "volume": None,
                "muted": False,
                "open": [],
                "warning": str(exc),
                "capabilities": {},
            }

    @app.post("/api/apps/{app_id}/activate")
    async def activate(app_id: str):
        if app_id not in apps:
            raise ControlError("Aplicación desconocida", 404)
        return await client.call("activate", id=app_id)

    @app.post("/api/apps/{app_id}/close")
    async def close_app(app_id: str):
        if app_id not in apps:
            raise ControlError("Aplicación desconocida", 404)
        return await client.call("close-app", id=app_id)

    @app.post("/api/apps/{app_id}/switch")
    async def switch_app(app_id: str):
        if app_id not in apps:
            raise ControlError("Aplicación desconocida", 404)
        return await client.call("switch-app", id=app_id)

    @app.post("/api/apps/max/open-url")
    async def open_max(payload: Url):
        if "max" not in apps:
            raise ControlError("Max no está en el catálogo de esta sala", 404)
        return await client.call("open-max", url=await validate_max_url(payload.url))

    @app.post("/api/remote/key")
    async def key(payload: Key):
        if payload.key not in {*KEYS, "play", "mute", "stop", "next", "previous"}:
            raise ControlError("Tecla no permitida", 422)
        return await client.call(
            "mute" if payload.key == "mute" else "key",
            **({} if payload.key == "mute" else {"key": payload.key}),
        )

    @app.post("/api/remote/text")
    async def text(payload: Text):
        if any(ord(c) < 32 or ord(c) == 127 for c in payload.text):
            raise ControlError("El texto no puede contener caracteres de control", 422)
        return await client.call("text", text=payload.text)

    @app.post("/api/remote/pointer")
    async def pointer():
        raise ControlError(
            "El puntero remoto no está habilitado en esta instalación", 409
        )

    @app.post("/api/remote/home")
    async def home():
        return await client.call("home")

    @app.post("/api/remote/close")
    async def close():
        return await client.call("close")

    @app.post("/api/audio/volume")
    async def volume(payload: Volume):
        if (payload.value is None) == (payload.delta is None) or payload.delta not in {
            None,
            -5,
            5,
        }:
            raise ControlError("Indica un volumen de 0 a 100 o un cambio de 5", 422)
        return await client.call("volume", value=payload.value, delta=payload.delta)

    @app.post("/api/browser/open-url")
    async def open_url(payload: Url):
        return await client.call("open-url", url=await validate_url(payload.url))

    @app.get("/api/preferences")
    async def preferences():
        return await client.call("preferences")

    @app.post("/api/preferences/background")
    async def background(payload: Background):
        return await client.call("background", id=payload.id)

    @app.post("/api/admin/restart-launcher")
    async def restart_launcher():
        return await client.call("restart-launcher")

    @app.post("/api/admin/reboot")
    async def reboot():
        return await client.call("reboot")

    @app.post("/api/admin/poweroff")
    async def poweroff():
        return await client.call("poweroff")

    @app.post("/api/display/brightness")
    async def brightness(payload: Brightness):
        return await client.call("brightness", value=payload.value)

    @app.post("/api/display/rotate")
    async def rotate():
        return await client.call("rotate")

    @app.get("/api/videos")
    async def local_files():
        return await client.call("local-files")

    @app.post("/api/videos/play")
    async def play_file(payload: LocalFile):
        return await client.call("play-file", name=payload.name)

    app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
    return app


def main():
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        create_app(),
        host=os.getenv("ORGM_BIND", "127.0.0.1"),
        port=int(os.getenv("ORGM_PORT", "8765")),
        proxy_headers=False,
        access_log=False,
    )
