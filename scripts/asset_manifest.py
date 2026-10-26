"""Version public assets and their CSS dependencies; run before committing assets."""

import hashlib
import json
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1] / 'orgm_home/static'
for css in root.glob('*.css'):
    def version(match):
        path = root / match[1]
        if not path.is_file():
            raise ValueError(f'Missing CSS asset: {path}')
        return f"url('/static/{match[1]}?v={hashlib.sha256(path.read_bytes()).hexdigest()[:12]}')"
    text = re.sub(r"url\('/static/([^?'\)]+)(?:\?v=[a-f0-9]+)?'\)", version, css.read_text())
    css.write_text(text)
files = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()[:12]
         for path in sorted(root.rglob('*')) if path.is_file() and path.name != 'manifest.json'}
version = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()[:12]
(root / 'manifest.json').write_text(json.dumps({'version': version, 'files': files}, indent=2) + '\n')
print(f'{len(files)} assets, version {version}')
