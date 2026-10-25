"""Immutable configuration; HTTP clients never supply executable commands."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class App:
    id: str
    type: str
    name: str
    workspace: str
    control: str = "keyboard"
    appId: str = ""
    url: str = ""
    match: str = ""
    player: str = ""

    def __post_init__(self):
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,31}", self.id):
            raise ValueError("Invalid catalog ID")
        if self.type not in {"internal", "chrome", "flatpak", "mpv"}:
            raise ValueError("Invalid catalog type")
        if not re.fullmatch(r"[1-9][0-9]?", self.workspace):
            raise ValueError("Invalid workspace")
        if self.type == "flatpak" and not re.fullmatch(r"[A-Za-z0-9_.-]+", self.appId):
            raise ValueError("Invalid Flatpak ID")

    def public(self):
        return {"id": self.id, "name": self.name, "control": self.control}


def load_catalog(path: Path) -> dict[str, App]:
    apps = [App(**row) for row in json.loads(path.read_text())["apps"]]
    result = {app.id: app for app in apps}
    if len(result) != len(apps) or "home" not in result:
        raise ValueError("Catalog must contain unique IDs and home")
    if len({app.workspace for app in apps}) != len(apps):
        raise ValueError("Applications need separate workspaces")
    return result


@dataclass(frozen=True)
class Settings:
    catalog: Path
    agent_socket: Path
    token_file: Path
    origins: tuple[str, ...]
    public_host: str = "home.or-gm.com"
    access_team: str = ""
    access_aud: str = ""
    access_emails: tuple[str, ...] = ()
    cookie_age: int = 43200

    @classmethod
    def from_env(cls):
        return cls(
            catalog=Path(os.getenv("ORGM_CATALOG", "/etc/orgm-home/apps.json")),
            agent_socket=Path(os.getenv("ORGM_AGENT_SOCKET", "/run/orgm-home/agent.sock")),
            token_file=Path(os.getenv("ORGM_TOKEN_FILE", "/var/lib/orgm-home/control-token")),
            origins=tuple(x.strip().rstrip("/") for x in os.getenv(
                "ORGM_ORIGINS", "http://127.0.0.1:8765,http://localhost:8765,https://home.or-gm.com"
            ).split(",") if x.strip()),
            public_host=os.getenv("ORGM_PUBLIC_HOST", "home.or-gm.com"),
            access_team=os.getenv("ORGM_ACCESS_TEAM", "").rstrip("/"),
            access_aud=os.getenv("ORGM_ACCESS_AUD", ""),
            access_emails=tuple(x.strip().lower() for x in os.getenv("ORGM_ACCESS_EMAILS", "").split(",") if x.strip()),
        )
