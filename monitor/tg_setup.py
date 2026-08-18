"""Alta de destinatarios de Telegram.

Un bot de Telegram **no puede escribirle a un número de teléfono**. Sólo puede
responderle a quien ya le haya escrito primero. Por eso cada gestor tiene que
abrir el bot una vez y darle "Start"; a partir de ahí existe un `chat_id`, que
es la dirección real a la que se mandan las alertas.

Esta herramienta hace ese trámite:

    python -m monitor.tg_setup --token 123456:AAF...            (ver quién dio Start)
    python -m monitor.tg_setup --token 123456:AAF... --guardar  (escribirlo en config.json)
    python -m monitor.tg_setup --probar                          (mandar una alerta de prueba)

Sirve ahora para la demo y después para dar de alta a los demás gestores, así
que se queda como parte de la entrega.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

API = "https://api.telegram.org/bot{token}/{metodo}"


def _llamar(token: str, metodo: str, **params) -> dict:
    url = API.format(token=token, metodo=metodo)
    try:
        r = httpx.get(url, params=params, timeout=25)
    except Exception as exc:
        raise SystemExit(f"No se pudo hablar con Telegram: {type(exc).__name__}: {exc}")
    if r.status_code in (401, 404):
        raise SystemExit(
            "Telegram no reconoce ese token.\n"
            "  - Cópialo completo, incluyendo los dos puntos del centro.\n"
            "  - Se ve así: 1234567890:AAF-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\n"
            "  - Si lo perdiste, escríbele /mybots a @BotFather y ahí lo vuelves a ver."
        )
    try:
        data = r.json()
    except Exception:
        raise SystemExit(f"Telegram respondió algo raro: {r.text[:200]}")
    if not data.get("ok"):
        raise SystemExit(f"Telegram respondió con error: {data}")
    return data["result"]


def quien_dio_start(token: str) -> list[dict]:
    """Chats que ya le escribieron al bot, sin repetir."""
    updates = _llamar(token, "getUpdates", timeout=0)
    vistos: dict[str, dict] = {}
    for u in updates:
        msg = u.get("message") or u.get("edited_message") or {}
        chat = msg.get("chat") or {}
        cid = str(chat.get("id", ""))
        if not cid or cid in vistos:
            continue
        nombre = " ".join(
            x for x in (chat.get("first_name"), chat.get("last_name")) if x
        ) or chat.get("title") or "(sin nombre)"
        vistos[cid] = {
            "chat_id": cid,
            "nombre": nombre,
            "usuario": chat.get("username", ""),
            "tipo": chat.get("type", ""),
        }
    return list(vistos.values())


def guardar_en_config(ruta: str, token: str, chat_ids: list[str]) -> None:
    p = Path(ruta)
    if not p.exists():
        raise SystemExit(f"No existe {p}. Copia config.example.json a config.json primero.")
    raw = json.loads(p.read_text(encoding="utf-8"))
    tg = raw.setdefault("alerts", {}).setdefault("telegram", {})
    tg["enabled"] = True
    tg["bot_token"] = token
    # chat_ids = quien recibe todo. Es lo que pidió el cliente: los tres ven todo.
    existentes = [str(x) for x in tg.get("chat_ids", [])]
    for cid in chat_ids:
        if cid not in existentes:
            existentes.append(cid)
    tg["chat_ids"] = existentes
    p.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nGuardado en {p}: token + {len(existentes)} destinatario(s).")


async def mandar_prueba(ruta: str) -> int:
    """Manda una alerta real, con captura si hay alguna a la mano."""
    from .config import load_config
    from . import alerts, storage

    cfg = load_config(ruta)
    if not cfg.telegram.enabled or not cfg.telegram.bot_token:
        raise SystemExit("Telegram no está configurado todavía. Corre primero con --guardar.")

    capturas = sorted(Path(cfg.storage.screenshots_dir).glob("*.png")) if \
        Path(cfg.storage.screenshots_dir).exists() else []
    captura = str(capturas[-1]) if capturas else None

    alerta = alerts.alerta_de_cita(
        zona="Cancún",
        oficina="Módulo de Servicios Tributarios Cancún (MST Cancún)",
        tramite="e.firma",
        dias=["18", "19", "21"],
        horarios=["09:00", "09:30", "10:00"],
        captura=captura,
    )
    alerta = alerts.Alerta(
        tipo=alerta.tipo, zona=alerta.zona, oficina=alerta.oficina,
        tramite=alerta.tramite, captura=alerta.captura,
        texto="[PRUEBA — datos de ejemplo, no es una cita real]\n\n" + alerta.texto,
    )

    conn = storage.connect(cfg.storage.sqlite_path)
    try:
        resultados = await alerts.despachar(cfg, alerta, conn)
    finally:
        conn.close()

    if not resultados:
        print("No salió nada: no hay destinatarios configurados.")
        return 1
    for canal, ok, detalle in resultados:
        print(f"  {canal}: {'ENVIADO' if ok else 'FALLÓ — ' + detalle}")
    if captura:
        print(f"\nSe mandó con la captura {captura}")
    else:
        print("\n(Sin captura: todavía no hay ninguna en la carpeta de capturas)")
    return 0 if all(ok for _, ok, _ in resultados) else 1


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser(description="Dar de alta destinatarios de Telegram")
    ap.add_argument("--token", default="", help="el token que da @BotFather")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--guardar", action="store_true", help="escribir token y chats en la config")
    ap.add_argument("--probar", action="store_true", help="mandar una alerta de prueba")
    args = ap.parse_args()

    if args.probar and not args.token:
        raise SystemExit(asyncio.run(mandar_prueba(args.config)))

    if not args.token:
        ap.error("hace falta --token (o usa --probar si ya está guardado)")

    info = _llamar(args.token, "getMe")
    print(f"Bot: {info.get('first_name')}  (@{info.get('username')})")

    chats = quien_dio_start(args.token)
    if not chats:
        print("\nTodavía nadie le ha escrito al bot.")
        print(f"Abre https://t.me/{info.get('username')} , dale START y manda un 'hola'.")
        print("Luego vuelve a correr esto.")
        raise SystemExit(1)

    print(f"\nYa le escribieron {len(chats)} persona(s):")
    for c in chats:
        usuario = f" @{c['usuario']}" if c["usuario"] else ""
        print(f"  chat_id={c['chat_id']:<15} {c['nombre']}{usuario}  [{c['tipo']}]")

    if args.guardar:
        guardar_en_config(args.config, args.token, [c["chat_id"] for c in chats])
        print("\nAhora prueba con:  python -m monitor.tg_setup --probar")
    else:
        print("\nSi se ve bien, vuelve a correrlo agregando --guardar")


if __name__ == "__main__":
    main()
