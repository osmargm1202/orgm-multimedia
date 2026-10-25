"""Authenticated pump actions through the private host gateway."""

import asyncio
import json
import os

from pydantic import BaseModel, ConfigDict, StrictInt

from .protocol import ControlError


class PumpTime(BaseModel):
    model_config = ConfigDict(extra="forbid")
    minutes: StrictInt


class PumpClient:
    def __init__(self, command=None):
        self.command = command or os.environ.get("ORGM_BOMBA_COMMAND", "")

    async def call(self, action, minutes=None):
        if not self.command:
            raise ControlError("La bomba todavía no está configurada en esta sala", 503)
        arguments = [self.command, "--json", action]
        if minutes is not None:
            arguments.append(str(minutes))
        try:
            process = await asyncio.create_subprocess_exec(
                *arguments,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError as exc:
            raise ControlError("El controlador de la bomba no está disponible", 503) from exc
        try:
            output, _ = await asyncio.wait_for(process.communicate(), timeout=60)
        except (TimeoutError, asyncio.CancelledError) as exc:
            process.kill()
            await process.wait()
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise ControlError("La bomba no respondió; comprueba su estado antes de reintentar", 504) from exc
        try:
            response = json.loads(output)
            if response.get("ok") is not True:
                raise ControlError(response.get("error", "No se pudo controlar la bomba"), 503)
            return response["result"]
        except (ValueError, KeyError, AttributeError) as exc:
            raise ControlError("El controlador de la bomba devolvió una respuesta no válida", 502) from exc


def install_routes(app):
    app.state.pump = PumpClient()

    @app.get("/api/pump/status")
    async def status():
        return await app.state.pump.call("status")

    @app.post("/api/pump/time")
    async def timed(payload: PumpTime):
        if payload.minutes not in {5, 10, 15, 20, 30, 40}:
            raise ControlError("Elige 5, 10, 15, 20, 30 o 40 minutos", 422)
        return await app.state.pump.call("time", payload.minutes)

    @app.post("/api/pump/off")
    async def off():
        return await app.state.pump.call("down")
