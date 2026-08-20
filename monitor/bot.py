"""Bot de Telegram: el gestor pide la búsqueda cuando él quiere.

Esta pieza existe por una lección que costó tres sesiones perdidas. Antes las
búsquedas las arrancaba el desarrollador, y para cuando el gestor llegaba a su
teléfono la liga ya se había apagado. El orden correcto es al revés:

    el gestor pide  ->  el sistema abre  ->  el gestor resuelve el captcha

Así la liga nace segundos antes de usarse y nunca llega muerta.

Comandos:
    /buscar   arranca una búsqueda y regresa la liga de la pantalla
    /estado   dice si hay algo corriendo y cómo salió lo último
    /ayuda    recordatorio de cómo funciona

Reglas que no se negocian:
  * Sólo responde a los chats dados de alta en la configuración. Cualquier otro
    recibe una negativa: quien tenga la liga puede abrir sesiones con el RFC del
    cliente, así que esto no se deja abierto.
  * Una búsqueda a la vez. Dos corridas peleándose el mismo perfil de navegador
    terminan en el error de "perfil en uso" que ya nos costó una tarde.
  * El bot **no** resuelve captchas ni agenda nada. Sólo abre la puerta para que
    lo haga una persona.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

import httpx

from .config import Config, load_config
from .pantalla import url_actual
from .reporte import ESTADOS

API = "https://api.telegram.org/bot{token}/{metodo}"

AYUDA = (
    "Así funciona:\n\n"
    "/buscar — abro el portal del SAT y te paso una liga. La abres, resuelves "
    "el captcha, y de ahí yo reviso las oficinas y te aviso qué encontré.\n\n"
    "/estado — te digo si hay algo corriendo y cómo salió lo último.\n\n"
    "Recuerda: el captcha lo resuelves tú y la cita la agendas tú. "
    "Yo sólo miro y aviso."
)


def chats_autorizados(cfg: Config) -> set[str]:
    """Todos los chats dados de alta, sin importar la zona."""
    permitidos = set(cfg.telegram.chat_ids)
    for chats in cfg.telegram.by_zone.values():
        permitidos.update(chats)
    return permitidos


class Bot:
    def __init__(self, cfg: Config, config_path: str, espera: int = 900):
        self.cfg = cfg
        self.config_path = config_path
        self.espera = espera
        self.token = cfg.telegram.bot_token
        self.autorizados = chats_autorizados(cfg)
        self.corrida: subprocess.Popen | None = None
        self.offset: int | None = None

    # ---------- Telegram ----------

    async def _llamar(self, cliente: httpx.AsyncClient, metodo: str, **params):
        try:
            r = await cliente.get(API.format(token=self.token, metodo=metodo),
                                  params=params)
            data = r.json()
            return data.get("result") if data.get("ok") else None
        except Exception as exc:
            print(f"  [telegram] {type(exc).__name__}: {exc}", flush=True)
            return None

    async def responder(self, cliente: httpx.AsyncClient, chat_id: str, texto: str):
        await self._llamar(cliente, "sendMessage", chat_id=chat_id, text=texto,
                           disable_web_page_preview="false")

    # ---------- estado de la corrida ----------

    @property
    def corriendo(self) -> bool:
        return self.corrida is not None and self.corrida.poll() is None

    def arrancar_corrida(self) -> None:
        """Lanza la búsqueda como proceso aparte y no lo espera."""
        self.corrida = subprocess.Popen(
            [sys.executable, "-m", "monitor.run",
             "--config", self.config_path,
             "--handoff",
             "--espera", str(self.espera),
             "--sin-alarma-inicial"],   # la liga ya se la mandó el bot
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    # ---------- comandos ----------

    async def cmd_buscar(self, cliente: httpx.AsyncClient, chat_id: str):
        if self.corriendo:
            await self.responder(cliente, chat_id,
                "Ya hay una búsqueda en curso. Espera a que termine esa y "
                "vuelve a pedirla.\n\n" + (url_actual() or ""))
            return

        liga = url_actual()
        if not liga:
            await self.responder(cliente, chat_id,
                "La pantalla remota está apagada, así que no puedo abrir la "
                "sesión. Avísale al desarrollador: hay que encender el "
                "servicio 'satmon-pantalla'.")
            return

        self.arrancar_corrida()
        minutos = max(1, self.espera // 60)
        await self.responder(cliente, chat_id,
            "Listo, ya abrí el portal del SAT.\n\n"
            f"1. Entra aquí: {liga}\n"
            "2. Palomea la casilla de términos\n"
            "3. Resuelve el captcha y dale Siguiente\n"
            "4. Ya no le muevas: yo sigo desde ahí\n\n"
            f"Tienes {minutos} minutos. En cuanto pases el captcha reviso las "
            "oficinas y te aviso qué encontré.")
        print(f"  [bot] búsqueda arrancada por {chat_id}", flush=True)

    async def cmd_estado(self, cliente: httpx.AsyncClient, chat_id: str):
        lineas = []
        lineas.append("Búsqueda en curso." if self.corriendo
                      else "No hay ninguna búsqueda corriendo.")
        liga = url_actual()
        lineas.append(f"Pantalla: {'encendida' if liga else 'apagada'}")

        import sqlite3
        ruta = Path(self.cfg.storage.sqlite_path)
        if ruta.exists():
            conn = sqlite3.connect(ruta)
            conn.row_factory = sqlite3.Row
            try:
                fila = conn.execute(
                    "SELECT * FROM checks ORDER BY id DESC LIMIT 1").fetchone()
                if fila:
                    estado = ESTADOS.get(fila["state"], fila["state"])
                    citas = ("no se pudo determinar" if fila["availability"] is None
                             else ("HABÍA LUGAR" if fila["availability"] else "sin lugar"))
                    lineas += ["", "Lo último que revisé:",
                               f"  {fila['ts']}",
                               f"  {fila['office']}",
                               f"  {estado} — {citas}"]
            finally:
                conn.close()
        if liga:
            lineas += ["", liga]
        await self.responder(cliente, chat_id, "\n".join(lineas))

    # ---------- ciclo principal ----------

    async def atender(self, cliente: httpx.AsyncClient, mensaje: dict):
        chat = mensaje.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        texto = (mensaje.get("text") or "").strip().lower()
        if not chat_id or not texto:
            return

        if chat_id not in self.autorizados:
            # Ni se le da información de más a quien no está dado de alta.
            await self.responder(cliente, chat_id,
                "Este bot es privado. Si crees que deberías tener acceso, "
                "habla con quien te compartió el sistema.")
            print(f"  [bot] chat no autorizado: {chat_id}", flush=True)
            return

        if texto.startswith("/buscar"):
            await self.cmd_buscar(cliente, chat_id)
        elif texto.startswith("/estado"):
            await self.cmd_estado(cliente, chat_id)
        elif texto.startswith(("/ayuda", "/help", "/start")):
            await self.responder(cliente, chat_id, AYUDA)
        else:
            await self.responder(cliente, chat_id,
                "No reconocí eso. Usa /buscar para arrancar una búsqueda "
                "o /ayuda para ver cómo funciona.")

    async def correr(self) -> None:
        print(f"Bot escuchando. Chats dados de alta: {len(self.autorizados)}", flush=True)
        async with httpx.AsyncClient(timeout=40) as cliente:
            while True:
                params = {"timeout": 30}
                if self.offset is not None:
                    params["offset"] = self.offset
                updates = await self._llamar(cliente, "getUpdates", **params)
                if updates is None:
                    await asyncio.sleep(5)      # error de red: no atropellar la API
                    continue
                for u in updates:
                    self.offset = u["update_id"] + 1
                    mensaje = u.get("message") or u.get("edited_message")
                    if mensaje:
                        await self.atender(cliente, mensaje)


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")
    import argparse
    ap = argparse.ArgumentParser(description="Bot de Telegram del monitor SAT")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--espera", type=int, default=900,
                    help="minutos*60 que espera el captcha en cada búsqueda")
    args = ap.parse_args()

    cfg = load_config(args.config)
    if not cfg.telegram.enabled or not cfg.telegram.bot_token:
        raise SystemExit("Telegram no está configurado en config.json")
    if not chats_autorizados(cfg):
        raise SystemExit("No hay ningún chat dado de alta: nadie podría usar el bot")

    asyncio.run(Bot(cfg, args.config, args.espera).correr())


if __name__ == "__main__":
    main()
