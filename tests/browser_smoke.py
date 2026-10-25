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
        if action == "switch-app":
            assert data['id'] in self.opened
            self.active=data['id']
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
                    "keys": True,
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
    page.add_init_script("sessionStorage.setItem('orgm-kiosk','yes')")
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"http://127.0.0.1:{port}/")
    page.locator("#pairing").wait_for(state="visible")
    page.fill("#pair-token", token.read_text())
    page.locator("#pair-form button").click()
    expect(page.locator('.app-youtube')).to_be_enabled()
    expect(page.locator('.app-tile:not([hidden])')).to_have_count(len(apps)-1)
    assert page.locator('.side-nav [data-catalog],.side-nav [data-panel=remote],.side-nav [data-panel=typing]').count()==0
    assert page.locator('[data-panel=settings]:visible').count()==1
    assert not page.locator('#remote .dpad').is_visible()
    assert not page.locator('#remote [data-home]').is_visible()
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
    kiosk.locator('.side-nav [data-panel=settings]').click()
    kiosk.locator('[data-settings-view=cast]').click()
    expect(kiosk.locator('#local-pairing')).to_be_visible()
    kiosk.locator('#generate-pair-code').click()
    expect(kiosk.locator('#pair-code')).to_have_text(__import__('re').compile(r'^\d{6}$'))
    invitation=kiosk.locator('#pair-code').inner_text()
    kiosk.screenshot(path=str(root/'pair-code-desktop.png'),full_page=True)
    kiosk.set_viewport_size({'width':390,'height':844})
    assert kiosk.evaluate('document.documentElement.scrollWidth<=innerWidth')
    kiosk.screenshot(path=str(root/'pair-code-mobile.png'),full_page=True)
    kiosk.set_viewport_size({'width':1920,'height':1080})
    phone=browser.new_page(viewport={'width':390,'height':844})
    phone.on('pageerror',lambda e:errors.append(str(e)))
    phone.goto(f'http://127.0.0.1:{port}/')
    phone.fill('#pair-token',invitation)
    phone.locator('#pair-form button').click()
    expect(phone.locator('#remote')).to_be_visible()
    expect(phone.locator('#remote .dpad')).to_be_visible()
    assert phone.locator('#local-pairing').is_hidden()
    assert phone.locator('#sources').is_hidden()
    phone.locator('#controller-nav [data-panel=sources]').click()
    phone.locator('.app-youtube').click()
    expect(phone.locator('#remote-title')).to_have_text('YouTube')
    for key in ['up','down','left','right','ok','tab','shift-tab','back']:
        phone.locator('#remote [data-key='+key+']').click()
        phone.wait_for_timeout(60)
        assert ('key',{'key':key}) in agent.calls
    phone.locator('#remote [data-home]').click()
    expect(phone.locator('#remote-title')).to_have_text('ORGM Home')
    expect(phone.locator('#remote [data-key=ok]')).to_be_enabled()
    for key in ['right','down','left','up','ok','back']:
        checkpoint=len(agent.calls)
        phone.locator('#remote [data-key='+key+']').click()
        phone.wait_for_timeout(60)
        assert ('key',{'key':key}) in agent.calls[checkpoint:]
    phone.locator('#controller-nav [data-panel=sources]').click()
    expect(phone.locator('.app-youtube')).to_be_visible()
    phone.locator('.app-youtube').click()
    expect(phone.locator('#remote')).to_be_visible()
    expect(phone.locator('#remote-title')).to_have_text('YouTube')
    expect(phone.locator('#remote [data-key=ok]')).to_be_enabled()
    phone.locator('#feedback').wait_for(state='hidden')
    for width,height,name in [(390,844,'remote-mobile'),(320,640,'remote-compact'),(1440,1000,'remote-desktop')]:
        phone.set_viewport_size({'width':width,'height':height})
        assert phone.evaluate('document.documentElement.scrollWidth<=innerWidth')
        for button in phone.locator('#remote button:visible').all():
            box=button.bounding_box()
            assert box['width']>=44 and box['height']>=44
        phone.screenshot(path=str(root/(name+'.png')),full_page=True)
    phone.set_viewport_size({'width':390,'height':844})
    phone.locator('#remote [data-switcher]').click()
    expect(phone.locator('#app-switcher')).to_be_visible()
    phone.screenshot(path=str(root/'switcher-mobile.png'),full_page=True)
    assert agent.active=='youtube'
    checkpoint=len(agent.calls)
    phone.locator('[data-switch-app=max]').click()
    expect(phone.locator('#remote-title')).to_have_text('Max')
    assert ('switch-app',{'id':'max'}) in agent.calls[checkpoint:]
    assert not any(action=='home' for action,_ in agent.calls[checkpoint:])
    phone.locator('#remote [data-switcher]').click()
    phone.locator('#switcher-list [aria-label="Cerrar YouTube"]').click()
    expect(phone.locator('[data-switch-app=youtube]')).to_have_count(0)
    assert agent.active=='max'
    phone.keyboard.press('Escape')
    expect(phone.locator('#app-switcher')).not_to_be_visible()
    phone.locator('#remote [data-panel=typing]').click()
    phone.fill('#remote-text','Buscar desde el teléfono')
    phone.locator('#text-form button[type=submit]').click()
    phone.wait_for_timeout(100)
    assert ('text',{'text':'Buscar desde el teléfono'}) in agent.calls
    phone.locator('[data-return].return-remote').click()
    expect(phone.locator('#remote')).to_be_visible()
    phone.close()
    kiosk.locator('.side-nav [data-home]').click()
    assert kiosk.evaluate('location.hash')==''
    expect(kiosk.locator('.app-tile:not([hidden])')).to_have_count(len(apps)-1)
    assert kiosk.locator('.masthead').bounding_box()['y']>=104
    for cover in kiosk.locator('.app-art').all():cover.scroll_into_view_if_needed()
    kiosk.wait_for_function("() => [...document.querySelectorAll('.app-art')].every(i=>i.complete&&i.naturalWidth>0)")
    kiosk.locator('.side-nav [data-home]').click()
    expect(kiosk.locator('.app-youtube')).to_be_enabled()
    kiosk.wait_for_function("() => document.querySelector('.app-grid').scrollLeft<8")
    kiosk.screenshot(path=str(root/'kiosk.png'),full_page=True)
    # Local kiosk consumes native navigation; it must never echo it to the API.
    kiosk.locator('.app-youtube').focus()
    before=len(agent.calls)
    kiosk.keyboard.press('ArrowRight')
    expect(kiosk.locator('.home-selected')).to_have_attribute('data-app','netflix')
    assert len(agent.calls)==before
    kiosk.screenshot(path=str(root/'home-selection.png'),full_page=True)
    kiosk.keyboard.press('Enter')
    expect(kiosk.locator('#current-label')).to_have_text('Netflix')
    kiosk.keyboard.press('Home')
    expect(kiosk.locator('.home-selected')).to_have_attribute('data-app','netflix')
    kiosk.locator('.side-nav [data-panel=settings]').click()
    kiosk.keyboard.press('Home')
    expect(kiosk.locator('#sources')).to_be_visible()
    expect(kiosk.locator('.home-selected')).to_have_attribute('data-app','netflix')
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
