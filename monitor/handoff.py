"""Traspaso del captcha: el gestor ve el navegador del servidor desde su celular.

Es la pieza que el gestor toca **cada vez** que quiere buscar citas, así que
tiene que ser de un toque y funcionar en un teléfono. Cómo se arma:

    Chromium con interfaz  ->  pantalla virtual (Xvfb)
                               -> x11vnc la publica en local
                               -> noVNC la vuelve una página web
                               -> túnel de Cloudflare le da una URL pública

Dos cosas que importan y no son casualidad:

* **La pantalla virtual sólo contiene el navegador.** No es el escritorio de
  nadie: no se ven archivos, ni otras ventanas, ni nada más del servidor.
* **El túnel sale hacia afuera.** El VPS del cliente tiene IP compartida y sólo
  un puerto abierto (el de SSH), así que no se puede publicar nada de forma
  directa. Como el túnel lo abre el servidor hacia Cloudflare, la limitación
  deja de estorbar — y de paso no queda ningún puerto expuesto a internet.

El sistema jamás resuelve el captcha. Nada más le acerca la pantalla a una
persona para que lo resuelva ella.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import secrets
import shutil
from dataclasses import dataclass, field
from pathlib import Path

DISPLAY = ":99"
PANTALLA = "1280x1024x24"
PUERTO_VNC = 5900
PUERTO_WEB = 6080
RUTA_NOVNC = "/usr/share/novnc"

_URL_TUNEL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


class HandoffError(Exception):
    """No se pudo levantar la pantalla remota."""


@dataclass
class Handoff:
    """Ciclo de vida de la pantalla remota."""

    display: str = DISPLAY
    puerto_vnc: int = PUERTO_VNC
    puerto_web: int = PUERTO_WEB
    url_publica: str = ""
    password: str = ""
    _procesos: list = field(default_factory=list)
    _dir_logs: Path | None = None

    # ---------- utilidades ----------

    @staticmethod
    def disponible() -> list[str]:
        """Qué falta instalar en el servidor. Lista vacía = todo listo."""
        faltan = [b for b in ("Xvfb", "x11vnc", "websockify", "cloudflared")
                  if shutil.which(b) is None]
        if not Path(RUTA_NOVNC).is_dir():
            faltan.append("novnc")
        return faltan

    async def _lanzar(self, *args: str, log: Path):
        fh = log.open("ab")
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=fh, stderr=fh, stdin=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        self._procesos.append(proc)
        return proc

    # ---------- arranque ----------

    async def start(self, *, timeout_tunel: int = 90) -> str:
        """Levanta todo y devuelve la liga que se le manda al gestor."""
        faltan = self.disponible()
        if faltan:
            raise HandoffError(f"faltan componentes en el servidor: {', '.join(faltan)}")

        self._dir_logs = Path("logs/handoff")
        self._dir_logs.mkdir(parents=True, exist_ok=True)

        # 1. Pantalla virtual: existe sólo para el navegador.
        await self._lanzar("Xvfb", self.display, "-screen", "0", PANTALLA,
                           "-nolisten", "tcp", log=self._dir_logs / "xvfb.log")
        await asyncio.sleep(2)
        os.environ["DISPLAY"] = self.display

        # 2. Contraseña de un solo uso para el VNC.
        self.password = secrets.token_urlsafe(9)
        archivo_pw = self._dir_logs / "vncpw"
        proc = await asyncio.create_subprocess_exec(
            "x11vnc", "-storepasswd", self.password, str(archivo_pw),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        with contextlib.suppress(Exception):
            archivo_pw.chmod(0o600)

        # 3. x11vnc atado a localhost: sólo el túnel puede llegarle.
        await self._lanzar(
            "x11vnc", "-display", self.display, "-rfbport", str(self.puerto_vnc),
            "-rfbauth", str(archivo_pw), "-localhost", "-forever", "-shared",
            "-noxdamage", "-repeat", "-quiet",
            log=self._dir_logs / "x11vnc.log",
        )
        await asyncio.sleep(2)

        # 4. noVNC: convierte el VNC en una página que abre cualquier celular.
        await self._lanzar(
            "websockify", "--web", RUTA_NOVNC,
            f"127.0.0.1:{self.puerto_web}", f"127.0.0.1:{self.puerto_vnc}",
            log=self._dir_logs / "novnc.log",
        )
        await asyncio.sleep(2)

        # 5. Túnel de salida -> URL pública con HTTPS.
        log_tunel = self._dir_logs / "cloudflared.log"
        log_tunel.write_bytes(b"")
        await self._lanzar(
            "cloudflared", "tunnel", "--url", f"http://127.0.0.1:{self.puerto_web}",
            "--no-autoupdate", log=log_tunel,
        )

        base = await self._esperar_url(log_tunel, timeout_tunel)
        # Autoconexión: el gestor abre la liga y ya está adentro, sin teclear
        # nada. La contraseña viaja en la liga a propósito: la liga ya es el
        # secreto, es distinta cada vez y muere con la sesión de 5 minutos.
        # Pedirle a alguien que escriba una contraseña en el celular con el
        # reloj corriendo sería cambiar seguridad real por fricción real.
        self.url_publica = (
            f"{base}/vnc.html?autoconnect=true&resize=scale&password={self.password}"
        )
        return self.url_publica

    async def _esperar_url(self, log: Path, timeout: int) -> str:
        for _ in range(timeout):
            await asyncio.sleep(1)
            with contextlib.suppress(Exception):
                encontrado = _URL_TUNEL.search(log.read_text(errors="replace"))
                if encontrado:
                    return encontrado.group(0)
        cola = ""
        with contextlib.suppress(Exception):
            cola = log.read_text(errors="replace")[-400:]
        raise HandoffError(f"el túnel no dio URL en {timeout}s. Última salida:\n{cola}")

    # ---------- apagado ----------

    async def stop(self) -> None:
        """Baja todo. La liga deja de existir en cuanto muere el túnel."""
        for proc in reversed(self._procesos):
            with contextlib.suppress(Exception):
                proc.terminate()
        await asyncio.sleep(1)
        for proc in reversed(self._procesos):
            with contextlib.suppress(Exception):
                if proc.returncode is None:
                    proc.kill()
        self._procesos.clear()
        self.url_publica = ""

    async def __aenter__(self) -> "Handoff":
        await self.start()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.stop()
