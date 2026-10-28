"""Recognize one YouTube video without fetching URLs or following redirects."""

import re
from urllib.parse import parse_qs, urlencode, urlsplit

from .protocol import ControlError

MESSAGE = (
    "Selecciona un enlace válido de un video de YouTube (watch, Shorts o youtu.be)."
)
HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}


def canonical_url(value):
    if not isinstance(value, str):
        raise ControlError(MESSAGE, 422)
    value = value.strip()
    if (
        not value
        or len(value) > 2048
        or "\\" in value
        or any(ord(char) < 33 or ord(char) == 127 for char in value)
    ):
        raise ControlError(MESSAGE, 422)
    try:
        parts = urlsplit(value)
        if (
            parts.scheme != "https"
            or parts.username
            or parts.password
            or parts.port not in {None, 443}
        ):
            raise ValueError
        host = (parts.hostname or "").lower()
        query = parse_qs(parts.query, keep_blank_values=True)
        path = parts.path.rstrip("/")
        if host in {"youtu.be", "www.youtu.be"}:
            identity = path.removeprefix("/")
        elif host in HOSTS and path == "/watch":
            videos = query.get("v", [])
            if len(videos) != 1:
                raise ValueError
            identity = videos[0]
        elif host in HOSTS and re.fullmatch(
            r"/(shorts|live|embed)/[A-Za-z0-9_-]{11}", path
        ):
            identity = path.rsplit("/", 1)[1]
        else:
            raise ValueError
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", identity):
            raise ValueError
        result = {"v": identity}
        starts = query.get("t", query.get("start", []))
        if len(starts) > 1:
            raise ValueError
        if starts:
            start = starts[0]
            match = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", start)
            if start.isascii() and start.isdigit():
                seconds = int(start)
            elif match and any(match.groups()):
                seconds = sum(
                    int(value or 0) * factor
                    for value, factor in zip(match.groups(), [3600, 60, 1])
                )
            else:
                raise ValueError
            if seconds > 359999:
                raise ValueError
            result["t"] = str(seconds)
        return "https://www.youtube.com/watch?" + urlencode(result)
    except (ValueError, UnicodeError) as exc:
        raise ControlError(MESSAGE, 422) from exc
