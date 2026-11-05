"""Keep one page per dedicated webapp profile, including across agent restarts."""

import asyncio
import contextlib
import json
from pathlib import Path

from websockets.asyncio.client import connect

from .browser_control import BrowserControl


class BrowserGuard:
    def __init__(self, state: Path):
        self.path = state / 'browser-primary.json'
        try:
            value = json.loads(self.path.read_text())
            self.primary = {key: target for key, target in value.items()
                            if isinstance(key, str) and isinstance(target, str)}
        except (OSError, ValueError, AttributeError):
            self.primary = {}

    def remember(self, app, target):
        if self.primary.get(app) == target:
            return
        self.primary[app] = target
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.primary))
        temporary.chmod(0o600)
        temporary.replace(self.path)

    async def reconcile(self, app, port):
        # No browser launch, page inspection, screenshots or external requests.
        # Run outside the controller lock so a slow browser cannot delay input.
        with contextlib.suppress(OSError, ValueError, TimeoutError, ConnectionError):
            try:
                async with asyncio.timeout(3):
                    targets = await asyncio.to_thread(BrowserControl(app, port).targets)
                    if not targets:
                        return
                    async with connect(targets[0]['webSocketDebuggerUrl'], open_timeout=1,
                                       max_size=1024 * 1024) as ws:
                        sequence = 0

                        async def call(method, params):
                            nonlocal sequence
                            sequence += 1
                            await ws.send(json.dumps({'id': sequence, 'method': method, 'params': params}))
                            while True:
                                reply = json.loads(await ws.recv())
                                if reply.get('id') == sequence:
                                    if 'error' in reply:
                                        raise ValueError('Browser target unavailable')
                                    return reply.get('result', {})

                        # /json/list omits openerId. Target.getTargets preserves
                        # this relationship even for cross-origin popups.
                        pages = {p['targetId']: p for p in
                                 (await call('Target.getTargets', {})).get('targetInfos', [])
                                 if p.get('type') == 'page' and p.get('targetId')}
                        main = self.primary.get(app)
                        if main not in pages:
                            roots = [ident for ident, page in pages.items() if not page.get('openerId')]
                            if len(roots) != 1:
                                # Never guess which of several pre-existing
                                # independent tabs contains the user's movie.
                                return
                            main = roots[0]
                            self.remember(app, main)
                        for ident in pages:
                            if ident != main:
                                await call('Target.closeTarget', {'targetId': ident})
            except Exception:
                # Browser exit / target closing between discovery and connect
                # is normal. Retry on the next tick, never relaunch the app.
                return
