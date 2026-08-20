"""Servicio de pantalla remota: se queda encendido, pase lo que pase.

Antes, la pantalla remota nacía y moría con cada corrida del monitor. Eso tenía
un defecto grave de uso: la liga empezaba a morirse desde que se creaba, no
desde que alguien la veía. Si el gestor tardaba veinte minutos en llegar a su
teléfono, se encontraba con una liga muerta y con razón pensaba que el sistema
no servía.

Aquí la pantalla es un servicio aparte que vive por su cuenta:

    - Se levanta una vez y se queda encendida.
    - Escribe su liga en `logs/pantalla.url` para que cualquiera la consulte.
    - Las corridas del monitor se **cuelgan** de ella en vez de crear la suya.

Así la liga sirve siempre que el servicio esté arriba, y una corrida que
termina —o que se cae— ya no se lleva la pantalla por delante.

    python -m monitor.pantalla            (arranca y se queda)
    python -m monitor.pantalla --url      (sólo dice cuál es la liga actual)
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal
import sys
from pathlib import Path

from .handoff import Handoff, HandoffError

ARCHIVO_URL = Path("logs/pantalla.url")


def url_actual() -> str:
    """Liga que dejó escrita el servicio, o cadena vacía si no hay."""
    with contextlib.suppress(Exception):
        return ARCHIVO_URL.read_text(encoding="utf-8").strip()
    return ""


async def servir() -> int:
    pantalla = Handoff()
    faltan = pantalla.disponible()
    if faltan:
        print(f"Faltan componentes: {', '.join(faltan)}", flush=True)
        return 1

    try:
        url = await pantalla.start()
    except HandoffError as exc:
        print(f"No se pudo levantar la pantalla: {exc}", flush=True)
        return 1

    ARCHIVO_URL.parent.mkdir(parents=True, exist_ok=True)
    ARCHIVO_URL.write_text(url, encoding="utf-8")
    print(f"Pantalla remota lista.\nLiga: {url}", flush=True)
    print("Se queda encendida hasta que se detenga el servicio.", flush=True)

    parar = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, parar.set)

    try:
        await parar.wait()
    finally:
        print("Bajando la pantalla remota...", flush=True)
        await pantalla.stop()
        with contextlib.suppress(Exception):
            ARCHIVO_URL.unlink()
    return 0


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Pantalla remota persistente")
    ap.add_argument("--url", action="store_true", help="sólo imprimir la liga actual")
    args = ap.parse_args()

    if args.url:
        url = url_actual()
        print(url if url else "(no hay pantalla encendida)")
        raise SystemExit(0 if url else 1)

    raise SystemExit(asyncio.run(servir()))


if __name__ == "__main__":
    main()
