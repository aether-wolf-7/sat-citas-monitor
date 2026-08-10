"""Selectores y rutas reales del portal de citas del SAT.

Mapeado en vivo el 2026-08-10 contra https://citas.sat.gob.mx/ (ver
`docs/portal-map.md`). Todo lo específico del portal vive aquí: cuando el SAT
cambie el maquetado, se toca este archivo y nada más.

El portal es una SPA de **Angular + Angular Material**. Regla importante para
los selectores: los atributos `_ngcontent-xxx-cNNN` cambian en cada compilación
del SAT, así que **nunca** se usan. Se prefiere, en este orden:
  1. `formcontrolname` / `id` estables  (input[formcontrolname="rfc"])
  2. rol + texto visible                (button "Registrar cita")
  3. estructura semántica               (mat-expansion-panel-header)
  4. nombre de archivo de imagen        (img[src*="menuCita"])
"""

from __future__ import annotations

# --- URLs ------------------------------------------------------------------
BASE_URL = "https://citas.sat.gob.mx/"
URL_MENU = "https://citas.sat.gob.mx/menu"
URL_DATOS_PERSONALES = "https://citas.sat.gob.mx/datosPersonales"
URL_CONSULTA_DATOS = "https://citas.sat.gob.mx/consultaCita/datosPersonales"

# Endpoints internos que consume la SPA (observados en el tráfico XHR).
# `API_CAPTCHA` es la señal más limpia de que el portal está pidiendo captcha:
# cuando se solicita, un humano tiene que resolverlo. El sistema jamás lo hace.
API_ACCOUNT = "/api/account"
API_CAPTCHA = "/api/captcha"

# --- Pantalla inicial ------------------------------------------------------
MODAL_AVISO_CERRAR = 'button:has-text("Cerrar")'
BTN_REGISTRAR_CITA = 'button:has-text("Registrar cita")'
BTN_CONSULTAR_CITA = 'button:has-text("Consultar/Gestionar cita")'

# --- /menu — tres categorías de servicio (botones sólo con imagen) ---------
CARD_SERVICIOS_GENERALES = 'button.image-button:has(img[src*="menuCita"])'
CARD_MARBETES = 'button.image-button:has(img[src*="menuMarbetes"])'
CARD_RECAUDACION = 'button.image-button:has(img[src*="menuAGR"])'

# --- /datosPersonales — opciones de trámite (paneles acordeón) ------------
PANEL_HEADER = "mat-expansion-panel-header"
PANEL_ABIERTO = "mat-expansion-panel.mat-expanded"

# Texto de cada panel. e.firma entra por "contribuyente que cuente con RFC";
# el alta de RFC entra por los paneles de inscripción.
PANEL_CON_RFC = "Contribuyente que cuente con RFC"
PANEL_INSCRIPCION_PM = "Inscripción al padrón de contribuyentes Personas Morales"
PANEL_INSCRIPCION_PF = "Inscripción al padrón de contribuyentes Personas Físicas"

# Campos del formulario (Angular reactive forms — nombres estables).
# Notas del mapeo en vivo:
#   - RFC acepta 13 caracteres, CURP 18; ambos se pasan a mayúsculas solos.
#   - En el panel "con RFC", CURP es opcional (sin asterisco).
#   - "correoconfirmacion" bloquea pegar (onpaste/oncopy/oncut = return false).
#     `fill()` de Playwright escribe el valor directo, así que sí funciona.
INPUT_RFC = 'input[formcontrolname="rfc"]'
INPUT_CORREO = 'input[formcontrolname="correo"]'
INPUT_CORREO_CONFIRMA = 'input[formcontrolname="correoconfirmacion"]'
INPUT_CURP = 'input[formcontrolname="curp"]'
INPUT_NOMBRE = 'input[formcontrolname="nombre"]'
INPUT_RAZON_SOCIAL = 'input[formcontrolname="razonSocial"]'

# Casilla de términos y condiciones: sin marcarla, "Siguiente" queda inhabilitado.
# El <input> real está oculto (cdk-visually-hidden), así que se hace clic en el
# componente de Material, no en el input.
CHECK_TERMINOS = "mat-checkbox"
CHECK_TERMINOS_INPUT = "#mat-checkbox-1-input"
URL_TERMINOS_PDF = (
    "https://www.sat.gob.mx/minisitio/DocumentosSAT/"
    "TerminosCondiciones_UsoCookies_FilaVirtual_y_ServicioOficinaVirtual.pdf"
)

BTN_SIGUIENTE = 'button:has-text("Siguiente")'
BTN_SALIR = 'button:has-text("Salir")'

# --- Captcha (imagen propia del SAT, no reCAPTCHA) ------------------------
# Lo resuelve SIEMPRE una persona (alarma 1). Estos selectores existen para
# DETECTAR que el captcha está presente, nunca para resolverlo.
CAPTCHA_INPUT = 'input[placeholder*="Captcha" i]'
CAPTCHA_IMG = 'img[src*="captcha" i], canvas'
CAPTCHA_TEXT_HINTS = ("captcha", "confirmar captcha")

# --- Señales de sesión / error --------------------------------------------
# Textos que delatan sesión caída o portal saturado. Si aparecen, NO se
# concluye "no hay citas": se dispara la alarma de sesión.
SESSION_DEAD_HINTS = (
    "sesión ha expirado",
    "sesion ha expirado",
    "la sesión expiró",
    "vuelve a intentar",
    "intenta más tarde",
    "servicio no disponible",
    "error inesperado",
)

# --- /creaCita — pantalla de disponibilidad -------------------------------
# CONFIRMADO en sesión real del 2026-08-10 (ver docs/portal-map.md).
URL_CREA_CITA = "https://citas.sat.gob.mx/creaCita"

# EL RELOJ. La pantalla de disponibilidad trae una cuenta regresiva de
# 5 minutos ("Tiempo restante para generar tu cita"). Al llegar a cero el
# portal regresa solo a la página inicial y la sesión muere. Es el hallazgo
# que define la arquitectura del proyecto: no existe una sesión larga que
# vigilar, sino ventanas de 5 minutos.
COUNTDOWN = "#timer countdown, countdown.count-down"
COUNTDOWN_CONTAINER = "#timer"
COUNTDOWN_LABEL = "Tiempo restante para generar tu cita"
SESSION_WINDOW_SECONDS = 300

# Los cuatro combos en cascada: cada uno habilita al siguiente.
# servicio -> entidad federativa -> módulo -> (calendario) -> horario
SELECT_SERVICIO = 'mat-select[name="servicio"]'
SELECT_ENTIDAD = 'mat-select[name="entidades"]'
# Módulo y Horario no traen atributo `name`; se ubican por su etiqueta, que es
# más estable que el id ordinal (mat-select-4 depende del orden de render).
SELECT_MODULO = 'mat-form-field:has(label:has-text("Módulo")) mat-select'
SELECT_HORARIO = 'mat-form-field:has(label:has-text("Horario")) mat-select'
# Las opciones de un mat-select se dibujan en un overlay fuera del formulario.
OPCION_SELECT = "mat-option .mat-option-text"

CALENDAR_ROOT = "mat-calendar"
CALENDAR_DAY = "td.mat-calendar-body-cell"
# POR CONFIRMAR: cómo se marca un día sin disponibilidad. En la captura no
# había ningún módulo seleccionado, así que ningún día estaba deshabilitado
# todavía. La hipótesis razonable es `aria-disabled="true"` / la clase
# `mat-calendar-body-disabled`, pero hay que verlo con un módulo elegido antes
# de confiar en ello.
CALENDAR_DAY_DISABLED = 'td.mat-calendar-body-cell[aria-disabled="true"]'

# NUNCA se le hace clic a esto. Existe sólo para reconocer la pantalla y para
# dejar constancia de que el sistema jamás agenda: eso lo hace una persona.
BTN_GENERAR_CITA_NO_TOCAR = 'button[type="submit"]:has-text("Generar cita")'

TEXT_SIN_CITAS_HINTS = (
    "no hay citas disponibles",
    "no existen citas",
    "sin disponibilidad",
    "no hay disponibilidad",
)  # POR CONFIRMAR: no se llegó a ver el estado vacío real
