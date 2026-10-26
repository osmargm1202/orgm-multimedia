"""Bounded CPU pressure relief for background media sources."""

from dataclasses import dataclass
import os
from pathlib import Path
import signal
import time


class CpuMeter:
    def __init__(self):
        self.previous = None

    def sample(self):
        row = Path('/proc/stat').read_text().splitlines()[0].split()
        values = [int(v) for v in row[1:9]]
        current = (sum(values), values[3] + values[4])
        previous, self.previous = self.previous, current
        if previous is None or current[0] <= previous[0]:
            return None
        return max(0, min(100, 100 * (1 - (current[1] - previous[1]) / (current[0] - previous[0]))))


class PressureGuard:
    threshold = 80
    duration = 60
    grace = 30
    cooldown = 60

    def __init__(self):
        self.active = None
        self.background = {}
        self.high_since = None
        self.next_close = 0
        self.cpu = None
        self.notice = None

    def select(self, app_id, now=None):
        now = time.monotonic() if now is None else now
        if self.active and self.active != app_id:
            self.background[self.active] = now
        self.background.pop(app_id, None)
        self.active = app_id

    def observe(self, cpu, active, opened, eligible, now=None):
        now = time.monotonic() if now is None else now
        self.cpu = cpu
        self.select(active, now)
        self.background = {app: stamp for app, stamp in self.background.items() if app in opened}
        for app in opened:
            if app != active:
                self.background.setdefault(app, now)
        if cpu is None or cpu < self.threshold or not active:
            self.high_since = None
            return None
        if self.high_since is None:
            self.high_since = now
        if now - self.high_since < self.duration or now < self.next_close:
            return None
        candidates = [app for app in self.background if app in eligible and app != active]
        if not candidates:
            return None
        # The most recently left source is intentional: don't close the active
        # player or unrelated older sessions when the user has just switched.
        target = max(candidates, key=self.background.get)
        return target if now - self.background[target] >= self.grace else None

    def closed(self, app, name, now=None):
        now = time.monotonic() if now is None else now
        self.next_close = now + self.cooldown
        self.high_since = None
        self.background.pop(app, None)
        self.notice = {'id': time.time_ns(), 'app': app, 'message': f'Se cerró {name} en segundo plano para aliviar la CPU.'}


@dataclass(frozen=True)
class Process:
    parent: int
    started: int


def owned_process(pid):
    try:
        directory = Path(f'/proc/{int(pid)}')
        if directory.stat().st_uid != os.getuid():
            return None
        stat = (directory / 'stat').read_text()
        fields = stat[stat.rindex(')') + 2:].split()
        return Process(int(fields[1]), int(fields[19]))
    except (OSError, ValueError, IndexError):
        return None


def terminate_family(roots):
    """Only the same UID's recorded descendants; PID reuse never gets a signal."""
    processes = {int(p.name): proc for p in Path('/proc').iterdir() if p.name.isdigit() and (proc := owned_process(p.name))}
    selected = set(roots).intersection(processes)
    while True:
        expanded = selected | {pid for pid, proc in processes.items() if proc.parent in selected}
        if expanded == selected:
            break
        selected = expanded
    if not selected:
        return False
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid in sorted(selected, reverse=True):
            if owned_process(pid) == processes[pid]:
                try:
                    os.kill(pid, sig)
                except ProcessLookupError:
                    pass
        if sig == signal.SIGTERM:
            time.sleep(.4)
    return True
