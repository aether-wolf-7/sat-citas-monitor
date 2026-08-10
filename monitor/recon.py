"""Reconocimiento del portal de citas del SAT.

Herramienta de desarrollo, no parte del monitor 24/7. Carga el portal, guarda
una captura y vuelca la estructura real de la página (títulos, formularios,
campos, botones, selects, iframes) para poder escribir selectores confiables
en vez de adivinarlos.

Uso:
    python -m monitor.recon                  # headless, portal por defecto
    python -m monitor.recon --headed         # con interfaz, para mirarlo
    python -m monitor.recon --url <otra_url>

Solo lee la página pública. No envía formularios, no toca el captcha.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import Page

from . import browser as br

# Pistas de texto que suelen delatar el estado de la página.
CAPTCHA_HINTS = ["captcha", "recaptcha", "no soy un robot", "hcaptcha", "turnstile"]
SESSION_HINTS = ["sesión", "sesion", "expir", "vencid", "inicia sesión", "vuelve a intentar"]
AVAILABILITY_HINTS = [
    "no hay citas", "sin citas", "no existen citas", "citas disponibles",
    "disponibilidad", "no hay disponibilidad", "agenda", "seleccione",
]


async def describe(page: Page) -> dict:
    """Extrae un retrato estructural de la página cargada."""
    return await page.evaluate(
        """
        () => {
          const clip = (s, n = 120) => (s || '').trim().replace(/\\s+/g, ' ').slice(0, n);
          const list = (sel, fn) => Array.from(document.querySelectorAll(sel)).slice(0, 40).map(fn);
          return {
            title: document.title,
            url: location.href,
            forms: list('form', f => ({
              id: f.id || null, name: f.name || null,
              action: f.getAttribute('action'), method: f.method,
            })),
            inputs: list('input, textarea', i => ({
              tag: i.tagName.toLowerCase(), type: i.type || null,
              id: i.id || null, name: i.name || null,
              placeholder: i.placeholder || null,
              visible: !!(i.offsetWidth || i.offsetHeight || i.getClientRects().length),
            })),
            selects: list('select', s => ({
              id: s.id || null, name: s.name || null,
              options: Array.from(s.options).slice(0, 15).map(o => clip(o.textContent, 60)),
            })),
            buttons: list('button, input[type=submit], a.btn, [role=button]', b => ({
              tag: b.tagName.toLowerCase(), id: b.id || null,
              text: clip(b.innerText || b.value, 60),
              visible: !!(b.offsetWidth || b.offsetHeight || b.getClientRects().length),
            })),
            iframes: list('iframe', f => ({
              id: f.id || null, name: f.name || null,
              src: clip(f.getAttribute('src'), 160),
              title: f.getAttribute('title'),
            })),
            headings: list('h1, h2, h3', h => clip(h.innerText, 90)).filter(Boolean),
            bodyText: clip(document.body ? document.body.innerText : '', 3000),
          };
        }
        """
    )


def find_hints(text: str, hints: list[str]) -> list[str]:
    low = (text or "").lower()
    return [h for h in hints if h in low]


async def run(url: str, *, headed: bool, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    session = await br.launch(
        user_data_dir=out_dir / "browser-profile", headless=not headed
    )
    try:
        response = await br.goto_portal(session.page, url)
        # El portal es una SPA en varias vistas: dar un respiro al render.
        await session.page.wait_for_timeout(4000)

        shot = await br.take_screenshot(session.page, out_dir / "screenshots", label="recon")
        info = await describe(session.page)
        body = info.get("bodyText", "")

        report = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "requested_url": url,
            "http_status": response.status if response else None,
            "final_url": info["url"],
            "title": info["title"],
            "screenshot": str(shot),
            "structure": info,
            "hints": {
                "captcha": find_hints(body, CAPTCHA_HINTS),
                "session": find_hints(body, SESSION_HINTS),
                "availability": find_hints(body, AVAILABILITY_HINTS),
            },
            "frames": [{"name": f.name, "url": f.url} for f in session.page.frames],
        }

        report_path = out_dir / "recon-report.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        html_path = out_dir / "recon-page.html"
        html_path.write_text(await session.page.content(), encoding="utf-8")
        report["report_path"] = str(report_path)
        report["html_path"] = str(html_path)
        return report
    finally:
        await session.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Reconocimiento del portal SAT")
    ap.add_argument("--url", default=br.SAT_CITAS_URL)
    ap.add_argument("--headed", action="store_true", help="abrir con interfaz")
    ap.add_argument("--out", default="data/recon", help="carpeta de salida")
    args = ap.parse_args()

    report = asyncio.run(run(args.url, headed=args.headed, out_dir=Path(args.out)))
    print(f"HTTP {report['http_status']} — {report['final_url']}")
    print(f"Título: {report['title']}")
    print(f"Captura: {report['screenshot']}")
    print(f"Reporte: {report['report_path']}")
    for kind, found in report["hints"].items():
        if found:
            print(f"Pistas de {kind}: {found}")


if __name__ == "__main__":
    main()
