"""Alertas: armado del mensaje y envío por Telegram.

Requisito literal del cliente: toda alerta tiene que decir **de qué SAT**
(Cancún o CDMX) se trata, **qué módulo**, **qué trámite**, y traer **captura**
y **liga directa**. Eso se arma aquí, en un solo lugar, para que todos los
canales manden exactamente el mismo contenido.

Telegram va primero porque es gratis y estable. WhatsApp (paso 11) y correo
(paso 10) se cuelgan de las mismas funciones de armado.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx

from . import storage
from .config import Config, Telegram

# El SAT trabaja en hora del centro de México (UTC-6).
HORA_CENTRO = timezone(timedelta(hours=-6))

LIGA_PORTAL = "https://citas.sat.gob.mx/"


@dataclass(frozen=True)
class Alerta:
    """Contenido de una alerta, independiente del canal por el que salga."""

    tipo: str            # storage.ALERT_* (session / appointment / heartbeat)
    zona: str            # "Cancún" o "CDMX" — lo que el cliente exige ver
    texto: str
    oficina: str | None = None
    tramite: str | None = None
    captura: str | None = None


def _sello() -> str:
    return datetime.now(HORA_CENTRO).strftime("%Y-%m-%d %H:%M") + " (hora del centro)"


def alerta_de_cita(
    *, zona: str, oficina: str, tramite: str,
    dias: list[str], horarios: list[str], captura: str | None = None,
    liga: str = LIGA_PORTAL,
) -> Alerta:
    """Alarma 2: hay disponibilidad. La agenda una persona, no el sistema."""
    lineas = [
        "HAY CITA DISPONIBLE",
        "",
        f"SAT: {zona}",
        f"Módulo: {oficina}",
        f"Trámite: {tramite}",
    ]
    if dias:
        lineas.append(f"Días: {', '.join(dias[:12])}")
    if horarios:
        lineas.append(f"Horarios: {', '.join(horarios[:8])}")
    lineas += [
        "",
        f"Agenda aquí: {liga}",
        f"Detectado: {_sello()}",
        "",
        "El agendado lo haces tú. El sistema solo avisa.",
    ]
    return Alerta(
        tipo=storage.ALERT_APPOINTMENT, zona=zona, oficina=oficina,
        tramite=tramite, captura=captura, texto="\n".join(lineas),
    )


def alerta_de_sesion(
    *, zona: str, motivo: str, liga_sesion: str | None = None,
    oficina: str | None = None, captura: str | None = None,
) -> Alerta:
    """Alarma 1: hay que abrir la sesión. El captcha lo resuelve una persona."""
    lineas = [
        "SE NECESITA ABRIR LA SESIÓN",
        "",
        f"SAT: {zona}",
    ]
    if oficina:
        lineas.append(f"Módulo: {oficina}")
    lineas.append(f"Motivo: {motivo}")
    if liga_sesion:
        lineas += ["", f"Abre la sesión aquí: {liga_sesion}"]
    lineas += [
        f"Momento: {_sello()}",
        "",
        "El captcha lo resuelves tú. El sistema no lo toca.",
    ]
    return Alerta(
        tipo=storage.ALERT_SESSION, zona=zona, oficina=oficina,
        captura=captura, texto="\n".join(lineas),
    )


def alerta_de_silencio(*, zona: str, minutos: int) -> Alerta:
    """Watchdog: llevamos demasiado tiempo sin una lectura válida.

    Existe porque el silencio nunca debe significar "no hay citas"; el silencio
    sólo puede significar "todo bien y vigilando", y para sostener eso hay que
    avisar cuando dejamos de ver.
    """
    texto = "\n".join([
        "AVISO: el sistema lleva rato sin poder leer el portal",
        "",
        f"SAT: {zona}",
        f"Sin lectura válida desde hace {minutos} minutos.",
        f"Momento: {_sello()}",
        "",
        "Esto NO quiere decir que no haya citas: quiere decir que no estamos viendo.",
    ])
    return Alerta(tipo=storage.ALERT_HEARTBEAT, zona=zona, texto=texto)


def destinos_telegram(cfg: Config, zona: str) -> tuple[str, ...]:
    """A qué chats va esta alerta, según la política de ruteo.

    `by_zone` reparte por zona —el gestor de Cancún ve lo de Cancún— y encima
    manda todo a quienes estén en `chat_ids`, que es el destinatario "de los
    dos" que pidió el cliente. `all` manda todo a todos.
    """
    return cfg.telegram.destinos(zona, cfg.routing)


async def enviar_telegram(
    tg: Telegram, alerta: Alerta, chat_id: str, *, timeout: float = 20.0
) -> tuple[bool, str]:
    """Manda la alerta a un chat. Si hay captura, va la foto con el texto."""
    base = f"https://api.telegram.org/bot{tg.bot_token}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            captura = Path(alerta.captura) if alerta.captura else None
            if captura and captura.exists():
                with captura.open("rb") as fh:
                    r = await client.post(
                        f"{base}/sendPhoto",
                        data={"chat_id": chat_id, "caption": alerta.texto[:1024]},
                        files={"photo": (captura.name, fh, "image/png")},
                    )
            else:
                r = await client.post(
                    f"{base}/sendMessage",
                    data={"chat_id": chat_id, "text": alerta.texto,
                          "disable_web_page_preview": "false"},
                )
        if r.status_code == 200 and r.json().get("ok"):
            return True, "enviado"
        return False, f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


async def despachar(
    cfg: Config, alerta: Alerta, conn: sqlite3.Connection | None = None
) -> list[tuple[str, bool, str]]:
    """Manda la alerta por los canales encendidos y deja constancia en SQLite.

    Devuelve una lista de (canal, ok, detalle). No lanza excepción si un canal
    falla: se registra y se sigue con los demás, porque perder una alerta por
    un canal caído es justo lo que no queremos.
    """
    resultados: list[tuple[str, bool, str]] = []

    if cfg.telegram.enabled:
        for chat_id in destinos_telegram(cfg, alerta.zona):
            ok, detalle = await enviar_telegram(cfg.telegram, alerta, chat_id)
            resultados.append((f"telegram:{chat_id}", ok, detalle))
            if conn is not None:
                storage.log_alert(
                    conn, kind=alerta.tipo, channel=f"telegram:{chat_id}", ok=ok,
                    zone=alerta.zona, office=alerta.oficina,
                    tramite=alerta.tramite, detail=detalle,
                )

    return resultados
