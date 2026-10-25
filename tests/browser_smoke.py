"""Run with: uv run --with playwright python tests/browser_smoke.py /path/apps-array.json

Uses a real HTTP server/browser and a simulated session agent; does not certify Sway.
"""

import json, os, secrets, socket, sys, tempfile, threading, time
from pathlib import Path
import uvicorn
from playwright.sync_api import sync_playwright, expect
from orgm_home.config import Settings
from orgm_home.web import create_app


class PreviewAgent:
    def __init__(self):
        self.active = "home"
        self.calls = []
        self.brightness = 35
        self.background = "costa"

    async def call(self, action, **data):
        self.calls.append((action, data))
        if action == "activate":
            self.active = data["id"]
        if action == "home":
            self.active = "home"
        if action == "brightness":
            self.brightness = data["value"]
        if action == "background":
            self.background=data["id"]
        if action == "status":
            return {
                "session": True,
                "app": self.active,
                "title": "ORGM Home"
                if self.active == "home"
                else "Reproducción de prueba",
                "volume": 45,
                "brightness": self.brightness,
                "background": self.background,
                "muted": False,
                "open": ["home", self.active],
                "capabilities": {
                    "keys": self.active != "home",
                    "text": self.active != "home",
                    "play": self.active != "home",
                    "close": self.active != "home",
                },
            }
        return {"app": self.active}


root = Path(tempfile.mkdtemp(prefix="orgm-browser-"))
apps = json.loads(Path(sys.argv[1]).read_text())
catalog = root / "apps.json"
catalog.write_text(json.dumps({"apps": apps}))
token = root / "token"
token.write_text(secrets.token_hex(32))
agent = PreviewAgent()
port = 18765
settings = Settings(catalog, root / "agent.sock", token, (f"http://127.0.0.1:{port}",))
server = uvicorn.Server(
    uvicorn.Config(
        create_app(settings, agent),
        host="127.0.0.1",
        port=port,
        log_level="error",
        access_log=False,
    )
)
thread = threading.Thread(target=server.run, daemon=True)
thread.start()
for _ in range(50):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.1):
            break
    except OSError:
        time.sleep(0.1)
with sync_playwright() as p:
    browser = p.chromium.launch(
        executable_path=os.getenv(
            "ORGM_TEST_CHROMIUM", "/run/current-system/sw/bin/chromium"
        ),
        headless=True,
        args=["--no-sandbox"],
    )
    errors = []
    context = browser.new_context(
        viewport={"width": 1440, "height": 1000}, device_scale_factor=1
    )
    page = context.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"http://127.0.0.1:{port}/")
    page.locator("#pairing").wait_for(state="visible")
    page.fill("#pair-token", token.read_text())
    page.locator("#pair-form button").click()
    page.locator("[data-app=youtube]").wait_for(state="visible")
    expect(page.locator("[data-app=youtube]")).to_be_enabled()
    page.screenshot(path=str(root / "desktop.png"), full_page=True)
    page.locator("[data-app=youtube]").click()
    expect(page.locator("#current-label")).to_have_text("YouTube")
    page.locator("[data-key=up]").click()
    page.wait_for_timeout(100)
    assert ("key", {"key": "up"}) in agent.calls
    page.locator("[data-home]").click()
    expect(page.locator("#current-label")).to_have_text("ORGM Home")
    page.set_viewport_size({"width": 390, "height": 844})
    page.screenshot(path=str(root / "mobile.png"), full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.locator("[data-app=netflix]").click()
    expect(page.locator("#current-label")).to_have_text("Netflix")
    assert page.locator("#remote").is_visible()
    page.screenshot(path=str(root / "remote-mobile.png"), full_page=True)
    page.locator(".mobile-nav [data-panel=typing]").click()
    page.fill("#remote-text", "Una búsqueda desde el sofá")
    page.locator("#text-form button[type=submit]").click()
    page.wait_for_timeout(150)
    assert ("text", {"text": "Una búsqueda desde el sofá"}) in agent.calls
    page.screenshot(path=str(root / "typing-mobile.png"), full_page=True)
    page.set_viewport_size({"width": 320, "height": 640})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    # Unpaired kiosk bootstrap must remove the fragment and activate without input.
    kiosk = browser.new_page(viewport={"width": 1920, "height": 1080})
    kiosk.on("pageerror", lambda e: errors.append(str(e)))
    kiosk.goto(f"http://127.0.0.1:{port}/#pair={token.read_text()}")
    expect(kiosk.locator("[data-app=youtube]")).to_be_enabled()
    assert kiosk.evaluate("location.hash") == ""
    assert kiosk.locator(".remote").is_hidden()
    kiosk.screenshot(path=str(root / "kiosk.png"), full_page=True)
    for width, height in [(1536, 864), (1280, 720)]:
        kiosk.set_viewport_size({"width": width, "height": height})
        assert kiosk.evaluate("document.documentElement.scrollHeight <= innerHeight"), (width, height)
    assert kiosk.locator('#brightness').count()==0
    assert kiosk.locator('[data-key=play]').count()==0
    kiosk.locator('.header-actions [data-panel=settings]').click()
    expect(kiosk.locator('#settings')).to_be_visible()
    expect(kiosk.locator('button[data-background]')).to_have_count(5)
    kiosk.locator('[data-background=bosque]').click()
    expect(kiosk.locator('body')).to_have_attribute('data-background','bosque')
    kiosk.screenshot(path=str(root/'options-kiosk.png'),full_page=True)
    page.set_viewport_size({'width':390,'height':844})
    page.locator('.header-actions [data-panel=settings]').click()
    expect(page.locator('#settings')).to_be_visible()
    page.screenshot(path=str(root/'options-mobile.png'),full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.locator('.admin-options summary').click()
    page.locator('[data-admin=reboot]').click()
    expect(page.locator('#reboot-confirm')).to_be_visible()
    page.locator('#reboot-cancel').click()
    assert not any(action=='reboot' for action,_ in agent.calls)
    assert not errors, errors
    browser.close()
server.should_exit = True
thread.join(timeout=5)
print(
    json.dumps(
        {"result": "PASS", "screenshots": str(root), "actions": len(agent.calls)}
    )
)
