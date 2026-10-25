"""Private per-window screenshots; capturing never changes compositor focus."""
import hashlib
import os
from pathlib import Path
import tempfile


def directory():
    return Path(os.getenv("ORGM_PREVIEW_DIR", str(Path(os.getenv("XDG_STATE_HOME", str(Path.home()/'.local/state'))) / 'orgm-home/previews')))


def versions(ids):
    result = {}
    for app_id in ids:
        try:
            result[app_id] = (directory()/f'{app_id}.jpg').stat().st_mtime_ns
        except OSError:
            pass
    return result


async def capture(app_id, identifier, run):
    if not isinstance(identifier, str) or not identifier:
        return
    target = directory()
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    final = target / f'{app_id}.jpg'
    with tempfile.NamedTemporaryFile(dir=target, suffix='.jpg', delete=False) as file:
        temporary = Path(file.name)
    try:
        await run('grim', '-T', identifier, '-s', '0.4', '-t', 'jpeg', '-q', '76', str(temporary), timeout=6, check=False)
        data = temporary.read_bytes()
        if not data.startswith(b'\xff\xd8'):
            return
        if final.exists() and hashlib.sha256(final.read_bytes()).digest() == hashlib.sha256(data).digest():
            return
        temporary.replace(final)
    finally:
        temporary.unlink(missing_ok=True)
