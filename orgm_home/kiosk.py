"""Bounded HTTP readiness check and kiosk launch; systemd handles retries."""

import json
import os
from pathlib import Path
import time
from urllib.error import URLError
from urllib.request import urlopen


def main():
    url = "http://127.0.0.1:8765"
    for _ in range(30):
        try:
            with urlopen(f"{url}/api/health", timeout=1) as response:
                if json.load(response).get("ok"):
                    break
        except (URLError, TimeoutError, ValueError, OSError):
            pass
        time.sleep(1)
    else:
        raise SystemExit("ORGM Home API did not become ready")
    token = (
        Path(os.getenv("ORGM_TOKEN_FILE", "/var/lib/orgm-home/control-token"))
        .read_text()
        .strip()
    )
    profile = Path.home() / ".local/share/orgm-home/chrome/home"
    profile.mkdir(parents=True, exist_ok=True)
    os.execvp(
        "google-chrome-stable",
        [
            "google-chrome-stable",
            "--ozone-platform=wayland",
            "--no-first-run",
            "--no-default-browser-check",
            "--password-store=basic",
            "--blink-settings=hideScrollbars=true",
            "--class=orgm-home-home",
            f"--user-data-dir={profile}",
            "--kiosk",
            f"{url}/#pair={token}",
        ],
    )
