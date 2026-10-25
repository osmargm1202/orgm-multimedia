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
        self.playing = False
        self.opened = {"home"}

    async def call(self, action, **data):
        self.calls.append((action, data))
        if action == "activate":
            self.active = data["id"]
            self.opened.add(self.active)
        if action == "home":
            self.active = "home"
        if action == "close-app":
            self.opened.discard(data["id"])
            if self.active == data["id"]:
                self.active = "home"
        if action == "open-max":
            self.active = "max"
            self.opened.add("max")
        if action == "brightness":
            self.brightness = data["value"]
        if action == "background":
            self.background=data["id"]
        if action == 'spotify-toggle':
            self.playing = not self.playing
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
                "spotify": {"available": True, "playing": self.playing, "title":"Sesión de prueba", "artist":"Spotify"},
                "open": sorted(self.opened),
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
    expect(page.locator('.app-youtube')).to_be_enabled()
    expect(page.locator('.app-tile:not([hidden])')).to_have_count(len(apps)-1)
    assert page.locator('.side-nav [data-catalog],.side-nav [data-panel=remote],.side-nav [data-panel=typing]').count()==0
    assert page.locator('[data-panel=settings]').count()==1
    assert page.locator('#remote .dpad,#remote [data-home],#remote [data-key=ok]').count()==0
    assert page.locator('[data-wifi]').count()==1
    page.locator('.app-youtube').click()
    expect(page.locator('#current-label')).to_have_text('YouTube')
    page.locator('#remote [data-key=back]').click()
    page.wait_for_timeout(100)
    assert ('key',{'key':'back'}) in agent.calls
    page.locator('.side-nav [data-home]').click()
    close = page.locator('[data-close-app=youtube]')
    expect(close).to_be_visible()
    assert close.bounding_box()['width'] >= 44 and close.bounding_box()['height'] >= 44
    close.click()
    expect(page.locator('[data-close-app=youtube]')).to_have_count(0)
    assert agent.active == 'home' and ('close-app', {'id':'youtube'}) in agent.calls
    page.locator('.app-youtube').click()
    page.locator('.side-nav [data-home]').click()
    page.locator('#spotify-toggle').click()
    expect(page.locator('#spotify-toggle')).to_have_attribute('aria-label','Pausar Spotify')
    for verb in ['previous','next']:
        page.locator('[data-spotify='+verb+']').click()
        page.wait_for_timeout(100)
        assert ('spotify-'+verb,{}) in agent.calls and agent.active=='home'
    page.locator('.music-cover').click()
    expect(page.locator('#current-label')).to_have_text('Spotify')
    assert agent.active=='spotify'
    page.locator('.side-nav [data-home]').click()
    page.locator('[data-wifi]').click()
    page.wait_for_timeout(100)
    assert ('wifi-open',{}) in agent.calls
    assert page.locator('#settings').is_hidden()
    for category,app_id in [('connect','airplay'),('tools','claude'),('photos','immich')]:
        page.locator('.category-tabs [data-category='+category+']').click()
        expect(page.locator('.app-'+app_id)).to_be_visible()
        for tile in page.locator('.app-tile:not([hidden])').all():
            assert tile.get_attribute('data-category')==category
    page.locator('.side-nav [data-home]').click()
    page.locator('.app-kick').scroll_into_view_if_needed()
    assert page.locator('.app-grid').evaluate('e=>e.scrollLeft>0')
    page.locator('.side-nav [data-home]').click()
    page.wait_for_function("() => document.querySelector('.app-grid').scrollLeft<8")
    page.locator('.side-nav [data-panel=settings]').click()
    expect(page.locator('#settings-menu')).to_be_visible()
    assert page.locator('#backgrounds-view').is_hidden() and page.locator('#admin-view').is_hidden()
    page.locator('[data-settings-view=backgrounds]').click()
    expect(page.locator('#backgrounds-view')).to_be_visible()
    assert page.locator('#admin-view').is_hidden()
    expect(page.locator('button[data-background]')).to_have_count(5)
    page.locator('[data-background=bosque]').click()
    expect(page.locator('body')).to_have_attribute('data-background','bosque')
    page.locator('#backgrounds-view [data-settings-view=menu]').click()
    page.locator('[data-settings-view=cast]').click()
    expect(page.locator('#cast-view')).to_be_visible()
    assert page.locator('#admin-view').is_hidden() and page.locator('#backgrounds-view').is_hidden()
    page.fill('#max-url','https://play.max.com/video/fixture')
    page.locator('#max-form button').click()
    expect(page.locator('#current-label')).to_have_text('Max')
    assert ('open-max',{'url':'https://play.max.com/video/fixture'}) in agent.calls
    page.locator('.side-nav [data-panel=settings]').click()
    page.locator('[data-settings-view=admin]').click()
    page.locator('[data-admin=reboot]').click()
    expect(page.locator('#reboot-confirm')).to_be_visible()
    page.locator('#reboot-cancel').click()
    assert not any(action=='reboot' for action,_ in agent.calls)
    page.locator('.side-nav [data-home]').click()
    expect(page.locator('#music')).to_be_visible()
    for width,height,name in [(1920,1080,'desktop'),(1280,720,'small'),(390,844,'mobile'),(320,640,'compact')]:
        page.set_viewport_size({'width':width,'height':height})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert page.locator('.side-nav').is_visible()
        assert page.locator('.side-nav [data-panel=settings]').is_visible()
        if width>=1280:
            assert page.locator('.music-controls').bounding_box()['width']>=150
        page.screenshot(path=str(root/(name+'.png')),full_page=True)
        for close in page.locator('[data-close-app]').all():
            assert close.bounding_box()['width'] >= 44 and close.bounding_box()['height'] >= 44
    kiosk=browser.new_page(viewport={'width':1920,'height':1080})
    kiosk.on('pageerror',lambda e:errors.append(str(e)))
    kiosk.goto(f'http://127.0.0.1:{port}/#pair={token.read_text()}')
    expect(kiosk.locator('.app-youtube')).to_be_enabled()
    assert kiosk.evaluate('location.hash')==''
    expect(kiosk.locator('.app-tile:not([hidden])')).to_have_count(len(apps)-1)
    assert kiosk.locator('.masthead').bounding_box()['y']>=104
    for cover in kiosk.locator('.app-art').all():cover.scroll_into_view_if_needed()
    kiosk.wait_for_function("() => [...document.querySelectorAll('.app-art')].every(i=>i.complete&&i.naturalWidth>0)")
    kiosk.locator('.side-nav [data-home]').click()
    expect(kiosk.locator('.app-youtube')).to_be_enabled()
    kiosk.wait_for_function("() => document.querySelector('.app-grid').scrollLeft<8")
    kiosk.screenshot(path=str(root/'kiosk.png'),full_page=True)
    kiosk.locator('.app-browser').click()
    expect(kiosk.locator('#current-label')).to_have_text('Navegador')
    kiosk.locator('[data-panel=typing]').click()
    kiosk.fill('#remote-text','Una búsqueda desde el sofá')
    kiosk.locator('#text-form button[type=submit]').click()
    page.wait_for_timeout(100)
    assert ('text',{'text':'Una búsqueda desde el sofá'}) in agent.calls
    assert not errors,errors
    page.goto(f'http://127.0.0.1:{port}/airplay')
    expect(page.locator('.receiver-name')).to_have_text('ORGM Jarq')
    browser.close()
server.should_exit = True
thread.join(timeout=5)
print(
    json.dumps(
        {"result": "PASS", "screenshots": str(root), "actions": len(agent.calls)}
    )
)
