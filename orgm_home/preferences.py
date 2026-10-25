"""Small validated preferences owned by the media session."""

import json
from pathlib import Path

BACKGROUNDS = {
    "costa": ("Costa nocturna", "home-night.png"),
    "bosque": ("Bosque", "home-bosque.png"),
    "dunas": ("Dunas", "home-dunas.png"),
    "orbita": ("Órbita", "home-orbita.png"),
    "aurora": ("Aurora", "home-aurora.png"),
}


def read_background(state: Path):
    try:
        value = json.loads((state / "preferences.json").read_text()).get("background")
        if value in BACKGROUNDS:
            return value
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return "costa"


def write_background(state: Path, value):
    if value not in BACKGROUNDS:
        raise ValueError("Unknown background")
    path = state / "preferences.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"background": value}))
    temporary.chmod(0o600)
    temporary.replace(path)


def gallery():
    return [
        {"id": ident, "name": name, "image": "/static/" + image}
        for ident, (name, image) in BACKGROUNDS.items()
    ]
