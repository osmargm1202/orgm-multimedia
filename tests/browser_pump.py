"""Browser validation with a simulated pump; never sends physical commands."""

import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time

from playwright.sync_api import expect, sync_playwright
import uvicorn

from orgm_home.config import Settings
from orgm_home.web import create_app


class Agent:
    async def call(self, *_args, **_kwargs):
        return {"session": True, "app": "home", "open": ["home"], "volume": 40, "capabilities": {}}


class Pump:
    def __init__(self):
        self.state = "off"
        self.seconds = 0
        self.calls = []
        self.offline = False
        self.controller = "jarq"

    async def call(self, action, minutes=None):
        from orgm_home.protocol import ControlError
        if self.offline:
            raise ControlError("No hay conexión con el controlador de la bomba", 503)
        if action != "status":
            self.calls.append((action, minutes))
            self.state = "on" if action == "time" else "off"
            self.seconds = (minutes or 0) * 60
        return {"state": self.state, "remaining_seconds": self.seconds, "native_timer": True,
                "controller": self.controller, "fallback": self.controller == "orgm"}


root = Path(tempfile.mkdtemp(prefix="orgm-pump-browser-"))
catalog = root / "apps.json"
catalog.write_text(json.dumps({"apps": json.loads(Path(sys.argv[1]).read_text())}))
token = root / "token"
token.write_text("test-pump-pairing-token-at-least-32-characters")
with socket.socket() as listener:
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
settings = Settings(catalog, root / "agent.sock", token, (f"http://localhost:{port}", f"http://127.0.0.1:{port}"))
app = create_app(settings, Agent())
pump = Pump()
app.state.pump = pump
server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
worker = threading.Thread(target=server.run, daemon=True)
worker.start()
for _ in range(100):
    if server.started:
        break
    time.sleep(0.05)
try:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.getenv("ORGM_TEST_CHROMIUM", "/run/current-system/sw/bin/chromium"), headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 960})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(f"http://localhost:{port}/#pair={token.read_text()}")
        expect(page.locator(".app-youtube")).to_be_enabled()
        page.locator("#pump-open").click()
        expect(page.locator("#pump-state")).to_have_text("Apagada")
        expect(page.locator("#pump-controller")).to_contain_text("Control local de Jarq")
        expect(page.locator("[data-pump-minutes]")).to_have_count(6)
        for minutes in [5, 10, 15, 20, 30, 40]:
            page.locator(f'[data-pump-minutes="{minutes}"]').click()
            expect(page.locator("#pump-state")).to_contain_text(f"quedan {minutes}:00")
        assert pump.calls == [("time", minutes) for minutes in [5, 10, 15, 20, 30, 40]]
        page.screenshot(path=str(root / "desktop.png"), full_page=True)
        page.locator("#pump-off").click()
        expect(page.locator("#pump-state")).to_have_text("Apagada")
        page.keyboard.press("Escape")
        expect(page.locator("#pump-dialog")).not_to_be_visible()
        expect(page.locator("#pump-open")).to_be_focused()
        pump.controller = "orgm"
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator("#pump-open").click()
        expect(page.locator("#pump-state")).to_have_text("Apagada")
        expect(page.locator("#pump-controller")).to_contain_text("Respaldo OrgM activo")
        page.screenshot(path=str(root / "mobile.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        for width in [320, 390]:
            page.set_viewport_size({"width": width, "height": 844})
            box = page.locator("#pump-dialog").bounding_box()
            assert box["x"] >= 0 and box["x"] + box["width"] <= width
        pump.offline = True
        page.locator("#pump-close").click()
        page.locator("#pump-open").click()
        expect(page.locator("#pump-error")).to_be_visible()
        expect(page.locator('[data-pump-minutes="10"]')).to_be_disabled()
        pump.offline = False
        page.locator("#pump-retry").click()
        expect(page.locator('[data-pump-minutes="10"]')).to_be_enabled()
        assert not errors, errors
        browser.close()
finally:
    server.should_exit = True
    worker.join(timeout=5)
print(json.dumps({"result": "PASS", "screenshots": str(root), "simulated_actions": pump.calls}))
