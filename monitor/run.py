"""Punto de entrada: una corrida completa del monitor.

Es el producto, de principio a fin, tal como lo va a usar un gestor:

  1. Arranca el navegador y llega a la pantalla de identidad.
  2. Dispara la **alarma 1**: "hay que abrir la sesión" — con la liga para que
     una persona resuelva el captcha. El sistema no lo intenta ni una vez.
  3. Se queda esperando a que esa persona pase el captcha.
  4. En cuanto hay sesión viva, barre todas las oficinas activas dentro de la
     ventana de 5 minutos.
  5. Dispara la **alarma 2** por cada oficina donde sí haya lugar, con captura,
     zona, módulo, trámite y liga. Quien agenda es una persona.
  6. Deja todo registrado en SQLite: qué se miró, qué se encontró, qué se avisó.

Uso:
    python -m monitor.run --config config.json --rfc TURFC --email tu@correo
    python -m monitor.run --config config.json --plan     (no toca el portal)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from pathlib import Path

from . import alerts, browser as br, detector as D, selectors as S, storage, sweep
from .config import Config, ConfigError, Target, load_config, validate_runtime
from .mapsession import (
    TRAMITE_CON_RFC, TRAMITE_RFC_FISICA, _fill_identity, _open_tramite_panel,
)


def agrupar_por_entidad(cfg: Config) -> dict[tuple[str, str], list[Target]]:
    """Junta las oficinas activas por (zona, entidad).

    El portal encadena entidad -> módulo, así que conviene elegir la entidad
    una sola vez y de ahí recorrer todos sus módulos.
    """
    grupos: dict[tuple[str, str], list[Target]] = defaultdict(list)
    for target in cfg.targets:
        if target.enabled:
            grupos[(target.zone, target.entidad)].append(target)
    return dict(grupos)


def mostrar_plan(cfg: Config) -> None:
    """Enseña qué haría la corrida, sin tocar el portal."""
    grupos = agrupar_por_entidad(cfg)
    total = sum(len(v) for v in grupos.values())
    print(f"Plan de barrido: {total} oficina(s) en {len(grupos)} entidad(es)\n")
    for (zona, entidad), targets in grupos.items():
        destinos = cfg.telegram.destinos(zona, cfg.routing)
        print(f"  {zona} / {entidad}")
        for t in targets:
            print(f"     - {t.office}  [{', '.join(t.tramites)}]")
        print(f"     avisa a: {', '.join(destinos) if destinos else '(NADIE — revisa la config)'}")
        print()
    estimado = total * 6
    print(f"Tiempo estimado del barrido: ~{estimado}s de los "
          f"{S.SESSION_WINDOW_SECONDS}s de la ventana.")
    if estimado > S.SESSION_WINDOW_SECONDS - sweep.RESERVA_SEGUNDOS:
        print("  OJO: no cabe en una sola ventana; habrá que partirlo en varias sesiones.")


async def correr(cfg: Config, args) -> int:
    problemas = validate_runtime(cfg)
    if problemas:
        print("La configuración no está lista:")
        for p in problemas:
            print(f"  - {p}")
        if not args.forzar:
            print("\nCorrige eso o usa --forzar para seguir de todos modos.")
            return 1
        print("\n--forzar: se sigue, pero puede que las alertas no lleguen.\n")

    conn = storage.connect(cfg.storage.sqlite_path)
    grupos = agrupar_por_entidad(cfg)
    if not grupos:
        print("No hay ninguna oficina habilitada en la configuración.")
        return 1

    tramite_portal = (
        TRAMITE_RFC_FISICA if args.tramite == TRAMITE_RFC_FISICA else TRAMITE_CON_RFC
    )
    sesion = await br.launch(
        user_data_dir=args.perfil, headless=False, slow_mo=150
    )
    encontrados = 0
    try:
        page = sesion.page
        print("Abriendo el portal...")
        await _open_tramite_panel(page, tramite_portal)
        await _fill_identity(page, args)
        print("Identidad lista. El captcha lo resuelve una persona.\n")

        # --- ALARMA 1: se necesita un humano ---
        zona_principal = next(iter(grupos))[0]
        aviso = alerts.alerta_de_sesion(
            zona=zona_principal,
            motivo="hay que pasar el captcha para abrir la ventana de 5 minutos",
            liga_sesion=args.liga_sesion,
        )
        for canal, ok, detalle in await alerts.despachar(cfg, aviso, conn):
            print(f"  alarma 1 -> {canal}: {'ok' if ok else 'FALLÓ ' + detalle}")

        deteccion = await sweep.esperar_sesion_humana(
            page, timeout_segundos=args.espera
        )
        if not deteccion.can_read_availability:
            print(f"\nNo se abrió la sesión: {D.describe(deteccion)}")
            storage.log_check(
                conn, zone=zona_principal, office="(todas)", state=deteccion.state,
                detail="nadie abrió la sesión dentro del plazo",
            )
            return 2

        print(f"\nSesión viva. {D.describe(deteccion)}. Empieza el barrido.\n")

        # --- BARRIDO + ALARMA 2 ---
        for (zona, entidad), targets in grupos.items():
            for tramite in sorted({t for tg in targets for t in tg.tramites}):
                modulos = [t.office for t in targets]
                resultado = await sweep.barrer(
                    page, servicio=tramite, entidad=entidad, modulos=modulos,
                    screenshots_dir=cfg.storage.screenshots_dir,
                )
                print(f"  {zona}/{entidad} [{tramite}]: "
                      f"{len(resultado.hallazgos)} revisadas, "
                      f"{'completo' if resultado.completo else resultado.motivo_corte}")

                for h in resultado.hallazgos:
                    storage.log_check(
                        conn, zone=zona, office=h.modulo, tramite=tramite,
                        state=resultado.estado_final,
                        availability=None if h.hay_disponibilidad is None
                        else int(h.hay_disponibilidad),
                        detail=h.nota or f"días={len(h.dias)} horarios={len(h.horarios)}",
                    )
                    if h.hay_disponibilidad:
                        encontrados += 1
                        alerta = alerts.alerta_de_cita(
                            zona=zona, oficina=h.modulo, tramite=tramite,
                            dias=h.dias, horarios=h.horarios, captura=h.captura,
                        )
                        for canal, ok, det in await alerts.despachar(cfg, alerta, conn):
                            print(f"     alarma 2 -> {canal}: {'ok' if ok else 'FALLÓ ' + det}")

                # La sesión se murió a medio barrido: eso se avisa, no se calla.
                if not resultado.completo and resultado.estado_final != D.SESSION_OK:
                    corte = alerts.alerta_de_sesion(
                        zona=zona, motivo=resultado.motivo_corte,
                        liga_sesion=args.liga_sesion,
                    )
                    await alerts.despachar(cfg, corte, conn)

        print(f"\nBarrido terminado. Oficinas con lugar: {encontrados}")
        return 0
    finally:
        if not args.dejar_abierto:
            await sesion.close()
        conn.close()


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser(description="Monitor de citas SAT — una corrida")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--plan", action="store_true", help="sólo enseña el plan, no abre el portal")
    ap.add_argument("--rfc", default="")
    ap.add_argument("--curp", default="")
    ap.add_argument("--nombre", default="")
    ap.add_argument("--razon-social", default="")
    ap.add_argument("--email", default="")
    ap.add_argument("--tramite", default=TRAMITE_CON_RFC)
    ap.add_argument("--espera", type=int, default=600,
                    help="segundos a esperar a que una persona pase el captcha")
    ap.add_argument("--liga-sesion", default="",
                    help="liga noVNC que se manda en la alarma 1 (paso 8)")
    ap.add_argument("--perfil", default="data/run-profile")
    ap.add_argument("--dejar-abierto", action="store_true")
    ap.add_argument("--forzar", action="store_true",
                    help="arrancar aunque la config tenga problemas")
    args = ap.parse_args()

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"Configuración inválida: {exc}")
        raise SystemExit(1)

    if args.plan:
        mostrar_plan(cfg)
        raise SystemExit(0)

    if not args.email:
        ap.error("--email es obligatorio: el portal lo exige")
    if args.tramite == TRAMITE_RFC_FISICA and not (args.curp and args.nombre):
        ap.error("inscripción persona física requiere --curp y --nombre")
    if args.tramite == TRAMITE_CON_RFC and not args.rfc:
        ap.error("este trámite requiere --rfc")

    raise SystemExit(asyncio.run(correr(cfg, args)))


if __name__ == "__main__":
    main()
