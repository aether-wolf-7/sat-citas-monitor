"""Arranque de Playwright y utilidades de navegador.

Dos decisiones importantes aquí:

1. **Contexto persistente.** El navegador guarda su perfil en disco
   (`user_data_dir`). Cuando un gestor abre la sesión a mano (resuelve el
   captcha), esa sesión sobrevive a reinicios del monitor y del servidor. Sin
   esto, cada reinicio obligaría a molestar a un humano otra vez.

2. **`headless` es configurable, no fijo.** Para el traspaso de captcha (paso 8)
   el navegador corre *con interfaz* dentro de Xvfb, para que el gestor lo vea
   por noVNC y resuelva el captcha él mismo. Nunca lo resuelve el sistema.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

# Portal público de citas del SAT.
SAT_CITAS_URL = "https://citas.sat.gob.mx/"

# Navegador realista: no es evasión, es presentarse como un usuario normal de
# México para que el portal sirva la misma página que a cualquier persona.
DEFAULT_LOCALE = "es-MX"
DEFAULT_TIMEZONE = "America/Mexico_City"
DEFAULT_VIEWPORT = {"width": 1366, "height": 900}
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


@dataclass
class BrowserSession:
    """Envoltura del contexto persistente + la pestaña de trabajo."""

    context: BrowserContext
    page: Page
    _playwright: object
    _browser: Browser | None = None

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            await self.context.close()
        if self._browser is not None:
            with contextlib.suppress(Exception):
                await self._browser.close()
        with contextlib.suppress(Exception):
            await self._playwright.stop()


async def launch(
    *,
    user_data_dir: str | Path = "data/browser-profile",
    headless: bool = True,
    slow_mo: int = 0,
) -> BrowserSession:
    """Abre Chromium con perfil persistente y devuelve la sesión lista."""
    profile = Path(user_data_dir)
    profile.mkdir(parents=True, exist_ok=True)

    pw = await async_playwright().start()
    context = await pw.chromium.launch_persistent_context(
        str(profile),
        headless=headless,
        slow_mo=slow_mo,
        locale=DEFAULT_LOCALE,
        timezone_id=DEFAULT_TIMEZONE,
        viewport=DEFAULT_VIEWPORT,
        user_agent=DEFAULT_USER_AGENT,
        args=["--disable-blink-features=AutomationControlled"],
    )
    page = context.pages[0] if context.pages else await context.new_page()
    page.set_default_timeout(30_000)
    return BrowserSession(context=context, page=page, _playwright=pw)


async def goto_portal(page: Page, url: str = SAT_CITAS_URL, *, timeout_ms: int = 45_000):
    """Carga el portal. Devuelve la respuesta (o None si vino de caché/redirect)."""
    return await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)


async def click_when_ready(
    page: Page, selector: str, *, timeout_ms: int = 30_000
) -> None:
    """Espera a que el elemento sea visible y entonces le hace clic.

    Sustituye al patrón frágil de "dormir N segundos y luego clic": el portal
    es una SPA y tarda lo que tarda. Un `sleep` fijo funciona en la máquina de
    desarrollo y falla de madrugada en el servidor, que es justo cuando nadie
    está viendo.
    """
    locator = page.locator(selector).first
    await locator.wait_for(state="visible", timeout=timeout_ms)
    await locator.click(timeout=timeout_ms)


async def wait_for_any(
    page: Page, selectors: list[str], *, timeout_ms: int = 30_000
) -> str | None:
    """Devuelve el primer selector que aparezca, o None si vence el plazo.

    Útil cuando el portal puede responder con varias pantallas distintas
    (disponibilidad, captcha, sesión caída) y hay que reaccionar a la que toque.
    """
    import asyncio

    async def _wait(sel: str) -> str:
        await page.locator(sel).first.wait_for(state="visible", timeout=timeout_ms)
        return sel

    tasks = [asyncio.create_task(_wait(s)) for s in selectors]
    try:
        done, pending = await asyncio.wait(
            tasks, timeout=timeout_ms / 1000, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        for task in done:
            with contextlib.suppress(Exception):
                return task.result()
        return None
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()


async def take_screenshot(
    page: Page,
    screenshots_dir: str | Path,
    *,
    label: str = "captura",
    full_page: bool = True,
) -> Path:
    """Guarda una captura con nombre trazable: <etiqueta>_<UTC>.png."""
    out_dir = Path(screenshots_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in label)
    path = out_dir / f"{safe}_{stamp}.png"
    await page.screenshot(path=str(path), full_page=full_page)
    return path
