"""Fixed 1080p touch source and HDMI mirror, with hotplug recovery."""

import asyncio
import json
import logging
import os
import re

from .agent import command

LOG = logging.getLogger(__name__)


class DisplayManager:
    def __init__(self, source=None, target=None, mode=None):
        self.source = source or os.getenv("ORGM_DISPLAY_SOURCE", "eDP-1")
        self.target = target or os.getenv("ORGM_DISPLAY_TARGET", "HDMI-A-1")
        self.mode = mode or os.getenv("ORGM_DISPLAY_MODE", "1920x1080")
        if any(
            not re.fullmatch(r"[A-Za-z0-9_-]+", value)
            for value in (self.source, self.target)
        ) or not re.fullmatch(r"[0-9]+x[0-9]+", self.mode):
            raise ValueError("Invalid fixed display configuration")
        self.mirror = None
        self.connected = None

    async def stop_mirror(self):
        if self.mirror and self.mirror.returncode is None:
            self.mirror.terminate()
            try:
                await asyncio.wait_for(self.mirror.wait(), 3)
            except TimeoutError:
                self.mirror.kill()
                await self.mirror.wait()
        self.mirror = None

    async def update(self):
        outputs = json.loads(await command("swaymsg", "-r", "-t", "get_outputs"))
        source = next((o for o in outputs if o["name"] == self.source), None)
        target = next(
            (
                o
                for o in outputs
                if o["name"] == self.target and (o.get("modes") or o.get("active"))
            ),
            None,
        )
        if source is None:
            return  # Do not commandeer an unrelated output.
        changed = self.connected != bool(target)
        if changed or not source.get("active") or not source.get("power", True):
            await command(
                "swaymsg",
                f"output {self.source} enable mode {self.mode} scale 1 position 0 0 power on",
            )
            await command("swaymsg", f"input type:touch map_to_output {self.source}")
        if target:
            if changed or not target.get("active") or not target.get("power", True):
                width = int(self.mode.split("x")[0])
                await command(
                    "swaymsg",
                    f"output {self.target} enable mode {self.mode} scale 1 position {width} 0 power on",
                )
            if self.mirror is None or self.mirror.returncode is not None:
                await self.stop_mirror()
                self.mirror = await asyncio.create_subprocess_exec(
                    "wl-mirror",
                    "--fullscreen-output",
                    self.target,
                    "--no-show-cursor",
                    "--title",
                    "ORGM Home Mirror",
                    self.source,
                    stdout=asyncio.subprocess.DEVNULL,
                )
                # The Sway no_focus rule keeps the real application on the touch
                # output focused when the mirror maps or is restarted.
                await command("swaymsg", f"focus output {self.source}")
            self.connected = True
            await select_hdmi_audio()
        else:
            await self.stop_mirror()
        self.connected = bool(target)


async def select_hdmi_audio():
    cards = json.loads(await command("pactl", "-f", "json", "list", "cards"))
    for card in cards:
        candidates = [
            name
            for name, profile in card.get("profiles", {}).items()
            if "output:hdmi-stereo" in name
            and profile.get("available") in (True, "yes")
        ]
        if candidates and card.get("active_profile") not in candidates:
            await command(
                "pactl",
                "set-card-profile",
                str(card["index"]),
                sorted(candidates, key=lambda name: ("extra" in name, len(name)))[0],
            )
    graph = json.loads(await command("pw-dump"))
    for node in graph:
        props = node.get("info", {}).get("props", {})
        if (
            props.get("media.class") == "Audio/Sink"
            and "hdmi" in props.get("node.name", "").lower()
        ):
            await command("wpctl", "set-default", str(int(node["id"])))
            break


async def run():
    manager = DisplayManager()
    try:
        while True:
            try:
                await manager.update()
            except Exception:
                LOG.exception("Display/audio hotplug update failed; retrying")
            await asyncio.sleep(2)
    finally:
        await manager.stop_mirror()


def main():
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
