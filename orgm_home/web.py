"""One FastAPI app serves the launcher, remote and authenticated control API."""

from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
import hashlib
import hmac
import logging
import os
from pathlib import Path
import secrets
import time
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import jwt
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from .agent import KEYS
from .config import Settings, load_catalog
from .protocol import AgentClient, ControlError
from .urls import validate_url

ROOT = Path(__file__).parent
LOG = logging.getLogger(__name__)


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Payload):
    token: StrictStr = Field(min_length=20, max_length=256)


class Key(Payload):
    key: StrictStr = Field(max_length=20)


class Text(Payload):
    text: StrictStr = Field(min_length=1, max_length=1000)


class Volume(Payload):
    value: StrictInt | None = Field(default=None, ge=0, le=100)
    delta: StrictInt | None = None


class Url(Payload):
    url: StrictStr = Field(min_length=1, max_length=2048)


class Brightness(Payload):
    value: StrictInt = Field(ge=5, le=100)


class LocalFile(Payload):
    name: StrictStr = Field(min_length=1, max_length=255)


class Sessions:
    def __init__(self, token: str, age: int):
        if len(token) < 32:
            raise ValueError("Control token needs at least 32 characters")
        self.token = token
        self.secret = hashlib.sha256(token.encode()).digest()
        self.age = age

    def sign(self, value):
        return hmac.new(self.secret, value.encode(), hashlib.sha256).hexdigest()

    def issue(self):
        csrf = secrets.token_urlsafe(24)
        body = f"{int(time.time())}.{csrf}"
        return f"{body}.{self.sign(body)}", csrf

    def verify(self, value):
        try:
            ts, csrf, signature = value.split(".")
            age = time.time() - int(ts)
            if not 0 <= age <= self.age or not hmac.compare_digest(
                signature, self.sign(f"{ts}.{csrf}")
            ):
                return None
            return csrf
        except (ValueError, AttributeError):
            return None


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
    sessions = Sessions(settings.token_file.read_text().strip(), settings.cookie_age)
    client = agent or AgentClient(settings.agent_socket)
    access = Access(settings)
    limits = RateLimit()
    origins = set(settings.origins)
    hosts = {urlsplit(origin).netloc for origin in origins}
    templates = Jinja2Templates(directory=str(ROOT / "templates"))
    app = FastAPI(title="ORGM Home", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.sessions = sessions

    @app.exception_handler(ControlError)
    async def control_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        def reject(message, code):
            return JSONResponse({"detail": message}, status_code=code)

        host = request.headers.get("host", "")
        if host not in hosts:
            return reject("Host no permitido", 400)
        public = host.split(":")[0] == settings.public_host
        is_api = request.url.path.startswith("/api/")
        peer = request.client.host if request.client else "unknown"
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
        if is_api and request.url.path not in {"/api/health", "/api/session"}:
            csrf = sessions.verify(request.cookies.get("orgm_session", ""))
            if not csrf:
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
                "Cache-Control": "no-store",
                "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
            }
        )
        return response

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"apps": [a.public() for a in apps.values() if a.id != "home"]},
        )

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    @app.post("/api/session")
    async def login(request: Request, payload: Login):
        peer = request.client.host if request.client else "unknown"
        if not limits.allow((peer, "login"), 5, 60):
            raise ControlError("Demasiados intentos; espera un minuto", 429)
        if not hmac.compare_digest(payload.token.encode(), sessions.token.encode()):
            raise ControlError("La clave de vinculación no es válida", 401)
        cookie, csrf = sessions.issue()
        response = JSONResponse({"csrf": csrf})
        response.set_cookie(
            "orgm_session",
            cookie,
            httponly=True,
            secure=request.headers["origin"].startswith("https:"),
            samesite="strict",
            max_age=settings.cookie_age,
            path="/",
        )
        return response

    @app.get("/api/session")
    async def session(request: Request):
        csrf = sessions.verify(request.cookies.get("orgm_session", ""))
        if not csrf:
            raise ControlError("Vincula este mando para continuar", 401)
        return {"csrf": csrf}

    @app.get("/api/apps")
    async def catalog():
        return {"apps": [a.public() for a in apps.values()]}

    @app.get("/api/status")
    async def status():
        try:
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
