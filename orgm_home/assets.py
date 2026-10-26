"""Public-only asset URLs; application data and previews are never cached."""

import json
from pathlib import Path
import re

MANIFEST = json.loads((Path(__file__).parent / 'static/manifest.json').read_text())


def asset_url(path):
    return f'/static/{path}?v={MANIFEST["files"][path]}'


def cache_control(version):
    return 'public, max-age=31536000, immutable' if re.fullmatch('[a-f0-9]{12}', version or '') else 'public, max-age=3600, must-revalidate'
