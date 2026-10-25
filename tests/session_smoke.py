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
config = root / "sway.conf"
config.write_text(
    "output * mode 1920x1080\noutput HEADLESS-1 position 0 0\noutput HEADLESS-2 position 1920 0\n"
    "output * bg #161b27 solid_color\ndefault_border none\nfocus_follows_mouse no\n"
    "workspace 1 output HEADLESS-1\nworkspace 7 output HEADLESS-1\nworkspace 99 output HEADLESS-2\n"
    'no_focus [app_id="at.yrlf.wl_mirror"]\n'
    'for_window [app_id="at.yrlf.wl_mirror"] move container to workspace number 99, fullscreen enable\n'
)
apps = json.loads((system / "etc/orgm-home/apps.json").read_text())
# The fixed test-only browser destination is a local input fixture.
for app in apps["apps"]:
    if app["id"] == "browser":
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
    touch_process = start([str(app_bin / "orgm-home-touch")], "touch")
    ui = next(
        (app_bin / "orgm-home-touch")
        .resolve()
        .parent.parent.glob("lib/python*/site-packages/orgm_home/touch/shell.qml"),
        None,
    )
    if os.getenv("ORGM_TEST_TOUCH_UI"):
        ui = Path(os.environ["ORGM_TEST_TOUCH_UI"])
    assert ui is not None, "Packaged touch QML not found"

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
            time.sleep(0.5)
            for output, name in [
                ("HEADLESS-1", "touch-source"),
                ("HEADLESS-2", "mirror-target"),
            ]:
                subprocess.check_call(
                    ["grim", "-o", output, str(root / (name + ".png"))], env=env
                )
            if shutil.which("magick"):
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
                assert match and float(match[1]) < 0.03, comparison.stderr

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
