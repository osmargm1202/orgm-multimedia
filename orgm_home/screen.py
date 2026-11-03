"""On-demand JPEG and bounded clicks; no video stream or additional listener."""
import asyncio
import math
import secrets
import tempfile
import time
from pathlib import Path
from .previews import directory
from .protocol import ControlError


class ScreenControl:
    def __init__(self, run, sway, context):
        self.run, self.sway, self.context = run, sway, context
        self.frame = None
        self.captured = 0
        self.last_capture = -1e9
        self.layout = None

    @property
    def path(self):
        return directory() / '.screen.jpg'

    def validate(self, frame):
        if not self.frame or frame != self.frame or time.monotonic()-self.captured > 30:
            raise ControlError('La imagen venció o cambió. Pulsa Actualizar.', 410)

    async def capture(self):
        if time.monotonic()-self.last_capture < .75:
            raise ControlError('Espera un momento antes de actualizar.', 429)
        self.last_capture = time.monotonic()
        layout = await self.context()
        rect = layout['rect']
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.NamedTemporaryFile(dir=self.path.parent, suffix='.jpg', delete=False) as stream:
            temporary = Path(stream.name)
        try:
            scale = min(.5, 1024/max(rect['width'], rect['height']))
            await self.run('grim','-c','-o',layout['output'],'-s',str(scale),'-t','jpeg','-q','55',str(temporary),timeout=6)
            if not temporary.read_bytes().startswith(b'\xff\xd8') or temporary.stat().st_size>2_000_000:
                raise ControlError('No se pudo capturar esta pantalla.', 409)
            if layout != await self.context():
                raise ControlError('La pantalla cambió durante la captura. Actualiza.', 409)
            temporary.replace(self.path)
            self.frame = secrets.token_hex(16)
            self.captured = time.monotonic()
            self.layout = layout
            return {'frame':self.frame,'width':rect['width'],'height':rect['height'],'expires_in':30}
        finally:
            temporary.unlink(missing_ok=True)

    async def click(self, frame, x, y):
        self.validate(frame)
        if any(type(value) not in {float,int} or not math.isfinite(value) or not 0<=value<=1 for value in (x,y)):
            raise ControlError('Posición de clic inválida.',422)
        if self.layout != await self.context():
            raise ControlError('Cambió la ventana o el monitor. Actualiza antes de tocar.',409)
        rect=self.layout['rect']
        px=rect['x']+round(x*(rect['width']-1))
        py=rect['y']+round(y*(rect['height']-1))
        # Sway reserves zero as "do not change that axis". Use the nearest pixel.
        px=1 if px==0 else px
        py=1 if py==0 else py
        await self.sway(f'seat seat0 cursor set {px} {py}')
        try:
            await self.sway('seat seat0 cursor press BTN_LEFT')
            await asyncio.sleep(.025)
        finally:
            await self.sway('seat seat0 cursor release BTN_LEFT')
        return {'clicked':True}

    async def scroll(self, frame, x, y, dx, dy):
        self.validate(frame)
        if any(type(value) is not int or not -6<=value<=6 for value in (dx,dy)):
            raise ControlError('Desplazamiento inválido.',422)
        if any(type(value) not in {float,int} or not math.isfinite(value) or not 0<=value<=1 for value in (x,y)):
            raise ControlError('Posición de scroll inválida.',422)
        if self.layout != await self.context():
            raise ControlError('Cambió la ventana o el monitor. Actualiza antes de desplazar.',409)
        rect=self.layout['rect']
        px=rect['x']+round(x*(rect['width']-1));py=rect['y']+round(y*(rect['height']-1))
        await self.sway(f'seat seat0 cursor set {px if px else 1} {py if py else 1}')
        for value,positive,negative in ((dy,5,4),(dx,7,6)):
            for _ in range(abs(value)):
                # Sway emits a complete discrete axis event for buttons 4–7;
                # a release command here would emit a second scroll.
                await self.sway(f'seat seat0 cursor press button{positive if value>0 else negative}')
        return {'scrolled':True}

    def close(self, frame):
        if frame == self.frame:
            self.frame = None
            self.layout = None
            self.path.unlink(missing_ok=True)
        return {'closed':True}
