"""Short lived, authenticated viewers of a private WayVNC Unix socket."""
import asyncio
import secrets
import time
from pathlib import Path

from .protocol import ControlError

SOCKET = '/run/orgm-home/live.sock'


class LiveScreen:
    def __init__(self, run):
        self.run = run
        self.viewers = {}

    async def start(self):
        if len(self.viewers) >= 2:
            raise ControlError('Ya hay dos pantallas en directo abiertas.', 409)
        await self.run('systemctl', '--user', 'start', 'orgm-home-live.service')
        for _ in range(30):
            if Path(SOCKET).is_socket():
                token = secrets.token_hex(16)
                self.viewers[token] = time.monotonic()
                return {'viewer': token}
            await asyncio.sleep(.1)
        await self.expire()
        raise ControlError('No se pudo abrir la pantalla en directo.', 503)

    def renew(self, token):
        if token not in self.viewers:
            raise ControlError('La conexión de pantalla venció.', 410)
        self.viewers[token] = time.monotonic()
        return {'connected': True}

    async def close(self, token):
        self.viewers.pop(token, None)
        await self.expire()
        return {'closed': True}

    async def expire(self):
        before = bool(self.viewers)
        self.viewers = {key: stamp for key, stamp in self.viewers.items()
                        if time.monotonic() - stamp < 25}
        if not self.viewers and (before or Path(SOCKET).exists()):
            await self.run('systemctl', '--user', 'stop', 'orgm-home-live.service')
