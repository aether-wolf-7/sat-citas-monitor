"""Barrido automático de disponibilidad dentro de la ventana de 5 minutos.

Éste es el corazón del producto, ya ajustado a cómo se comporta el portal de
verdad: la persona abre la puerta una sola vez (resuelve el captcha) y a partir
de ahí el sistema recorre solo todas las combinaciones de entidad, módulo y
servicio que le pidan, guarda capturas y registra lo que encontró.

Lo que a una persona le llevaría varios minutos de clics —y no alcanzaría a
terminar antes de que expire el reloj— aquí toma segundos.

Límites que respeta:
  - Vuelve a mirar el reloj antes de cada combinación y se detiene con margen;
    nunca deja el barrido a medias sin avisar.
  - Si la sesión se cae, **no** reporta "no hay citas": reporta sesión caída.
  - Jamás toca el botón "Generar cita". Agendar es de una persona.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from playwright.async_api import Page

from . import browser as br
from . import detector as D
from . import selectors as S

# Margen que se reserva para no quedar a medias cuando el reloj se agota.
RESERVA_SEGUNDOS = 25


@dataclass
class Hallazgo:
    """Lo que se vio para una combinación concreta."""

    entidad: str
    modulo: str
    servicio: str
    hay_disponibilidad: bool | None  # None = no se pudo determinar
    dias: list[str] = field(default_factory=list)
    dias_bloqueados: list[str] = field(default_factory=list)
    horarios: list[str] = field(default_factory=list)
    captura: str | None = None
    nota: str = ""


@dataclass
class ResultadoBarrido:
    hallazgos: list[Hallazgo] = field(default_factory=list)
    completo: bool = False
    motivo_corte: str = ""
    estado_final: str = ""
    # Lo que el portal ofreció de verdad. Sirve para cuadrar los nombres que
    # nos dio el cliente contra los que realmente usa el SAT.
    servicios_ofrecidos: list[str] = field(default_factory=list)
    entidades_ofrecidas: list[str] = field(default_factory=list)
    modulos_ofrecidos: list[str] = field(default_factory=list)


async def _sin_velo(page: Page, *, timeout_ms: int = 8_000) -> None:
    """Espera a que se quite el velo que Material deja al cerrar un combo.

    Angular Material tapa la página con un `cdk-overlay-backdrop` mientras
    abre y cierra sus desplegables. El velo es invisible pero se come los
    clics: el primer barrido real contra el portal murió justo así, tratando
    de abrir el combo de entidad mientras seguía puesto el del servicio.

    Esperar a que desaparezca es la condición de verdad; dormir un rato fijo
    sólo funciona hasta que el servidor tarda un poco más.
    """
    try:
        await page.wait_for_function(
            "() => document.querySelectorAll('.cdk-overlay-backdrop-showing').length === 0",
            timeout=timeout_ms,
        )
    except Exception:
        # Último recurso: cerrar a mano y seguir.
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(400)


async def _opciones_de(page: Page, select_sel: str, *, timeout_ms: int = 10_000) -> list[str]:
    """Abre un combo de Angular Material y devuelve el texto de sus opciones.

    Las opciones se dibujan en un overlay aparte del formulario, por eso hay
    que abrirlo para poder leerlas.
    """
    await _sin_velo(page)
    combo = page.locator(select_sel).first
    await combo.wait_for(state="visible", timeout=timeout_ms)
    if "mat-select-disabled" in (await combo.get_attribute("class") or ""):
        return []
    await combo.click(timeout=timeout_ms)
    try:
        await page.locator(S.OPCION_SELECT).first.wait_for(state="visible", timeout=timeout_ms)
    except Exception:
        await page.keyboard.press("Escape")
        await _sin_velo(page)
        return []
    textos = [t.strip() for t in await page.locator(S.OPCION_SELECT).all_inner_texts()]
    await page.keyboard.press("Escape")
    await _sin_velo(page)
    return [t for t in textos if t]


async def _elegir(page: Page, select_sel: str, texto: str, *, timeout_ms: int = 10_000) -> bool:
    """Selecciona una opción por su texto. Devuelve si lo logró.

    Nunca revienta: si no encuentra la opción devuelve False y quien llama
    decide. En un barrido de 11 oficinas, que una falle no puede tumbar todo.
    """
    try:
        await _sin_velo(page)
        combo = page.locator(select_sel).first
        await combo.wait_for(state="visible", timeout=timeout_ms)
        await combo.click(timeout=timeout_ms)

        opcion = page.locator("mat-option").filter(has_text=texto).first
        await opcion.wait_for(state="visible", timeout=timeout_ms)
        await opcion.click(timeout=timeout_ms)
    except Exception:
        try:
            await page.keyboard.press("Escape")
            await _sin_velo(page)
        except Exception:
            pass
        return False

    # Cerrar el desplegable deja el velo puesto un momento; hay que esperarlo
    # antes de tocar el siguiente combo, que además se habilita por una
    # llamada al servidor.
    await _sin_velo(page)
    return True


async def _leer_calendario(page: Page) -> tuple[list[str], list[str]]:
    """Devuelve (días ofrecidos, días bloqueados) del calendario visible.

    OJO: cómo marca el portal un día sin disponibilidad está **sin confirmar**
    (nunca se llegó a ver un módulo elegido). Por eso se reportan las dos
    listas en crudo en vez de decidir por adelantado: la primera corrida real
    nos dirá cuál es la buena, y mientras tanto el dato no se inventa.
    """
    celdas = page.locator(S.CALENDAR_DAY)
    total = await celdas.count()
    libres: list[str] = []
    bloqueados: list[str] = []
    for i in range(total):
        celda = celdas.nth(i)
        try:
            texto = (await celda.inner_text()).strip()
            deshabilitado = (await celda.get_attribute("aria-disabled")) == "true"
            clase = await celda.get_attribute("class") or ""
            if deshabilitado or "mat-calendar-body-disabled" in clase:
                bloqueados.append(texto)
            else:
                libres.append(texto)
        except Exception:
            continue
    return libres, bloqueados


async def barrer(
    page: Page,
    *,
    servicio: str,
    entidad: str,
    modulos: list[str] | None = None,
    screenshots_dir: str | Path = "data/sweep",
    reserva_segundos: int = RESERVA_SEGUNDOS,
) -> ResultadoBarrido:
    """Recorre los módulos pedidos para un servicio y entidad dados.

    Si `modulos` es None, barre todos los que ofrezca el portal para esa
    entidad — que es justo la lista que el cliente todavía no nos ha dado.
    """
    resultado = ResultadoBarrido()

    deteccion = await D.detect(page)
    resultado.estado_final = deteccion.state
    if not deteccion.can_read_availability:
        resultado.motivo_corte = f"no hay sesión viva: {D.describe(deteccion)}"
        return resultado

    # Se lee la lista antes de elegir: si el nombre configurado no existe,
    # queremos poder decir exactamente qué sí ofrece el portal en vez de un
    # "no se pudo" a secas.
    resultado.servicios_ofrecidos = await _opciones_de(page, S.SELECT_SERVICIO)
    if not await _elegir(page, S.SELECT_SERVICIO, servicio):
        resultado.motivo_corte = (
            f"no se pudo elegir el servicio '{servicio}'. El portal ofrece: "
            f"{resultado.servicios_ofrecidos or '(nada)'}"
        )
        return resultado

    resultado.entidades_ofrecidas = await _opciones_de(page, S.SELECT_ENTIDAD)
    if not await _elegir(page, S.SELECT_ENTIDAD, entidad):
        resultado.motivo_corte = (
            f"no se pudo elegir la entidad '{entidad}'. El portal ofrece: "
            f"{resultado.entidades_ofrecidas or '(nada)'}"
        )
        return resultado

    disponibles = await _opciones_de(page, S.SELECT_MODULO)
    resultado.modulos_ofrecidos = disponibles
    objetivo = modulos or disponibles
    if not objetivo:
        resultado.motivo_corte = "el portal no ofreció ningún módulo para esa entidad"
        return resultado

    for modulo in objetivo:
        deteccion = await D.detect(page)
        resultado.estado_final = deteccion.state
        if not deteccion.can_read_availability:
            resultado.motivo_corte = f"la sesión se cayó a medio barrido: {D.describe(deteccion)}"
            return resultado

        restante = deteccion.seconds_left or 0
        if restante <= reserva_segundos:
            resultado.motivo_corte = (
                f"se acabó la ventana: quedaban {restante}s y faltaban "
                f"{len(objetivo) - len(resultado.hallazgos)} módulos"
            )
            return resultado

        # Cada módulo se aísla: si uno falla, se anota y se sigue con los
        # demás. Perder un barrido completo de 11 oficinas porque una se
        # atoró sería justo lo contrario de lo que necesita el cliente.
        try:
            if not await _elegir(page, S.SELECT_MODULO, modulo):
                resultado.hallazgos.append(
                    Hallazgo(
                        entidad, modulo, servicio, None,
                        nota=f"no aparece en el portal; ofrece: {disponibles or '(nada)'}",
                    )
                )
                continue

            libres, bloqueados = await _leer_calendario(page)
            horarios = await _opciones_de(page, S.SELECT_HORARIO)
            captura = await br.take_screenshot(
                page, screenshots_dir, label=f"{entidad}-{modulo}"[:60]
            )

            # Sólo se afirma que hay disponibilidad si de verdad se vio un
            # horario ofrecido. Un calendario con días "libres" pero sin
            # horarios no basta para decirle a alguien que corra a agendar.
            hay = bool(horarios) if horarios or bloqueados else None
            resultado.hallazgos.append(
                Hallazgo(
                    entidad=entidad, modulo=modulo, servicio=servicio,
                    hay_disponibilidad=hay, dias=libres, dias_bloqueados=bloqueados,
                    horarios=horarios, captura=str(captura),
                    nota="" if hay is not None
                    else "calendario sin señales claras (por confirmar)",
                )
            )
        except Exception as exc:
            resultado.hallazgos.append(
                Hallazgo(
                    entidad, modulo, servicio, None,
                    nota=f"error al revisar este módulo: {type(exc).__name__}: {exc}"[:300],
                )
            )
            continue

    resultado.completo = True
    return resultado


async def esperar_sesion_humana(
    page: Page, *, timeout_segundos: int = 600, intervalo: float = 2.0
) -> D.Detection:
    """Espera a que una persona resuelva el captcha y llegue a la pantalla de citas.

    El sistema no resuelve el captcha ni lo intenta: nada más se queda mirando
    hasta que el reloj de la pantalla de disponibilidad aparece.
    """
    transcurrido = 0.0
    ultimo = ""
    while transcurrido < timeout_segundos:
        deteccion = await D.detect(page)
        if deteccion.state != ultimo:
            ultimo = deteccion.state
            print(f"  [portal] {D.describe(deteccion)}", flush=True)
        if deteccion.can_read_availability:
            return deteccion
        await asyncio.sleep(intervalo)
        transcurrido += intervalo
    return await D.detect(page)
