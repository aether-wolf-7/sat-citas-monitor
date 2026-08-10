"""Sesión de mapeo asistida por humano: graba las pantallas de disponibilidad.

El portal no enseña disponibilidad a un visitante anónimo (ver
`docs/portal-map.md`): exige datos reales y captcha. Y el captcha lo resuelve
una persona, siempre. Así que esta herramienta invierte los papeles:

    **la persona navega, el programa graba.**

Abre el navegador *con interfaz*, llena los campos de identidad que se le pasen
por línea de comandos, y a partir de ahí se queda mirando: cada vez que cambia
la pantalla, guarda captura + estructura del DOM. Con eso salen los selectores
reales del selector de oficina y del calendario, que son los que faltan para
los pasos 3 y 4.

Es el mismo patrón del traspaso de captcha del paso 8, usado antes de tiempo
para mapear.

Reglas que este archivo respeta y que no se negocian:
  - NUNCA escribe en el campo del captcha.
  - NUNCA envía el formulario: el "Siguiente" lo aprieta la persona.
  - NUNCA agenda una cita.
  - Los datos de identidad llegan por argumento y no se guardan en el repo.

Uso (trámite e.firma / quien ya tiene RFC):
    python -m monitor.mapsession --rfc TURFC --email tu@correo.com

Uso (inscripción al RFC, persona física):
    python -m monitor.mapsession --curp TUCURP --nombre "Nombre Completo" \\
        --email tu@correo.com --tramite rfc-fisica

Validar el camino sin enviar nada (no requiere resolver captcha):
    python -m monitor.mapsession --rfc TURFC --email tu@correo.com --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import Page

from . import browser as br
from . import selectors as S
from .recon import describe

TRAMITE_CON_RFC = "efirma"
TRAMITE_RFC_FISICA = "rfc-fisica"
TRAMITE_RFC_MORAL = "rfc-moral"


async def _dump(page: Page, out_dir: Path, label: str) -> dict:
    """Guarda captura + estructura de la pantalla actual."""
    info = await describe(page)
    shot = await br.take_screenshot(page, out_dir / "screenshots", label=label)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    (out_dir / f"{label}_{stamp}.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / f"{label}_{stamp}.html").write_text(
        await page.content(), encoding="utf-8"
    )
    print(f"  [grabado] {label} — {page.url}")
    print(f"            captura: {shot.name}")
    return info


async def _open_tramite_panel(page: Page, tramite: str) -> None:
    """Llega a /datosPersonales y abre el panel del trámite pedido."""
    await br.goto_portal(page, S.BASE_URL)
    await page.wait_for_timeout(4000)
    try:
        await page.locator(S.MODAL_AVISO_CERRAR).click(timeout=8000)
    except Exception:
        pass  # el aviso no siempre aparece
    await page.wait_for_timeout(1000)

    await page.locator(S.BTN_REGISTRAR_CITA).click(timeout=15000)
    await page.wait_for_timeout(4000)
    await page.locator(S.CARD_SERVICIOS_GENERALES).click(timeout=15000)
    await page.wait_for_timeout(5000)

    index = {TRAMITE_CON_RFC: 0, TRAMITE_RFC_MORAL: 1, TRAMITE_RFC_FISICA: 2}[tramite]
    await page.locator(S.PANEL_HEADER).nth(index).click(timeout=15000)
    await page.wait_for_timeout(2500)


async def _fill_identity(page: Page, args) -> None:
    """Llena identidad y correo. No toca el captcha ni envía nada."""
    if args.tramite == TRAMITE_CON_RFC:
        await page.locator(S.INPUT_RFC).fill(args.rfc)
    elif args.tramite == TRAMITE_RFC_FISICA:
        await page.locator(S.INPUT_CURP).fill(args.curp)
        await page.locator(S.INPUT_NOMBRE).fill(args.nombre)
    else:
        await page.locator(S.INPUT_RFC).fill(args.rfc)
        await page.locator(S.INPUT_RAZON_SOCIAL).fill(args.razon_social)

    await page.locator(S.INPUT_CORREO).fill(args.email)
    confirm = page.locator(S.INPUT_CORREO_CONFIRMA)
    if await confirm.count():
        await confirm.fill(args.email)
    await page.wait_for_timeout(1200)


async def _watch_and_record(page: Page, out_dir: Path, minutes: int) -> None:
    """Graba cada pantalla nueva mientras la persona navega."""
    print()
    print("=" * 68)
    print("  TU TURNO. El programa ya no toca nada.")
    print()
    print("  1. Resuelve el captcha en la ventana del navegador.")
    print("  2. Aprieta 'Siguiente' y sigue hasta el calendario de citas.")
    print("  3. Entra a la oficina de Cancún y déjala a la vista.")
    print()
    print(f"  Voy grabando cada pantalla durante {minutes} minutos.")
    print("  Ctrl+C cuando termines.")
    print("=" * 68)
    print()

    seen: set[str] = set()
    deadline = minutes * 60
    elapsed = 0
    step = 0

    while elapsed < deadline:
        try:
            fingerprint = await page.evaluate(
                "() => location.href + '|' + (document.body ? "
                "document.body.innerText.replace(/\\s+/g,' ').slice(0, 400) : '')"
            )
        except Exception:
            await asyncio.sleep(3)
            elapsed += 3
            continue

        if fingerprint not in seen:
            seen.add(fingerprint)
            step += 1
            await _dump(page, out_dir, f"paso{step:02d}")

        await asyncio.sleep(3)
        elapsed += 3

    print(f"\nSe acabó el tiempo. {step} pantallas grabadas en {out_dir}")


async def run(args) -> None:
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    session = await br.launch(
        user_data_dir=out_dir / "browser-profile",
        headless=args.dry_run,  # la sesión real necesita ventana visible
        slow_mo=250,
    )
    try:
        page = session.page
        print("Abriendo el portal y llegando a la pantalla de identidad...")
        await _open_tramite_panel(page, args.tramite)
        await _fill_identity(page, args)
        print("Campos de identidad llenos. El captcha queda intacto.")

        await _dump(page, out_dir, "identidad")

        captcha_present = await page.locator(S.CAPTCHA_INPUT).count()
        print(f"Campo de captcha en pantalla: {'sí' if captcha_present else 'todavía no'}")

        if args.dry_run:
            print("\n--dry-run: no se envía nada. Camino validado hasta el captcha.")
            return

        await _watch_and_record(page, out_dir, args.minutes)
    finally:
        if not args.keep_open:
            await session.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Mapeo de disponibilidad asistido por humano")
    ap.add_argument("--tramite", default=TRAMITE_CON_RFC,
                    choices=[TRAMITE_CON_RFC, TRAMITE_RFC_FISICA, TRAMITE_RFC_MORAL])
    ap.add_argument("--rfc", default="")
    ap.add_argument("--curp", default="")
    ap.add_argument("--nombre", default="")
    ap.add_argument("--razon-social", default="")
    ap.add_argument("--email", default="")
    ap.add_argument("--minutes", type=int, default=15, help="cuánto tiempo grabar")
    ap.add_argument("--dry-run", action="store_true",
                    help="llena y valida el camino, sin enviar ni esperar captcha")
    ap.add_argument("--keep-open", action="store_true", help="no cerrar el navegador al final")
    ap.add_argument("--out", default="data/map", help="carpeta de salida (fuera de git)")
    args = ap.parse_args()

    if args.tramite == TRAMITE_RFC_FISICA and not (args.curp and args.nombre):
        ap.error("inscripción persona física requiere --curp y --nombre")
    if args.tramite in (TRAMITE_CON_RFC, TRAMITE_RFC_MORAL) and not args.rfc:
        ap.error(f"el trámite {args.tramite} requiere --rfc")
    if args.tramite == TRAMITE_RFC_MORAL and not args.razon_social:
        ap.error("inscripción persona moral requiere --razon-social")
    if not args.email:
        ap.error("--email es obligatorio: el portal lo exige")

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
