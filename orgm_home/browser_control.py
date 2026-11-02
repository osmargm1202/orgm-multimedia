"""Fixed actions against the focused page in an app's private Chrome profile.

DevTools stays on loopback; neither a URL nor JavaScript comes from the remote.
"""
import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import build_opener, ProxyHandler

from websockets.asyncio.client import connect

from .protocol import ControlError

ASSETS = Path(__file__).with_name("navigation")
PROFILES = json.loads((ASSETS / "profiles.json").read_text())
SCRIPT = (ASSETS / "control.js").read_text()


def allowed(url, hosts):
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    return parsed.scheme == "https" and any(host == h or host.endswith('.' + h) for h in hosts)


class BrowserControl:
    def __init__(self, app_id, port=None):
        self.app_id = app_id
        self.port = port

    def targets(self):
        path = Path.home() / '.local/share/orgm-home/chrome' / self.app_id / 'DevToolsActivePort'
        port = self.port if self.port is not None else int(path.read_text().splitlines()[0])
        if not 1 <= port <= 65535:
            raise ValueError('Invalid port')
        opener = build_opener(ProxyHandler({}))
        with opener.open(f'http://127.0.0.1:{port}/json/list', timeout=2) as response:
            targets = json.loads(response.read(1024 * 1024))
        result = []
        for target in targets:
            endpoint = target.get('webSocketDebuggerUrl', '')
            parsed = urlsplit(endpoint)
            if (target.get('type') == 'page' and parsed.scheme == 'ws'
                    and parsed.hostname in {'127.0.0.1', 'localhost'} and parsed.port == port):
                result.append(target)
        return result

    async def act(self, action, expected_id=None):
        if action not in {'up', 'down', 'left', 'right', 'ok', 'search', 'play', 'start'}:
            raise ControlError('Control no permitido', 422)
        profile = PROFILES.get(self.app_id, {})
        # Generic directional selection is useful for other Chrome catalogue apps.
        options = {**profile, 'action': action, 'expected_id': expected_id}
        expression = '(' + SCRIPT + ')(' + json.dumps(options) + ')'
        try:
            async with asyncio.timeout(6):
                for target in await asyncio.to_thread(self.targets):
                    async with connect(target['webSocketDebuggerUrl'], open_timeout=2, max_size=1024*1024) as ws:
                        async def evaluate(identifier, script):
                            await ws.send(json.dumps({'id': identifier, 'method': 'Runtime.evaluate', 'params': {
                                'expression': script, 'returnByValue': True, 'awaitPromise': True, 'userGesture': True}}))
                            while True:
                                message = json.loads(await ws.recv())
                                if message.get('id') == identifier:
                                    if 'error' in message or 'exceptionDetails' in message.get('result', {}):
                                        raise ControlError('La página no pudo ejecutar el control', 409)
                                    return message.get('result', {}).get('result', {}).get('value')
                        if not await evaluate(1, 'document.hasFocus() && document.visibilityState === "visible"'):
                            continue
                        if profile and not allowed(target.get('url', ''), profile['hosts']):
                            raise ControlError('Vuelve a la página del servicio para usar este control', 409)
                        result = await evaluate(2, expression)
                        if not result or not result.get('ok'):
                            raise ControlError((result or {}).get('error', 'Control no disponible'), 409)
                        return {'navigation': result.get('mode', action)}
        except ControlError:
            raise
        except Exception as exc:
            # Do not expose URLs, page contents, profile paths or protocol errors.
            raise ControlError('El navegador aún no tiene el mando conectado. Reabre esta aplicación.', 409) from exc
        raise ControlError('No hay una página enfocada para este control', 409)

    async def navigate(self, url):
        from .media_links import media_link
        try:
            target = media_link(url)
        except ControlError:
            # Retain the existing Max endpoint's public service URLs.
            if self.app_id != 'max' or not allowed(url, PROFILES['max']['hosts']):
                raise
            from .urls import validate_max_url
            target_url = await validate_max_url(url)
        else:
            if target.app != self.app_id:
                raise ControlError('El enlace no corresponde a esta aplicación', 422)
            target_url = target.url
        try:
            async with asyncio.timeout(6):
                for page in await asyncio.to_thread(self.targets):
                    async with connect(page['webSocketDebuggerUrl'], open_timeout=2) as ws:
                        await ws.send(json.dumps({'id':1,'method':'Runtime.evaluate','params':{'expression':'document.hasFocus()','returnByValue':True}}))
                        while True:
                            result=json.loads(await ws.recv())
                            if result.get('id')==1:break
                        if not result.get('result',{}).get('result',{}).get('value'):continue
                        await ws.send(json.dumps({'id':2,'method':'Page.navigate','params':{'url':target_url}}))
                        while True:
                            result=json.loads(await ws.recv())
                            if result.get('id')==2:break
                        if 'error' in result or result.get('result',{}).get('errorText'):
                            raise ControlError('No se pudo abrir el contenido en esta ventana',409)
                        return
        except ControlError:raise
        except Exception:
            raise ControlError('Reabre esta aplicación para conectar su navegador',409) from None
        raise ControlError('No hay una ventana enfocada para abrir el enlace',409)
