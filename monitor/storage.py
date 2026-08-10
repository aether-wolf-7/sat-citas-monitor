"""Persistencia en SQLite: historial de chequeos, detecciones y alertas.

Este historial es también la fuente para responder, con datos reales, la
pregunta del cliente: "¿cada cuánto se cae la sesión del SAT en la práctica?"
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# Estados que puede reportar un chequeo (los produce el detector del paso 3).
STATE_SESSION_OK = "SESSION_OK"
STATE_CAPTCHA_OR_EXPIRED = "CAPTCHA_OR_EXPIRED"
STATE_UNKNOWN = "UNKNOWN"
STATE_ERROR = "ERROR"

# Tipos de alerta (modelo de dos alarmas + watchdog).
ALERT_SESSION = "session"       # alarma 1: abrir sesión / resolver captcha (humano)
ALERT_APPOINTMENT = "appointment"  # alarma 2: hay cita, agendar a mano (humano)
ALERT_HEARTBEAT = "heartbeat"   # watchdog: demasiado tiempo sin lectura válida

_SCHEMA = """
CREATE TABLE IF NOT EXISTS checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    zone TEXT NOT NULL,
    office TEXT NOT NULL,
    tramite TEXT,
    state TEXT NOT NULL,
    availability INTEGER,   -- NULL: no se pudo leer; 0: sin citas; 1: hay citas
    detail TEXT
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    kind TEXT NOT NULL,
    zone TEXT,
    office TEXT,
    tramite TEXT,
    channel TEXT NOT NULL,
    ok INTEGER NOT NULL,
    detail TEXT
);

CREATE INDEX IF NOT EXISTS idx_checks_ts ON checks (ts);
CREATE INDEX IF NOT EXISTS idx_checks_state ON checks (state, ts);
CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts (ts);
"""


def connect(sqlite_path: str | Path) -> sqlite3.Connection:
    """Abre (creando si hace falta) la base y garantiza el esquema."""
    path = Path(sqlite_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def log_check(
    conn: sqlite3.Connection,
    *,
    zone: str,
    office: str,
    state: str,
    tramite: str | None = None,
    availability: int | None = None,
    detail: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO checks (zone, office, tramite, state, availability, detail) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (zone, office, tramite, state, availability, detail),
    )
    conn.commit()
    return cur.lastrowid


def log_alert(
    conn: sqlite3.Connection,
    *,
    kind: str,
    channel: str,
    ok: bool,
    zone: str | None = None,
    office: str | None = None,
    tramite: str | None = None,
    detail: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO alerts (kind, zone, office, tramite, channel, ok, detail) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (kind, zone, office, tramite, channel, int(ok), detail),
    )
    conn.commit()
    return cur.lastrowid


def last_check_ts(conn: sqlite3.Connection, state: str | None = None) -> str | None:
    """Timestamp (UTC) del último chequeo, opcionalmente filtrado por estado.

    El watchdog usa `state=STATE_SESSION_OK`: si el último chequeo *válido*
    es demasiado viejo, el silencio deja de significar "todo bien" y se alerta.
    """
    if state is None:
        row = conn.execute("SELECT MAX(ts) AS ts FROM checks").fetchone()
    else:
        row = conn.execute(
            "SELECT MAX(ts) AS ts FROM checks WHERE state = ?", (state,)
        ).fetchone()
    return row["ts"] if row and row["ts"] else None


def recent_checks(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM checks ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
