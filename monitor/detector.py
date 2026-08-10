"""Detección de estado del portal — la pieza que evita el falso "no hay citas".

La preocupación concreta del cliente: hay scrapers que siguen "corriendo" con la
sesión muerta, leen una página vacía y reportan cero disponibilidad para
siempre, sin marcar error. Este módulo existe para que eso no pueda pasar.

La regla es una sola y no se negocia:

    **Nunca se concluye "no hay citas" sin haber confirmado antes que estamos
    de verdad en la pantalla de disponibilidad.**

El ancla de esa confirmación es el reloj de cuenta regresiva (`#timer`) que el
portal dibuja en `/creaCita`. Si el reloj está y corre, la pantalla es real. Si
no está, no sabemos nada de la disponibilidad: sabemos que la sesión se cayó,
que es información distinta y que dispara otra alarma.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from playwright.async_api import Page

from . import selectors as S

# Estados posibles de una lectura del portal.
SESSION_OK = "SESSION_OK"                # en /creaCita con el reloj corriendo
CAPTCHA_REQUIRED = "CAPTCHA_REQUIRED"    # el portal pide captcha → humano
IDENTITY_SCREEN = "IDENTITY_SCREEN"      # en /datosPersonales, falta identidad
SESSION_DEAD = "SESSION_DEAD"            # de vuelta al inicio: sesión muerta
UNKNOWN = "UNKNOWN"                      # no reconocemos la pantalla

# Estados en los que preguntar por disponibilidad no tiene ningún sentido.
NO_SIRVE_PARA_LEER_CITAS = (CAPTCHA_REQUIRED, IDENTITY_SCREEN, SESSION_DEAD, UNKNOWN)

_MMSS = re.compile(r"(\d{1,2}):(\d{2})")


@dataclass(frozen=True)
class Detection:
    """Resultado de mirar el portal una vez."""

    state: str
    url: str
    seconds_left: int | None = None
    detail: str = ""

    @property
    def can_read_availability(self) -> bool:
        """¿Tiene sentido leer disponibilidad en esta pantalla?"""
        return self.state == SESSION_OK

    @property
    def needs_human(self) -> bool:
        """¿Hace falta que una persona abra o reabra la sesión?"""
        return self.state in (CAPTCHA_REQUIRED, SESSION_DEAD, IDENTITY_SCREEN)


async def read_countdown_seconds(page: Page) -> int | None:
    """Segundos que le quedan a la ventana de 5 minutos, o None si no hay reloj.

    Que no haya reloj es justamente la señal de que no estamos en la pantalla
    de disponibilidad.
    """
    try:
        locator = page.locator(S.COUNTDOWN).first
        if not await locator.count():
            return None
        text = (await locator.inner_text(timeout=5_000)).strip()
    except Exception:
        return None

    match = _MMSS.search(text)
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


async def detect(page: Page) -> Detection:
    """Clasifica la pantalla actual. Nunca adivina disponibilidad."""
    try:
        url = page.url
    except Exception:
        return Detection(UNKNOWN, "", detail="la página ya no responde")

    # 1. ¿Estamos en la pantalla de citas con el reloj vivo?
    seconds = await read_countdown_seconds(page)
    if seconds is not None and "creaCita" in url:
        return Detection(
            SESSION_OK, url, seconds_left=seconds,
            detail=f"pantalla de disponibilidad viva, quedan {seconds}s",
        )

    # 2. ¿El portal está pidiendo captcha? Lo resuelve una persona, siempre.
    try:
        if await page.locator(S.CAPTCHA_INPUT).count():
            return Detection(CAPTCHA_REQUIRED, url, detail="captcha en pantalla")
    except Exception:
        pass

    # 3. ¿Nos quedamos en la pantalla de identidad?
    if "datosPersonales" in url:
        return Detection(IDENTITY_SCREEN, url, detail="falta capturar identidad")

    # 4. ¿Nos regresó al inicio? Es como muere la ventana de 5 minutos.
    if url.rstrip("/").endswith("citas.sat.gob.mx"):
        return Detection(
            SESSION_DEAD, url,
            detail="de vuelta en el inicio: la ventana se agotó o la sesión murió",
        )

    # 5. En /creaCita pero sin reloj: la pantalla se está muriendo.
    if "creaCita" in url:
        return Detection(
            SESSION_DEAD, url,
            detail="en /creaCita pero sin reloj: la sesión ya no es confiable",
        )

    return Detection(UNKNOWN, url, detail="pantalla no reconocida")


def describe(detection: Detection) -> str:
    """Frase corta en español para el log y para las alertas."""
    if detection.state == SESSION_OK:
        left = detection.seconds_left or 0
        return f"Sesión viva ({left // 60}:{left % 60:02d} restantes)"
    if detection.state == CAPTCHA_REQUIRED:
        return "El portal pide captcha: se necesita una persona"
    if detection.state == IDENTITY_SCREEN:
        return "Pantalla de identidad: falta abrir la sesión"
    if detection.state == SESSION_DEAD:
        return "Sesión caída: hay que reabrirla a mano"
    return "Pantalla desconocida: no se puede afirmar nada sobre las citas"
