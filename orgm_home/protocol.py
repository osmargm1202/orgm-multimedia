"""Bounded JSON lines over a Unix socket, limited to the media user's UID."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

MAX_MESSAGE = 16384


class ControlError(Exception):
    def __init__(self, message: str, status: int = 503):
        super().__init__(message)
        self.status = status


class AgentClient:
    def __init__(self, path: Path):
        self.path = path

    async def call(self, action: str, **data):
        writer = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(str(self.path), limit=MAX_MESSAGE), 2
            )
            writer.write(json.dumps({"action": action, **data}).encode() + b"\n")
            await writer.drain()
            raw = await asyncio.wait_for(reader.readline(), 30)
            result = json.loads(raw)
            if not result.get("ok"):
                raise ControlError(
                    result.get("error", "No se pudo completar la acción"),
                    result.get("status", 503),
                )
            return result["data"]
        except (OSError, TimeoutError, ValueError) as exc:
            raise ControlError(
                "La sesión multimedia todavía no está disponible"
            ) from exc
        finally:
            if writer:
                writer.close()
                await writer.wait_closed()
