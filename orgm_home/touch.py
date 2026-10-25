"""Local touch UI and a UID-authenticated, fixed-action session client."""

import asyncio
import json
import os
from pathlib import Path
import sys

from .config import Settings
from .protocol import AgentClient, ControlError


def main():
    os.environ["ORGM_ASSET_DIR"] = str(Path(__file__).parent / "static")
    ui = Path(__file__).parent / "touch/shell.qml"
    os.execvp("qs", ["qs", "--no-duplicate", "--path", str(ui)])


def control():
    action = sys.argv[1] if len(sys.argv) >= 2 else "status"
    actions = {
        "status": ("status", {}),
        "home": ("home", {}),
        "rotate": ("rotate", {}),
        "preferences": ("preferences", {}),
        "background": ("background", {"id": sys.argv[2] if len(sys.argv) == 3 else ""}),
        "restart-launcher": ("restart-launcher", {}),
        "reboot": ("reboot", {}),
        "close": ("close", {}),
        "back": ("key", {"key": "back"}),
        "play": ("key", {"key": "play"}),
        "stop": ("key", {"key": "stop"}),
        "next": ("key", {"key": "next"}),
        "previous": ("key", {"key": "previous"}),
        "mute": ("mute", {}),
        "volume-up": ("volume", {"delta": 5}),
        "volume-down": ("volume", {"delta": -5}),
    }
    if action not in actions:
        raise SystemExit("Unsupported local touch action")
    try:
        verb, data = actions[action]
        result = asyncio.run(
            AgentClient(Settings.from_env().agent_socket).call(verb, **data)
        )
        print(json.dumps({"ok": True, "data": result}))
    except ControlError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        raise SystemExit(1)
