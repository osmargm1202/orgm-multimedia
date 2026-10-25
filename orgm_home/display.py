"""Follow HDMI hotplug and select its audio without suspending the appliance."""
import asyncio
import contextlib
import json
import logging
import re

from .agent import command

LOG = logging.getLogger(__name__)


async def update():
    outputs = json.loads(await command("swaymsg", "-r", "-t", "get_outputs"))
    hdmi = [o for o in outputs if o["name"].startswith("HDMI-") and o.get("modes")]
    internal = [o for o in outputs if o["name"].startswith(("eDP-", "LVDS-"))]
    for output in hdmi + internal:
        name = output["name"]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            continue
        enabled = output in hdmi or not hdmi
        if bool(output.get("active")) != enabled:
            await command("swaymsg", f"output {name} {'enable' if enabled else 'disable'}")
    if not hdmi:
        return
    # The analog card profile may otherwise prevent an HDMI sink from existing.
    cards = json.loads(await command("pactl", "-f", "json", "list", "cards"))
    for card in cards:
        profiles = card.get("profiles", {})
        candidates = [name for name, profile in profiles.items() if "output:hdmi-stereo" in name and profile.get("available") == "yes"]
        if candidates and card.get("active_profile") not in candidates:
            await command("pactl", "set-card-profile", str(card["index"]), sorted(candidates, key=lambda name: ("extra" in name, len(name)))[0])
    graph = json.loads(await command("pw-dump"))
    for node in graph:
        props = node.get("info", {}).get("props", {})
        if props.get("media.class") == "Audio/Sink" and "hdmi" in props.get("node.name", "").lower():
            await command("wpctl", "set-default", str(int(node["id"])))
            break


async def run():
    while True:
        try:
            await update()
        except Exception:
            LOG.exception("Display/audio hotplug update failed; retrying")
        await asyncio.sleep(5)


def main():
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
