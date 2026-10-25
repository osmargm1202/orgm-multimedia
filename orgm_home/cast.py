"""LAN-only YouTube DIAL discovery and a fixed-port bridge to VacuumTube.

Runs as a separate system user. The multimedia user's private-network egress
policy stays intact; only the paired loopback API may launch YouTube.
"""

from __future__ import annotations

import asyncio
import http.cookiejar
import ipaddress
import json
import os
import socket
import time
import uuid
from contextlib import asynccontextmanager
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import (
    HTTPCookieProcessor,
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
    build_opener,
)
from xml.sax.saxutils import escape

import uvicorn
from fastapi import FastAPI
from fastapi import Request as WebRequest
from fastapi.responses import Response

from .protocol import ControlError

PORT = 8766
GROUP = "239.255.255.250"
SERVICE = "urn:dial-multiscreen-org:service:dial:1"
DEVICE = "urn:dial-multiscreen-org:device:dial:1"
PATHS = {"/apps/YouTube", "/apps/YouTube/run"}
STOPPED = ('<?xml version="1.0"?><service xmlns="urn:dial-multiscreen-org:schemas:dial">'
           '<name>YouTube</name><options allowStop="false"/><state>stopped</state></service>')


def trusted(address, networks):
    try:
        ip = ipaddress.ip_address(address)
        return any(ip in net for net in networks)
    except ValueError:
        return False


def interface_addresses(networks):
    # UDP connect selects the LAN source without sending a packet. Refresh
    # periodically so reconnecting Wi-Fi does not leave an old advertisement.
    result = set()
    for network in networks:
        if network.version != 4 or network.is_loopback:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            try:
                probe.connect((str(next(network.hosts(), network.network_address)), 1900))
                address = probe.getsockname()[0]
                if trusted(address, [network]):
                    result.add(address)
            except OSError:
                pass
    return result


def native_ports(uid=1100):
    """Read listening sockets, not other users' process command lines."""
    ports = []
    for row in Path("/proc/net/tcp").read_text().splitlines()[1:]:
        fields = row.split()
        if fields[3] != "0A" or int(fields[7]) != uid:
            continue
        address, port = fields[1].split(":")
        number = int(port, 16)
        if address in {"00000000", "0100007F"} and number >= 32768:
            ports.append(number)
    return ports


class Launcher:
    def __init__(self):
        self.client = build_opener(ProxyHandler({}), HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.base = "http://127.0.0.1:8765"
        self.csrf = None

    def activate(self):
        credential = Path(os.environ["CREDENTIALS_DIRECTORY"]) / "control-token"
        def post(path, payload, csrf=""):
            request = Request(self.base + path, data=json.dumps(payload).encode(), headers={
                "Origin": self.base, "Content-Type": "application/json", "X-CSRF-Token": csrf,
            })
            with self.client.open(request, timeout=25) as response:
                return json.load(response)
        try:
            if self.csrf is None:
                self.csrf = post("/api/session", {"token": credential.read_text().strip()})["csrf"]
            try:
                post("/api/apps/youtube/activate", {}, self.csrf)
            except HTTPError as exc:
                if exc.code not in {401, 403}:
                    raise
                self.csrf = post("/api/session", {"token": credential.read_text().strip()})["csrf"]
                post("/api/apps/youtube/activate", {}, self.csrf)
        except (OSError, ValueError, KeyError, URLError) as exc:
            raise ControlError("No se pudo abrir YouTube", 503) from exc


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class NativeBridge:
    def __init__(self):
        self.port = None
        self.client = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, method, path, body=b""):
        candidates = ([self.port] if self.port else []) + native_ports()
        for port in dict.fromkeys(candidates):
            base = f"http://127.0.0.1:{port}"
            try:
                # Verify the receiver before forwarding a launch payload.
                check = Request(base + "/apps/YouTube")
                with self.client.open(check, timeout=2) as response:
                    if b"<name>YouTube</name>" not in response.read(65537):
                        continue
                request = Request(base + path, method=method,
                                  data=body if method in {"POST", "DELETE"} else None,
                                  headers={"Content-Type": "application/x-www-form-urlencoded"})
                try:
                    response = self.client.open(request, timeout=5)
                except HTTPError as exc:
                    response = exc
                with response:
                    content = response.read(65537)
                    if len(content) > 65536:
                        raise ControlError("Respuesta DIAL demasiado grande", 502)
                    self.port = port
                    headers = {k: v for k, v in response.headers.items()
                               if k.lower() in {"content-type", "location", "application-url"}}
                    return response.status, headers, content, base
            except (OSError, URLError, HTTPException):
                continue
        self.port = None
        raise ControlError("El receptor de YouTube todavía no está listo", 503)


class Discovery(asyncio.DatagramProtocol):
    def __init__(self, networks, identity):
        self.networks, self.identity = networks, identity
        self.addresses = set()
        self.limits = {}

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, peer):
        if len(data) > 2048 or not trusted(peer[0], self.networks):
            return
        lines = data.decode("ascii", errors="ignore").splitlines()
        if not lines or lines[0].strip() != "M-SEARCH * HTTP/1.1":
            return
        headers = {k.lower().strip(): v.strip() for k, _, v in
                   (line.partition(":") for line in lines[1:]) if k}
        target = headers.get("st")
        if target not in {SERVICE, DEVICE, "ssdp:all"} or headers.get("man") != '"ssdp:discover"':
            return
        now = time.monotonic()
        if now - self.limits.get(peer[0], -100) < 1:
            return
        self.limits = {k: v for k, v in self.limits.items() if now - v < 30}
        self.limits[peer[0]] = now
        for address in self.addresses:
            if not any(ipaddress.ip_address(address) in net and ipaddress.ip_address(peer[0]) in net
                       for net in self.networks):
                continue
            st = SERVICE if target == "ssdp:all" else target
            packet = ("HTTP/1.1 200 OK\r\nCACHE-CONTROL: max-age=60\r\nEXT:\r\n"
                      f"LOCATION: http://{address}:{PORT}/\r\n"
                      f"SERVER: Linux UPnP/1.0 ORGMHome/1.0\r\nST: {st}\r\n"
                      f"USN: uuid:{self.identity}::{st}\r\n\r\n").encode()
            try:
                self.transport.sendto(packet, peer)
            except OSError:
                pass
            break

    async def refresh(self, sock):
        while True:
            addresses = interface_addresses(self.networks)
            for address in addresses - self.addresses:
                try:
                    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                                    socket.inet_aton(GROUP) + socket.inet_aton(address))
                except OSError:
                    pass
            self.addresses = addresses
            await asyncio.sleep(15)


def create_app(launcher=None, bridge=None, networks=None, discovery=True):
    networks = networks if networks is not None else [
        ipaddress.ip_network(n) for n in os.getenv("ORGM_DIAL_NETWORKS", "").split(",") if n
    ]
    identity = str(uuid.uuid5(uuid.NAMESPACE_DNS, socket.gethostname() + ".orgm-youtube"))
    launcher, bridge = launcher or Launcher(), bridge or NativeBridge()
    launching = asyncio.Lock()
    limits = {}

    @asynccontextmanager
    async def lifespan(app):
        if not discovery:
            yield
            return
        protocol = Discovery(networks, identity)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", 1900))
        transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(lambda: protocol, sock=sock)
        task = asyncio.create_task(protocol.refresh(transport.get_extra_info("socket")))
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            transport.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def guard(request, call_next):
        peer = request.client.host if request.client else ""
        allowed = networks + [ipaddress.ip_network("127.0.0.0/8")]
        try:
            host = urlsplit("http://" + request.headers.get("host", "")).hostname or ""
        except ValueError:
            return Response(status_code=400)
        if not trusted(peer, allowed) or not trusted(host, allowed):
            return Response(status_code=403)
        origin = request.headers.get("origin")
        if origin and origin not in {"https://www.youtube.com", "https://m.youtube.com", "package:com.google.android.youtube"}:
            return Response(status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        if origin:
            response.headers["Access-Control-Allow-Origin"] = origin
        return response

    @app.get("/")
    async def description(request: WebRequest):
        base = str(request.base_url).rstrip("/")
        name = escape(os.getenv("ORGM_DIAL_NAME", "ORGM Jarq · YouTube"))
        content = ('<?xml version="1.0"?><root xmlns="urn:schemas-upnp-org:device-1-0">'
                   '<specVersion><major>1</major><minor>0</minor></specVersion>'
                   f'<URLBase>{base}</URLBase><device><deviceType>{DEVICE}</deviceType>'
                   f'<friendlyName>{name}</friendlyName><manufacturer>VacuumTube</manufacturer>'
                   f'<modelName>ORGM Home</modelName><UDN>uuid:{identity}</UDN></device></root>')
        return Response(content, media_type="text/xml", headers={"Application-URL": base + "/apps"})

    @app.api_route("/apps/{path:path}", methods=["GET", "POST", "DELETE"])
    async def relay(path: str, request: WebRequest):
        path = "/apps/" + path
        if path not in PATHS or request.url.query:
            return Response(status_code=404)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 8192:
                return Response(status_code=413)
        try:
            async with launching:
                if request.method == "POST":
                    peer = request.client.host
                    now = time.monotonic()
                    limits[peer] = [t for t in limits.get(peer, []) if now - t < 60]
                    if len(limits[peer]) >= 10:
                        return Response(status_code=429)
                    if len(limits) > 256:
                        limits.clear()
                        limits[peer] = []
                    limits[peer].append(now)
                    await asyncio.to_thread(launcher.activate)
                deadline = time.monotonic() + (12 if request.method == "POST" else 0)
                while True:
                    try:
                        code, headers, content, native = await asyncio.to_thread(
                            bridge.request, request.method, path, bytes(body))
                        break
                    except ControlError:
                        if time.monotonic() >= deadline:
                            raise
                        await asyncio.sleep(0.3)
            base = str(request.base_url).rstrip("/")
            content = content.replace(native.encode(), base.encode())
            headers = {k: v.replace(native, base) for k, v in headers.items()}
            return Response(content, status_code=code, headers=headers)
        except ControlError as exc:
            if request.method == "GET":
                return Response(STOPPED, media_type="text/xml")
            return Response(str(exc), status_code=exc.status)

    return app


def main():
    uvicorn.run(create_app(), host="0.0.0.0", port=PORT, access_log=False)


if __name__ == "__main__":
    main()
