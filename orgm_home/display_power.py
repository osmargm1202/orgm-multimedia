"""Session-scoped HDMI power preference shared by the agent and display watcher."""

import os
from pathlib import Path
import re

from .protocol import ControlError


def target_output():
    target = os.getenv('ORGM_DISPLAY_TARGET', 'HDMI-A-1')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', target) or target == os.getenv('ORGM_DISPLAY_SOURCE', 'eDP-1'):
        raise ControlError('Salida externa no válida', 409)
    return target


def off_marker():
    runtime = Path(os.getenv('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}'))
    return runtime / 'orgm-home-external-off'


def set_enabled(enabled):
    if enabled:
        off_marker().unlink(missing_ok=True)
    else:
        off_marker().touch(mode=0o600)


def power_status(outputs):
    output = next((o for o in outputs if o.get('name') == target_output()), None)
    connected = bool(output and (output.get('modes') or output.get('active')))
    return {'connected': connected, 'enabled': not off_marker().exists()}
