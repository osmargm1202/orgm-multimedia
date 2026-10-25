"""Public HTTP(S) destinations only. Chrome still needs its own network policy."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit

from .protocol import ControlError


async def validate_max_url(value: str) -> str:
    if not isinstance(value, str):
        raise ControlError("Copia un enlace HTTPS de Max o HBO Max", 422)
    url = await validate_url(value)
    parts = urlsplit(url)
    host = parts.hostname.lower()
    if parts.scheme != "https" or not any(host == domain or host.endswith("." + domain)
                                          for domain in ("max.com", "hbomax.com")):
        raise ControlError("Copia un enlace HTTPS de Max o HBO Max", 422)
    return url


async def validate_url(value: str) -> str:
    if (
        len(value) > 2048
        or any(ord(c) < 33 or ord(c) == 127 for c in value)
        or "\\" in value
    ):
        raise ControlError("El enlace no es válido", 422)
    try:
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username
            or parts.password
        ):
            raise ValueError
        if parts.port not in {None, 80, 443}:
            raise ValueError
        host = parts.hostname.encode("idna").decode("ascii")
        if (
            host.endswith(".")
            or "." not in host
            or host.lower().endswith(
                (".local", ".localhost", ".internal", ".ts.net", ".home", ".lan")
            )
        ):
            raise ValueError
        addresses = await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(
                host,
                parts.port or (443 if parts.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            ),
            3,
        )
        if not addresses or any(
            not ipaddress.ip_address(row[4][0]).is_global for row in addresses
        ):
            raise ValueError
    except (ValueError, UnicodeError, OSError, TimeoutError) as exc:
        raise ControlError(
            "Solo se permiten enlaces HTTP(S) a destinos públicos", 422
        ) from exc
    authority = f"[{host}]" if ":" in host else host
    if parts.port:
        authority += f":{parts.port}"
    return urlunsplit(
        (parts.scheme, authority, parts.path, parts.query, parts.fragment)
    )
