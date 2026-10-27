"""Persistent, individually revocable remotes and short-lived room approvals."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import time

from .protocol import ControlError


class Devices:
    """Only public device metadata is stored; credentials live in signed cookies."""

    def __init__(self, path: Path):
        self.path = path
        self.items = json.loads(path.read_text()) if path.exists() else {}
        if not isinstance(self.items, dict):
            raise ValueError("Invalid authorized device registry")

    def save(self):
        temporary = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w") as stream:
                os.fchmod(stream.fileno(), 0o600)
                json.dump(self.items, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def add(self, name, browser):
        if len(self.items) >= 100:
            raise ControlError("Revoca algún dispositivo antes de autorizar otro", 409)
        identity = secrets.token_hex(16)
        self.items[identity] = {
            "id": identity,
            "name": name,
            "browser": browser,
            "approved_at": int(time.time()),
        }
        try:
            self.save()
        except OSError:
            self.items.pop(identity, None)
            raise
        return identity

    def revoke(self, identity):
        if identity not in self.items:
            raise ControlError("Este dispositivo ya no está autorizado", 404)
        previous = self.items.pop(identity)
        try:
            self.save()
        except OSError:
            self.items[identity] = previous
            raise


class Sessions:
    def __init__(self, token: str, age: int, devices: Devices | None = None):
        if len(token) < 32:
            raise ValueError("Control token needs at least 32 characters")
        self.token = token
        self.secret = hashlib.sha256(token.encode()).digest()
        self.age = age
        self.devices = devices

    def sign(self, value):
        return hmac.new(self.secret, value.encode(), hashlib.sha256).hexdigest()

    def issue(self, device=None):
        csrf = secrets.token_urlsafe(24)
        subject = f"d.{device}" if device else f"l.{int(time.time())}"
        body = f"{subject}.{csrf}"
        return f"{body}.{self.sign(body)}", csrf

    def identity(self, value):
        try:
            kind, subject, csrf, signature = value.split(".")
            body = f"{kind}.{subject}.{csrf}"
            if not csrf or not hmac.compare_digest(signature, self.sign(body)):
                return None
            if kind == "l" and 0 <= time.time() - int(subject) <= self.age:
                return "local"
            if kind == "d" and self.devices and subject in self.devices.items:
                return subject
        except (ValueError, AttributeError):
            pass
        return None

    def verify(self, value):
        return value.split(".")[2] if self.identity(value) else None


def device_browser(agent):
    """A readable hint, never a trusted identity or a fingerprint."""
    os_name = next(
        (
            label
            for marker, label in [
                ("iPhone", "iPhone"),
                ("iPad", "iPad"),
                ("Android", "Android"),
                ("Windows", "Windows"),
                ("Macintosh", "Mac"),
                ("Linux", "Linux"),
            ]
            if marker in agent
        ),
        "Dispositivo",
    )
    browser = next(
        (
            label
            for marker, label in [
                ("Edg", "Edge"),
                ("Firefox", "Firefox"),
                ("FxiOS", "Firefox"),
                ("Chrome", "Chrome"),
                ("CriOS", "Chrome"),
                ("Safari", "Safari"),
            ]
            if marker in agent
        ),
        "Navegador",
    )
    return f"{os_name} · {browser}"


class PairingRequests:
    def __init__(self, devices):
        self.devices = devices
        self.items = {}

    def get(self, credential):
        key = hashlib.sha256(credential.encode()).hexdigest()
        item = self.items.get(key)
        if item and time.monotonic() >= item["expires"]:
            item["status"] = "expired"
        return item

    def request(self, credential, name, browser):
        existing = self.get(credential) if credential else None
        if existing and existing["status"] == "pending":
            return credential, existing
        now = time.monotonic()
        self.items = {
            key: item for key, item in self.items.items() if item["expires"] > now
        }
        if sum(item["status"] == "pending" for item in self.items.values()) >= 3:
            raise ControlError(
                "Jarq tiene solicitudes pendientes. Espera un momento.", 429
            )
        credential = secrets.token_urlsafe(32)
        item = {
            "id": secrets.token_hex(16),
            "name": name or browser,
            "browser": browser,
            "status": "pending",
            "expires": now + 120,
        }
        self.items[hashlib.sha256(credential.encode()).hexdigest()] = item
        return credential, item

    def pending(self):
        now = time.monotonic()
        return [
            {
                **{key: item[key] for key in ["id", "name", "browser"]},
                "expires_in": max(0, int(item["expires"] - now)),
            }
            for item in self.items.values()
            if item["status"] == "pending" and item["expires"] > now
        ]

    def decide(self, identity, approve):
        item = next(
            (item for item in self.items.values() if item["id"] == identity), None
        )
        if (
            not item
            or item["status"] != "pending"
            or item["expires"] <= time.monotonic()
        ):
            raise ControlError("La solicitud ya terminó o venció", 409)
        if approve:
            item["device"] = self.devices.add(item["name"], item["browser"])
        item["status"] = "approved" if approve else "rejected"
