"""Local, fixed NetworkManager actions. Credentials never enter argv or logs."""

import asyncio
from pathlib import Path
import tempfile
import uuid

from .protocol import ControlError


def fields(line):
    result, value, escaped = [], [], False
    for char in line:
        if escaped:
            value.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            result.append("".join(value))
            value = []
        else:
            value.append(char)
    result.append("".join(value))
    return result


class Wifi:
    def __init__(self, run, runtime):
        self.run = run
        self.runtime = Path(runtime)
        self.lock = asyncio.Lock()

    async def nm(self, *args, timeout=8):
        return await self.run("env", "LC_ALL=C", "nmcli", "--colors", "no", *args, timeout=timeout)

    async def device(self):
        raw = await self.nm("-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status")
        for line in raw.splitlines():
            row = fields(line)
            if len(row) == 4 and row[1] == "wifi":
                return row
        raise ControlError("No se encontró el adaptador Wi-Fi", 409)

    async def status(self, rescan=False):
        device, _, state, connection = await self.device()
        raw = await self.nm("-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list", "ifname", device, "--rescan", "yes" if rescan else "no", timeout=15)
        networks = {}
        for line in raw.splitlines():
            row = fields(line)
            if len(row) != 4 or not row[1] or not row[2].isdigit():
                continue
            used, ssid, signal, security = row
            item = {"ssid": ssid, "signal": int(signal), "secured": security not in {"", "--"}, "security": security, "connected": used == "*"}
            old = networks.get(ssid)
            if old is None or (item["connected"], item["signal"]) > (old["connected"], old["signal"]):
                networks[ssid] = item
        return {"connected": state == "connected", "connection": connection if state == "connected" else "", "networks": sorted(networks.values(), key=lambda n: (not n["connected"], -n["signal"], n["ssid"]))[:40]}

    async def connect(self, ssid, password=""):
        if not isinstance(ssid, str) or not 1 <= len(ssid.encode()) <= 32 or any(ord(c) < 32 for c in ssid):
            raise ControlError("Selecciona una red válida", 422)
        if not isinstance(password, str) or len(password) > 64 or any(ord(c) < 32 for c in password):
            raise ControlError("La contraseña no es válida", 422)
        async with self.lock:
            device = (await self.device())[0]
            await self.nm("radio", "wifi", "on")
            try:
                if not password:
                    available = (await self.status())["networks"]
                    network = next((n for n in available if n["ssid"] == ssid), None)
                    if network and not network["secured"]:
                        connection = str(uuid.uuid4())
                        await self.nm("connection", "add", "type", "wifi", "ifname", device, "con-name", f"ORGM {ssid}", "connection.uuid", connection, "connection.permissions", "user:media", "connection.autoconnect", "no", "ssid", ssid)
                        try:
                            await self.nm("--wait", "22", "connection", "up", "uuid", connection, "ifname", device, timeout=26)
                            await self.nm("connection", "modify", "uuid", connection, "connection.autoconnect", "yes")
                        except BaseException:
                            await self.nm("connection", "delete", "uuid", connection)
                            raise
                    else:
                        await self.nm("--wait", "22", "device", "wifi", "connect", ssid, "ifname", device, timeout=26)
                else:
                    available = (await self.status())["networks"]
                    network = next((n for n in available if n["ssid"] == ssid), None)
                    if network is None:
                        raise ControlError("Busca las redes y vuelve a seleccionar la tuya", 409)
                    if "802.1X" in network["security"]:
                        raise ControlError("Esta red necesita configuración de empresa", 409)
                    if len(password) < 8:
                        raise ControlError("La contraseña debe tener al menos 8 caracteres", 422)
                    connection = str(uuid.uuid4())
                    security = "sae" if "WPA3" in network["security"] and "WPA2" not in network["security"] else "wpa-psk"
                    await self.nm("connection", "add", "type", "wifi", "ifname", device, "con-name", f"ORGM {ssid}", "connection.uuid", connection, "connection.permissions", "user:media", "connection.autoconnect", "no", "ssid", ssid, "wifi-sec.key-mgmt", security)
                    self.runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
                    try:
                        with tempfile.NamedTemporaryFile(mode="w+", dir=self.runtime, prefix="wifi-", encoding="utf-8") as secret:
                            secret.write(f"802-11-wireless-security.psk:{password}\n")
                            secret.flush()
                            await self.nm("--wait", "22", "connection", "up", "uuid", connection, "ifname", device, "passwd-file", secret.name, timeout=26)
                        await self.nm("connection", "modify", "uuid", connection, "connection.autoconnect", "yes")
                    except BaseException:
                        await self.nm("connection", "delete", "uuid", connection)
                        raise
            except ControlError as exc:
                if exc.status != 503:
                    raise
                raise ControlError("No se pudo conectar. Revisa la contraseña o pulsa Buscar redes.", 409) from exc
            return await self.status()

    async def reconnect(self):
        async with self.lock:
            device = (await self.device())[0]
            await self.nm("radio", "wifi", "on")
            await self.nm("--wait", "22", "device", "connect", device, timeout=26)
            return await self.status()
