"""Carga y validación de la configuración (config.json).

`load_config()` valida estructura y tipos. La validación de credenciales de
los canales activos (tokens, destinatarios) se hace aparte con
`validate_runtime()`, para que el ejemplo y las pruebas carguen sin secretos.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# Cadencia mínima responsable frente al portal del SAT (comportamiento de
# usuario humano activo, nunca martilleo).
MIN_INTERVAL_SECONDS = 20


class ConfigError(Exception):
    """Configuración inválida o incompleta."""


@dataclass(frozen=True)
class Polling:
    interval_seconds: int
    jitter_seconds: int


@dataclass(frozen=True)
class Target:
    """Una oficina a vigilar.

    `entidad` es obligatoria porque el portal encadena los combos: sin elegir
    entidad federativa no se habilita el de módulo. `office` tiene que ser el
    texto **tal cual** aparece en ese combo, no como lo llamamos nosotros.
    """

    zone: str
    entidad: str
    office: str
    tramites: tuple[str, ...]
    enabled: bool


@dataclass(frozen=True)
class Telegram:
    enabled: bool
    bot_token: str
    # Destinos que reciben TODO, sin importar la zona (el número "de los dos"
    # que pidió el cliente).
    chat_ids: tuple[str, ...]
    # Destinos por zona: {"Cancun": ("123",), "CDMX": ("456",)}.
    by_zone: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def destinos(self, zona: str, routing: str) -> tuple[str, ...]:
        """Chats que deben recibir una alerta de esta zona, sin repetidos.

        Con `all` reciben todos; con `by_zone` reciben los de la zona más los
        que están dados de alta para todo.
        """
        if routing == "all":
            todos = list(self.chat_ids)
            for chats in self.by_zone.values():
                todos.extend(chats)
        else:
            todos = list(self.by_zone.get(zona, ())) + list(self.chat_ids)
        vistos: list[str] = []
        for chat in todos:
            if chat not in vistos:
                vistos.append(chat)
        return tuple(vistos)


@dataclass(frozen=True)
class WhatsApp:
    enabled: bool
    bridge_url: str
    numbers: tuple[str, ...]


@dataclass(frozen=True)
class Email:
    enabled: bool
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    recipients: tuple[str, ...]


@dataclass(frozen=True)
class Heartbeat:
    max_silence_minutes: int


@dataclass(frozen=True)
class Storage:
    sqlite_path: str
    screenshots_dir: str


@dataclass(frozen=True)
class Config:
    polling: Polling
    targets: tuple[Target, ...]
    telegram: Telegram
    whatsapp: WhatsApp
    email: Email
    routing: str
    heartbeat: Heartbeat
    storage: Storage


def _require(data: dict, key: str, ctx: str):
    if key not in data:
        raise ConfigError(f"Falta la clave '{key}' en {ctx}")
    return data[key]


def load_config(path: str | Path) -> Config:
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"No existe el archivo de configuración: {p}")
    try:
        texto = p.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        # Pasa cuando el archivo se guardó en ANSI/Latin-1 (típico del Bloc de
        # notas en Windows). El mensaje de Python no le dice nada a nadie, así
        # que se traduce a algo accionable.
        raise ConfigError(
            f"{p} no está guardado en UTF-8, y los acentos de nombres como "
            f"'Módulo Coyoacán' lo rompen. Vuelve a guardarlo con codificación "
            f"UTF-8 (detalle: {exc})"
        ) from exc
    try:
        raw = json.loads(texto)
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"JSON inválido en {p}, línea {exc.lineno}: {exc.msg}. "
            f"Suele ser una coma de más o unas comillas sin cerrar."
        ) from exc

    polling_raw = _require(raw, "polling", "config")
    polling = Polling(
        interval_seconds=int(_require(polling_raw, "interval_seconds", "polling")),
        jitter_seconds=int(polling_raw.get("jitter_seconds", 0)),
    )
    if polling.interval_seconds < MIN_INTERVAL_SECONDS:
        raise ConfigError(
            f"interval_seconds={polling.interval_seconds} es demasiado agresivo; "
            f"mínimo permitido: {MIN_INTERVAL_SECONDS}s"
        )

    targets_raw = _require(raw, "targets", "config")
    if not isinstance(targets_raw, list) or not targets_raw:
        raise ConfigError("'targets' debe ser una lista con al menos una oficina")
    targets = []
    for i, t in enumerate(targets_raw):
        ctx = f"targets[{i}]"
        tramites = _require(t, "tramites", ctx)
        if not tramites:
            raise ConfigError(f"{ctx} no tiene trámites configurados")
        targets.append(
            Target(
                zone=str(_require(t, "zone", ctx)),
                entidad=str(_require(t, "entidad", ctx)),
                office=str(_require(t, "office", ctx)),
                tramites=tuple(str(x) for x in tramites),
                enabled=bool(t.get("enabled", True)),
            )
        )
    if not any(t.enabled for t in targets):
        raise ConfigError("Ninguna oficina está habilitada en 'targets'")

    alerts = _require(raw, "alerts", "config")
    tg = _require(alerts, "telegram", "alerts")
    by_zone_raw = tg.get("by_zone", {}) or {}
    if not isinstance(by_zone_raw, dict):
        raise ConfigError("telegram.by_zone debe ser un objeto {zona: [chat_ids]}")
    telegram = Telegram(
        enabled=bool(tg.get("enabled", False)),
        bot_token=str(tg.get("bot_token", "")),
        chat_ids=tuple(str(x) for x in tg.get("chat_ids", [])),
        by_zone={str(k): tuple(str(x) for x in v) for k, v in by_zone_raw.items()},
    )
    wa = _require(alerts, "whatsapp", "alerts")
    whatsapp = WhatsApp(
        enabled=bool(wa.get("enabled", False)),
        bridge_url=str(wa.get("bridge_url", "")),
        numbers=tuple(str(x) for x in wa.get("numbers", [])),
    )
    em = _require(alerts, "email", "alerts")
    email = Email(
        enabled=bool(em.get("enabled", False)),
        smtp_host=str(em.get("smtp_host", "")),
        smtp_port=int(em.get("smtp_port", 587)),
        smtp_user=str(em.get("smtp_user", "")),
        smtp_password=str(em.get("smtp_password", "")),
        recipients=tuple(str(x) for x in em.get("recipients", [])),
    )

    routing = str(raw.get("routing", "by_zone"))
    if routing not in ("by_zone", "all"):
        raise ConfigError(f"routing='{routing}' inválido; usa 'by_zone' o 'all'")

    hb_raw = _require(raw, "heartbeat", "config")
    heartbeat = Heartbeat(
        max_silence_minutes=int(_require(hb_raw, "max_silence_minutes", "heartbeat"))
    )
    if heartbeat.max_silence_minutes < 1:
        raise ConfigError("heartbeat.max_silence_minutes debe ser >= 1")

    st_raw = _require(raw, "storage", "config")
    storage = Storage(
        sqlite_path=str(_require(st_raw, "sqlite_path", "storage")),
        screenshots_dir=str(_require(st_raw, "screenshots_dir", "storage")),
    )

    return Config(
        polling=polling,
        targets=tuple(targets),
        telegram=telegram,
        whatsapp=whatsapp,
        email=email,
        routing=routing,
        heartbeat=heartbeat,
        storage=storage,
    )


def validate_runtime(cfg: Config) -> list[str]:
    """Valida que los canales habilitados estén completos.

    Devuelve la lista de problemas (vacía si todo está listo). Se llama al
    arrancar el monitor, no al cargar el archivo.
    """
    problems: list[str] = []
    if cfg.telegram.enabled:
        if not cfg.telegram.bot_token or "PON_AQUI" in cfg.telegram.bot_token:
            problems.append("Telegram está habilitado pero falta bot_token real")
        if not cfg.telegram.chat_ids and not cfg.telegram.by_zone:
            problems.append("Telegram está habilitado pero no hay ningún destino")
        for target in cfg.targets:
            if target.enabled and not cfg.telegram.destinos(target.zone, cfg.routing):
                problems.append(
                    f"la zona '{target.zone}' está activa pero nadie recibiría sus alertas"
                )
    if cfg.whatsapp.enabled:
        if not cfg.whatsapp.bridge_url:
            problems.append("WhatsApp está habilitado pero falta bridge_url")
        if not cfg.whatsapp.numbers:
            problems.append("WhatsApp está habilitado pero numbers está vacío")
    if cfg.email.enabled:
        if not cfg.email.smtp_host or not cfg.email.recipients:
            problems.append("Email está habilitado pero falta smtp_host o recipients")
    if not (cfg.telegram.enabled or cfg.whatsapp.enabled or cfg.email.enabled):
        problems.append("Ningún canal de alerta está habilitado")
    return problems
