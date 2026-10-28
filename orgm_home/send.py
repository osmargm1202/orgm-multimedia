"""Send a selected YouTube URL using the user's existing browser authorization."""

import argparse
import os
import subprocess
import time
from urllib.parse import urlencode

from .protocol import ControlError
from .youtube import canonical_url


def notify(message):
    try:
        subprocess.run(
            ["notify-send", "--app-name=ORGM Home", "YouTube en Jarq", message],
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def selection():
    if os.environ.get("WAYLAND_DISPLAY"):
        args = ["wl-paste", "--primary", "--no-newline"]
    elif os.environ.get("DISPLAY"):
        args = ["xclip", "-selection", "primary", "-o"]
    else:
        raise ControlError(
            "No hay una sesión gráfica desde la que leer la selección.", 422
        )
    # Read only the selection. Never fall back to an old clipboard video.
    with subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    ) as process:
        try:
            import selectors

            raw = bytearray()
            deadline = time.monotonic() + 2
            with selectors.DefaultSelector() as ready:
                ready.register(process.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not ready.select(remaining):
                        raise ControlError(
                            "No se pudo leer el texto seleccionado.", 422
                        )
                    chunk = os.read(process.stdout.fileno(), 8193 - len(raw))
                    if not chunk:
                        break
                    raw.extend(chunk)
                    if len(raw) > 8192:
                        raise ControlError(
                            "La selección es demasiado larga para ser un enlace.", 422
                        )
            process.wait(timeout=2)
            if process.returncode:
                raise ControlError("Selecciona primero un enlace de YouTube.", 422)
            return raw.decode("utf-8")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


def main():
    parser = argparse.ArgumentParser(
        description="Enviar a Jarq el enlace de YouTube seleccionado"
    )
    parser.add_argument("--url", help="Usar este enlace en lugar de la selección")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validar y mostrar el destino sin abrirlo",
    )
    args = parser.parse_args()
    try:
        video = canonical_url(args.url if args.url is not None else selection())
        target = "https://home.or-gm.com/youtube/link/?" + urlencode({"key": video})
        if args.dry_run:
            print(target)
            return
        subprocess.run(
            ["xdg-open", target],
            check=True,
            timeout=15,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (ControlError, OSError, UnicodeError, subprocess.SubprocessError) as error:
        message = (
            str(error)
            if isinstance(error, ControlError)
            else "No se pudo enviar el enlace. Comprueba la selección y el navegador."
        )
        notify(message)
        raise SystemExit(2)
