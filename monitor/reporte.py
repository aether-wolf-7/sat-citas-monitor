"""Qué ha estado haciendo el sistema, en español y sin leer bitácoras.

    python -m monitor.reporte             (resumen de lo último)
    python -m monitor.reporte --todo      (más historial)
    python -m monitor.reporte --pantalla  (sólo la liga de la pantalla remota)

Está pensado para que el cliente pueda revisar por su cuenta sin pedirle nada
a nadie: qué se revisó, qué se encontró, qué avisos salieron y a quién.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from .config import load_config
from .pantalla import url_actual
from .storage import (
    ALERT_APPOINTMENT, ALERT_HEARTBEAT, ALERT_SESSION,
    STATE_CAPTCHA_OR_EXPIRED, STATE_ERROR, STATE_SESSION_OK,
)

# Cómo se lee cada estado en palabras normales.
ESTADOS = {
    STATE_SESSION_OK: "sesión viva, sí se alcanzó a mirar",
    STATE_CAPTCHA_OR_EXPIRED: "el portal pidió captcha",
    "IDENTITY_SCREEN": "nadie abrió la sesión",
    "SESSION_DEAD": "la sesión se cayó",
    STATE_ERROR: "hubo un error",
    "UNKNOWN": "pantalla desconocida",
}

TIPOS = {
    ALERT_APPOINTMENT: "AVISO DE CITA",
    ALERT_SESSION: "pedir que abran la sesión",
    ALERT_HEARTBEAT: "aviso de que no se pudo revisar",
}


def _disponibilidad(valor) -> str:
    """Tres estados, y la diferencia importa.

    `None` no es "no hay citas": es "no se pudo saber". Confundirlos es
    justo el error que este proyecto existe para evitar.
    """
    if valor is None:
        return "no se pudo determinar"
    return "HABÍA LUGAR" if valor else "sin lugar"


def resumen(conn: sqlite3.Connection, limite: int) -> None:
    print("=" * 66)
    print("  QUÉ SE REVISÓ")
    print("=" * 66)
    filas = list(conn.execute(
        "SELECT * FROM checks ORDER BY id DESC LIMIT ?", (limite,)))
    if not filas:
        print("  Todavía no hay ningún registro.")
    for r in filas:
        estado = ESTADOS.get(r["state"], r["state"])
        print(f"\n  {r['ts']}  ({r['zone']})")
        print(f"     oficina : {r['office']}")
        if r["tramite"]:
            print(f"     trámite : {r['tramite']}")
        print(f"     estado  : {estado}")
        print(f"     citas   : {_disponibilidad(r['availability'])}")
        if r["detail"]:
            print(f"     detalle : {r['detail'][:150]}")

    print("\n" + "=" * 66)
    print("  AVISOS QUE SALIERON")
    print("=" * 66)
    filas = list(conn.execute(
        "SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limite,)))
    if not filas:
        print("  Todavía no se ha mandado ningún aviso.")
    for r in filas:
        tipo = TIPOS.get(r["kind"], r["kind"])
        estado = "entregado" if r["ok"] else f"FALLÓ ({r['detail'] or 'sin detalle'})"
        destino = r["channel"]
        print(f"  {r['ts']}  {tipo:32} -> {destino:26} {estado}")


def conteos(conn: sqlite3.Connection) -> None:
    print("\n" + "=" * 66)
    print("  EN TOTAL")
    print("=" * 66)
    total = conn.execute("SELECT COUNT(*) c FROM checks").fetchone()["c"]
    ok = conn.execute("SELECT COUNT(*) c FROM checks WHERE state=?",
                      (STATE_SESSION_OK,)).fetchone()["c"]
    con_lugar = conn.execute(
        "SELECT COUNT(*) c FROM checks WHERE availability=1").fetchone()["c"]
    sin_saber = conn.execute(
        "SELECT COUNT(*) c FROM checks WHERE availability IS NULL").fetchone()["c"]
    avisos = conn.execute("SELECT COUNT(*) c FROM alerts WHERE ok=1").fetchone()["c"]
    fallidos = conn.execute("SELECT COUNT(*) c FROM alerts WHERE ok=0").fetchone()["c"]
    print(f"  revisiones registradas : {total}")
    print(f"  con la sesión viva     : {ok}")
    print(f"  veces que hubo lugar   : {con_lugar}")
    print(f"  no se pudo determinar  : {sin_saber}")
    print(f"  avisos entregados      : {avisos}")
    if fallidos:
        print(f"  avisos que fallaron    : {fallidos}")


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Reporte del monitor de citas SAT")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--todo", action="store_true", help="más historial")
    ap.add_argument("--pantalla", action="store_true", help="sólo la liga remota")
    args = ap.parse_args()

    liga = url_actual()
    if args.pantalla:
        print(liga if liga else "No hay pantalla remota encendida.")
        raise SystemExit(0 if liga else 1)

    cfg = load_config(args.config)
    print()
    print("PANTALLA REMOTA")
    print(f"  {liga}" if liga else "  apagada (arranca el servicio satmon-pantalla)")
    print()

    ruta = Path(cfg.storage.sqlite_path)
    if not ruta.exists():
        print(f"Todavía no existe la base de datos ({ruta}).")
        raise SystemExit(1)
    conn = sqlite3.connect(ruta)
    conn.row_factory = sqlite3.Row
    try:
        resumen(conn, 25 if args.todo else 6)
        conteos(conn)
    finally:
        conn.close()
    print()


if __name__ == "__main__":
    main()
