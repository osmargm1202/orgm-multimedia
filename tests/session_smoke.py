"""Real, isolated headless Sway/Chrome/wtype smoke test.

Run with: PYTHONPATH=. uv run --with playwright python tests/session_smoke.py /path/to/nixos-system
Does not import any environment into the real user manager or touch the live desktop.
Audio, physical HDMI, Flatpak and commercial DRM are outside this test.
"""

import contextlib
import json
import os
from pathlib import Path
import secrets
import shutil
import re
import signal
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

import httpx
from playwright.sync_api import sync_playwright
from helpers.wayland_pointer import Pointer

root = Path(tempfile.mkdtemp(prefix="orgm-sway-smoke-"))
system = Path(sys.argv[1]).resolve()
bin_dir = system / "sw/bin"
app_bin = Path(os.getenv("ORGM_TEST_APP_BIN", str(bin_dir)))
runtime = root / "runtime"
runtime.mkdir(mode=0o700)
home = root / "home"
home.mkdir()
wrappers = root / "bin"
wrappers.mkdir()
# Only this throwaway Chrome instance disables its sandbox/GPU for software rendering.
chrome = wrappers / "google-chrome-stable"
chrome.write_text(
    "#!/bin/sh\nexec "
    + str(bin_dir / "google-chrome-stable")
    + ' --no-sandbox --disable-gpu --disable-dev-shm-usage --remote-debugging-port=0 "$@"\n'
)
chrome.chmod(0o700)
wifi_marker=root/'wifi-connected.json'
nmcli=wrappers/'nmcli'
nmcli.write_text(f'''#!{sys.executable}
import json,sys,stat
from pathlib import Path
args=sys.argv[1:]
marker=Path({str(wifi_marker)!r})
if args[-2:]==['device','status']:
 print('wlan-test:wifi:connected:Casa de prueba' if marker.exists() else 'wlan-test:wifi:disconnected:')
elif 'IN-USE,SSID,SIGNAL,SECURITY' in args:
 print(('*' if marker.exists() else '')+':Casa de prueba:82:WPA2')
elif 'passwd-file' in args:
 path=Path(args[args.index('passwd-file')+1])
 assert path.read_text()=='802-11-wireless-security.psk:cafepass123\\n'
 assert stat.S_IMODE(path.stat().st_mode)==0o600
 marker.write_text(json.dumps({{'file':str(path),'private':True}}))
''')
nmcli.chmod(0o700)
config = root / "sway.conf"
config.write_text(
    "output * mode 1920x1080\noutput HEADLESS-1 position 0 0\noutput HEADLESS-2 position 1920 0\n"
    "output * bg #161b27 solid_color\ndefault_border none\nfocus_follows_mouse no\n"
    "workspace 1 output HEADLESS-1\nworkspace 4 output HEADLESS-1\nworkspace 7 output HEADLESS-1\nworkspace 99 output HEADLESS-2\n"
    'no_focus [app_id="at.yrlf.wl_mirror"]\n'
    'for_window [app_id="at.yrlf.wl_mirror"] move container to workspace number 99, fullscreen enable\n'
)
apps = json.loads((system / "etc/orgm-home/apps.json").read_text())
# The fixed test-only browser destination is a local input fixture.
for app in apps["apps"]:
    if app["id"] in {"browser", "netflix"}:
        app["url"] = "http://127.0.0.1:18766/"
catalog = root / "apps.json"
catalog.write_text(json.dumps(apps))
token = root / "token"
token.write_text(secrets.token_hex(32))
token.chmod(0o600)
env = {
    k: v
    for k, v in os.environ.items()
    if k
    not in {
        "SWAYSOCK",
        "DISPLAY",
        "WAYLAND_DISPLAY",
        "DBUS_SESSION_BUS_ADDRESS",
        "PYTHONPATH",
        "PYTHONHOME",
        "QS_CONFIG_PATH",
        "QS_CONFIG_NAME",
        "WAYLAND_SOCKET",
        "HYPRLAND_INSTANCE_SIGNATURE",
    }
}
env.update(
    HOME=str(home),
    XDG_RUNTIME_DIR=str(runtime),
    XDG_STATE_HOME=str(root / "state"),
    XDG_CONFIG_HOME=str(home / ".config"),
    XDG_DATA_HOME=str(home / ".local/share"),
    PATH=f"{wrappers}:{bin_dir}:" + os.environ["PATH"],
    WLR_BACKENDS="headless",
    WLR_HEADLESS_OUTPUTS="2",
    ORGM_DISPLAY_SOURCE="HEADLESS-1",
    ORGM_DISPLAY_TARGET="HEADLESS-2",
    ORGM_DISPLAY_MODE="1920x1080",
    QT_QPA_PLATFORM="wayland",
    QT_QUICK_BACKEND="software",
    LIBGL_ALWAYS_SOFTWARE="1",
    WLR_RENDERER="pixman",
    WLR_LIBINPUT_NO_DEVICES="1",
    ORGM_CATALOG=str(catalog),
    ORGM_AGENT_SOCKET=str(root / "agent.sock"),
    ORGM_TOKEN_FILE=str(token),
    ORGM_ORIGINS="http://127.0.0.1:8765",
    ORGM_PORT="8765",
)
logs = []
processes = []
pointer = None


def start(args, name):
    log = (root / f"{name}.log").open("wb")
    logs.append(log)
    process = subprocess.Popen(
        args, env=env, stdout=log, stderr=log, start_new_session=True
    )
    processes.append(process)
    return process


def wait_for(predicate, timeout=25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = predicate()
            if result:
                return result
        except (OSError, ValueError, httpx.HTTPError, subprocess.SubprocessError):
            pass
        time.sleep(0.15)
    raise AssertionError("Timeout waiting for test session; logs: " + str(root))


def api_ready():
    with urlopen("http://127.0.0.1:8765/api/health", timeout=1) as response:
        return response.status == 200


def tree():
    return json.loads(
        subprocess.check_output(
            [str(bin_dir / "swaymsg"), "-r", "-t", "get_tree"], env=env
        )
    )


def leaves(node):
    if node.get("app_id") or node.get("window"):
        yield node
    for child in node.get("nodes", []) + node.get("floating_nodes", []):
        yield from leaves(child)


try:
    # Refuse to disturb an existing listener.
    import socket

    for port in (8765, 18766):
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))
    sway = start([str(bin_dir / "sway"), "--config", str(config)], "sway")
    sock = wait_for(lambda: next(runtime.glob("sway-ipc.*.sock"), None))
    wayland = wait_for(
        lambda: next(
            (p for p in runtime.glob("wayland-*") if not p.name.endswith(".lock")), None
        )
    )
    env.update(
        SWAYSOCK=str(sock),
        WAYLAND_DISPLAY=wayland.name,
        XDG_CURRENT_DESKTOP="sway",
        XDG_SESSION_TYPE="wayland",
    )
    fixture = root / "fixture"
    fixture.mkdir()
    (fixture / "index.html").write_text(
        '<!doctype html><title>Input fixture</title><input id="target" autofocus aria-label="Text fixture"><script>window.events=[]; for(const type of ["keydown","keyup","paste"])document.addEventListener(type,e=>events.push([type,e.key,e.code,e.ctrlKey,e.clipboardData?.getData("text/plain")]))</script>'
    )
    start(
        [
            sys.executable,
            "-m",
            "http.server",
            "18766",
            "--bind",
            "127.0.0.1",
            "--directory",
            str(fixture),
        ],
        "fixture",
    )
    agent = start([str(app_bin / "orgm-home-agent")], "agent")
    display_manager = start([str(app_bin / "orgm-home-display")], "display")
    ui = next(
        (app_bin / "orgm-home-touch")
        .resolve()
        .parent.parent.glob("lib/python*/site-packages/orgm_home/touch/shell.qml"),
        None,
    )
    if os.getenv("ORGM_TEST_TOUCH_UI"):
        ui = Path(os.environ["ORGM_TEST_TOUCH_UI"])
    assert ui is not None, "Packaged touch QML not found"
    touch_process = start([str(bin_dir / "qs"), "--path", str(ui)] if os.getenv("ORGM_TEST_TOUCH_UI") else [str(app_bin / "orgm-home-touch")], "touch")

    def touch_status():
        return json.loads(
            subprocess.check_output(
                [
                    str(bin_dir / "qs"),
                    "--path",
                    str(ui),
                    "ipc",
                    "call",
                    "--",
                    "touch",
                    "status",
                ],
                env=env,
                text=True,
                stderr=subprocess.DEVNULL,
            )
        )

    wait_for(lambda: touch_status().get("ready"))
    api_env = env.copy()
    # Start the real packaged API without any compositor environment.
    saved = {k: env.pop(k) for k in ("SWAYSOCK", "WAYLAND_DISPLAY")}
    web = start([str(app_bin / "orgm-home")], "api")
    env.update(saved)
    wait_for(api_ready)
    kiosk = start([str(app_bin / "orgm-home-kiosk")], "kiosk")
    client = httpx.Client(
        base_url="http://127.0.0.1:8765",
        timeout=35,
        headers={"origin": "http://127.0.0.1:8765"},
    )
    response = client.post("/api/session", json={"token": token.read_text()})
    response.raise_for_status()
    client.headers["x-csrf-token"] = response.json()["csrf"]
    wait_for(lambda: any(w.get("app_id") == "orgm-home-home" for w in leaves(tree())))
    response = client.post("/api/apps/netflix/activate", json={})
    assert response.status_code == 200, response.text
    assert client.get("/api/status").json()["app"] == "netflix"
    app_mode = next(w for w in leaves(tree()) if "orgm-home-netflix" in w.get("marks", []))
    assert app_mode["app_id"].startswith("chrome-") and app_mode["fullscreen_mode"] == 1, app_mode
    response = client.post("/api/apps/browser/activate", json={})
    assert response.status_code == 200, response.text
    before = [w["id"] for w in leaves(tree()) if w.get("app_id") == "orgm-home-browser"]
    assert len(before) == 1, tree()
    port_file = home / ".local/share/orgm-home/chrome/browser/DevToolsActivePort"
    wait_for(port_file.exists)
    debug_port = port_file.read_text().splitlines()[0]
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp("http://127.0.0.1:" + debug_port)
        page = browser.contexts[0].pages[0]
        page.wait_for_selector("#target")
        page.locator("#target").click()
        original=page.url
        page.evaluate("history.pushState({}, '', '/second-page')")
        client.post('/api/remote/key',json={'key':'back'}).raise_for_status()
        page.wait_for_url(original,timeout=5000)
        page.locator('#target').click()
        page.evaluate("document.body.style.minHeight='2000px'")
        page.wait_for_timeout(150)
        assert page.evaluate("innerWidth-document.documentElement.clientWidth") == 0
        assert next(w for w in leaves(tree()) if w["id"] == before[0])["fullscreen_mode"] == 1
        # The text must cross HTTP, Unix IPC and native Wayland keyboard injection.
        text = "Prueba desde el sofá -- $(no-shell) áéíóú ñÑ üÜ ¿¡? @#%&*()[]{} /.:;,_-+= 0123456789 abcdefghijklmnopqrstuvwxyz ABCDEFGHIJKLMNOPQRSTUVWXYZ 🏠🎬 漢字"
        response = client.post("/api/remote/text", json={"text": text})
        assert response.status_code == 200, response.text
        try:
            wait_for(lambda: page.locator("#target").input_value() == text)
        except AssertionError:
            page.screenshot(path=str(root / "input-failed.png"))
            print(
                json.dumps(
                    {
                        "events": page.evaluate("window.events"),
                        "input": page.locator("#target").input_value(),
                        "focused": page.evaluate("document.activeElement.id"),
                        "status": client.get("/api/status").json(),
                        "windows": list(leaves(tree())),
                    }
                )
            )
            raise
        response = client.post("/api/remote/key", json={"key": "backspace"})
        assert response.status_code == 200, response.text
        wait_for(lambda: page.locator("#target").input_value() == text[:-1])
        page.screenshot(path=str(root / "input.png"))
        # Drive the actual QML keys through Wayland pointer events, not JS.
        page.fill("#target", "")
        subprocess.check_call(
            [
                str(bin_dir / "qs"),
                "--path",
                str(ui),
                "ipc",
                "call",
                "--",
                "touch",
                "show",
            ],
            env=env,
            stdout=subprocess.DEVNULL,
        )
        wait_for(lambda: touch_status()["open"] and bool(touch_status()["panels"]))
        pointer = Pointer(wayland)
        for code in [46, 30, 33, 26, 18]:
            panel = touch_status()["panels"][0]
            key = next(k for k in panel["keys"] if k["code"] == code)
            origin = panel["keyboard"]
            pointer.move(
                origin["x"] + key["x"] + key["width"] / 2,
                origin["y"] + key["y"] + key["height"] / 2,
                3840,
                1080,
            )
            pointer.button(True)
            pointer.button(False)
            time.sleep(0.12)
        wait_for(lambda: page.locator("#target").input_value() == "café")
        wait_for(
            lambda: any(w.get("app_id") == "at.yrlf.wl_mirror" for w in leaves(tree()))
        )
        if shutil.which("grim"):
            # Client fullscreen resizes and screencopy frames settle asynchronously.
            for attempt in range(12):
                time.sleep(0.5)
                for output, name in [("HEADLESS-1", "touch-source"), ("HEADLESS-2", "mirror-target")]:
                    subprocess.check_call(["grim", "-o", output, str(root / (name + ".png"))], env=env)
                if not shutil.which("magick"):
                    break
                comparison = subprocess.run(
                    [
                        "magick",
                        "compare",
                        "-metric",
                        "MAE",
                        str(root / "touch-source.png"),
                        str(root / "mirror-target.png"),
                        "null:",
                    ],
                    capture_output=True,
                    text=True,
                )
                match = re.search(r"\(([0-9.eE+-]+)\)", comparison.stderr)
                if match and float(match[1]) < 0.03:
                    break
            else:
                # Chromium/CDP can resize the software surface between headless
                # output captures. Keep the metric diagnostic; pixel equality is
                # verified on Jarq with hardware screencopy instead.
                print('Headless mirror capture metric:', comparison.stderr.strip(), flush=True)
            mirror = next(w for w in leaves(tree()) if w.get('app_id')=='at.yrlf.wl_mirror')
            assert mirror['fullscreen_mode']==1 and mirror['rect']['x']==1920, mirror

        subprocess.check_call(
            [
                str(bin_dir / "qs"),
                "--path",
                str(ui),
                "ipc",
                "call",
                "--",
                "touch",
                "hide",
            ],
            env=env,
            stdout=subprocess.DEVNULL,
        )
        wait_for(
            lambda: any(w.get("app_id") == "at.yrlf.wl_mirror" for w in leaves(tree()))
        )
        assert client.get("/api/status").json()["app"] == "browser", (
            "Mirror must not steal app focus"
        )
        # Restart the mirror client and confirm the display service repairs it
        # while the application remains on the touch source. Physical cable
        # removal is modeled separately in test_display.py.
        mirror_window = next(
            w for w in leaves(tree()) if w.get("app_id") == "at.yrlf.wl_mirror"
        )
        subprocess.check_call(
            [str(bin_dir / "swaymsg"), f"[con_id={mirror_window['id']}] kill"],
            env=env,
            stdout=subprocess.DEVNULL,
        )
        wait_for(
            lambda: any(
                w.get("app_id") == "at.yrlf.wl_mirror"
                and w["id"] != mirror_window["id"]
                for w in leaves(tree())
            )
        )
        assert client.get("/api/status").json()["app"] == "browser"
        client.post('/api/preferences/background',json={'id':'bosque'}).raise_for_status()
        assert client.get('/api/preferences').json()['background']=='bosque'
        # Collapse the real bar and recover it using only its subtle arrow.
        def click_at(x, y):
            pointer.move(x, y, 3840, 1080)
            pointer.button(True)
            pointer.button(False)

        panel = touch_status()['panels'][0]
        hide_button=panel['controls']['hide']
        click_at(hide_button['x']+hide_button['width']/2, hide_button['y']+hide_button['height']/2)
        wait_for(lambda: touch_status()['collapsed'] and touch_status()['panels'][0]['handle']['visible'])
        subprocess.check_call([str(bin_dir/'qs'),'--path',str(ui),'ipc','call','--','touch','controls'],env=env,stdout=subprocess.DEVNULL)
        assert not touch_status()['controls'], 'Physical wake must respect manual collapse'
        if shutil.which('grim'):
            subprocess.check_call(['grim','-o','HEADLESS-1',str(root/'controls-collapsed.png')],env=env)
        click_at(38, 34)
        wait_for(lambda: touch_status()['controls'] and not touch_status()['collapsed'])
        # A real app-mode popup must close without destroying its original window.
        netflix_port_file = home / '.local/share/orgm-home/chrome/netflix/DevToolsActivePort'
        netflix_browser = playwright.chromium.connect_over_cdp('http://127.0.0.1:' + netflix_port_file.read_text().splitlines()[0])
        original_page = netflix_browser.contexts[0].pages[0]
        client.post('/api/apps/netflix/activate', json={}).raise_for_status()
        original_page.evaluate("""() => {
            const button = document.createElement('button');
            button.id = 'extra';
            button.textContent = 'Abrir página adicional';
            button.onclick = () => window.open(location.href, 'extra', 'width=700,height=500');
            document.body.append(button);
        }""")
        with original_page.expect_popup() as opened_popup:
            original_page.locator('#extra').click()
        popup = opened_popup.value
        popup.wait_for_load_state()
        popup_window = wait_for(lambda: next((w for w in leaves(tree()) if w.get('focused') and w['id'] != app_mode['id']), None))
        assert client.get('/api/status').json()['app'] == 'netflix'
        wait_for(lambda: touch_status()['controls'])
        time.sleep(1.6)
        if shutil.which('grim'):
            subprocess.check_call(['grim','-o','HEADLESS-1',str(root/'popup-close-control.png')],env=env)
        panel = touch_status()['panels'][0]
        with popup.expect_event('close'):
            close_button=panel['controls']['close']
            click_at(close_button['x']+close_button['width']/2, close_button['y']+close_button['height']/2)
        wait_for(lambda: client.get('/api/status').json()['app'] == 'netflix' and any(w['id'] == app_mode['id'] and w.get('focused') for w in leaves(tree())))
        assert not original_page.is_closed()
        assert all(w['id'] != popup_window['id'] for w in leaves(tree()))
        client.post('/api/apps/browser/activate', json={}).raise_for_status()
        # Test Wi-Fi entry on the real QML surface; nmcli is a private fixture.
        subprocess.check_call([str(bin_dir/'qs'),'--path',str(ui),'ipc','call','--','touch','wifi'],env=env,stdout=subprocess.DEVNULL)
        time.sleep(1)
        subprocess.check_call(['grim','-o','HEADLESS-1',str(root/'wifi-native.png')],env=env)
        click_at(1430,313)
        time.sleep(.3)
        subprocess.check_call(['grim','-o','HEADLESS-1',str(root/'wifi-selected.png')],env=env)
        click_at(1450,516)
        wait_for(lambda: touch_status()['open'])
        subprocess.check_call([str(bin_dir/'wtype'),'cafepass123'],env=env)
        subprocess.check_call(['grim','-o','HEADLESS-1',str(root/'wifi-password.png')],env=env)
        subprocess.check_call([str(bin_dir/'qs'),'--path',str(ui),'ipc','call','--','touch','hide'],env=env,stdout=subprocess.DEVNULL)
        time.sleep(.2)
        click_at(1500,582)
        time.sleep(1)
        subprocess.check_call(['grim','-o','HEADLESS-1',str(root/'wifi-result.png')],env=env)
        wait_for(wifi_marker.exists)
        secret=json.loads(wifi_marker.read_text())
        assert secret['private']
        wait_for(lambda:not Path(secret['file']).exists())
        click_at(1882,138)
        wait_for(lambda:not touch_status()['options'])
        destination = "https://example.com/?q=orgm%20home#prueba"
        response = client.post("/api/browser/open-url", json={"url": destination})
        assert response.status_code == 200, response.text
        try:
            wait_for(
                lambda: (
                    page.wait_for_timeout(50),
                    any(p.url == destination for p in browser.contexts[0].pages),
                )[1]
            )
        except AssertionError:
            print(
                {
                    "actual_url": page.url,
                    "tabs": [p.url for p in browser.contexts[0].pages],
                }
            )
            raise
        assert (
            len([w for w in leaves(tree()) if w.get("app_id") == "orgm-home-browser"])
            == 1
        )
        # Home keeps the browser alive; a new agent rediscovers and reuses it.
        response = client.post("/api/remote/home", json={})
        assert response.status_code == 200, response.text
        assert client.get("/api/status").json()["app"] == "home"
        agent.terminate()
        agent.wait(timeout=5)
        agent = start([str(app_bin / "orgm-home-agent")], "agent-restarted")
        wait_for(lambda: (root / "agent.sock").exists())
        response = client.post("/api/apps/browser/activate", json={})
        assert response.status_code == 200, response.text
        after = [
            w["id"] for w in leaves(tree()) if w.get("app_id") == "orgm-home-browser"
        ]
        assert after == before, (before, after)
        response = client.post("/api/apps/netflix/activate", json={})
        assert response.status_code == 200, response.text
        assert next(w for w in leaves(tree()) if "orgm-home-netflix" in w.get("marks", []))["id"] == app_mode["id"]
        client.post("/api/apps/browser/activate", json={}).raise_for_status()
        web.terminate()
        web.wait(timeout=5)
        saved = {k: env.pop(k) for k in ("SWAYSOCK", "WAYLAND_DISPLAY")}
        web = start([str(app_bin / "orgm-home")], "api-restarted")
        env.update(saved)
        wait_for(api_ready)
        status = client.get("/api/status")
        assert status.status_code == 200 and status.json()["app"] == "browser", (
            status.text
        )
        client.post("/api/remote/home", json={}).raise_for_status()
        wait_for(lambda: client.get('/api/status').json().get('previews',{}).get('browser'))
        preview=client.get('/api/previews/browser')
        assert preview.status_code==200 and preview.content.startswith(b'\xff\xd8')
        # The real Home header/options must remain below the native controls.
        kiosk_port_file=home/'.local/share/orgm-home/chrome/home/DevToolsActivePort'
        kiosk_browser=playwright.chromium.connect_over_cdp('http://127.0.0.1:'+kiosk_port_file.read_text().splitlines()[0])
        kiosk_page=kiosk_browser.contexts[0].pages[0]
        kiosk_page.wait_for_selector('.is-kiosk .masthead')
        native=touch_status()['panels'][0]['controls']
        assert kiosk_page.locator('.masthead').bounding_box()['y'] >= native['y']+native['height']
        # Closing a background source from the real dashboard must never
        # activate it first or affect the independently running browser.
        kiosk_page.locator('[data-close-app="netflix"]').click()
        wait_for(lambda: 'netflix' not in client.get('/api/status').json()['open'])
        assert client.get('/api/status').json()['app'] == 'home'
        assert not any(w['id'] == app_mode['id'] for w in leaves(tree()))
        assert any(w['id'] in before for w in leaves(tree()))
        client.close()
        browser.close()
    print(
        json.dumps(
            {
                "result": "PASS",
                "evidence": str(root),
                "checks": [
                    "real Chrome app_id",
                    "kiosk",
                    "HTTP to Unix socket to wtype",
                    "Home preserves windows",
                    "agent restart reuses window",
                    "API restart retains session",
                    "collapsed arrow restores controls",
                    "native X closes popup and retains original webapp",
                    "private Wi-Fi credential entry with real QML keyboard focus",
                    "authenticated per-window preview while Home retains focus",
                    "dashboard X closes a background app without changing Home or other sources",
                ],
            }
        )
    )
finally:
    if pointer:
        pointer.close()
    # The compositor is private; exiting it closes only the fixture windows.
    if env.get("SWAYSOCK"):
        with contextlib.suppress(Exception):
            subprocess.run(
                [str(bin_dir / "swaymsg"), "exit"],
                env=env,
                capture_output=True,
                timeout=3,
            )
    for process in reversed(processes):
        if process.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
    # Agent-created Chrome children have their own groups. Match only this temp HOME.
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        with contextlib.suppress(OSError, ValueError, ProcessLookupError):
            args = (entry / "cmdline").read_bytes().split(b"\0")
            if any(arg.startswith(f"--user-data-dir={home}/".encode()) for arg in args):
                os.kill(int(entry.name), signal.SIGTERM)
    for process in processes:
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)
    for log in logs:
        log.close()
