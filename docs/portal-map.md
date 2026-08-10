# Mapa del portal de citas del SAT

Reconocimiento en vivo contra `https://citas.sat.gob.mx/` — **2026-08-10**.
Solo navegación pública de lectura: no se envió ningún formulario, no se tocó
el captcha, no se agendó nada.

## Tecnología del portal

SPA en **Angular + Angular Material**, servida desde `citas.sat.gob.mx`.
El encabezado y el pie son iframes de `www.sat.gob.mx` (irrelevantes para el
monitoreo).

Consecuencia práctica para los selectores: Angular marca el DOM con atributos
tipo `_ngcontent-kaa-c163`, **que cambian en cada compilación del SAT**. Usarlos
sería garantizar que el monitor se rompa sin aviso. Por eso `monitor/selectors.py`
se apoya en `formcontrolname`, `id`, rol + texto visible y estructura semántica.

## Flujo mapeado

| # | Pantalla | URL | Qué hay |
|---|---|---|---|
| 1 | Inicio | `/` | Modal "Aviso Importante" (botón **Cerrar**) + botones **Registrar cita** y **Consultar/Gestionar cita** |
| 2 | Menú | `/menu` | "Selecciona tu cita" — 3 tarjetas sólo con imagen: Servicios Generales (`menuCita.png`), Marbetes y Precintos (`menuMarbetes.png`), Recaudación/Auditoría/Comercio Exterior (`menuAGR.png`) |
| 3 | Datos personales | `/datosPersonales` | "Opciones de trámite" — 3 paneles acordeón (ver abajo) |
| 4 | Captcha + disponibilidad | *(tras "Siguiente")* | **Sin mapear** — ver §Bloqueo |

### Paneles de trámite en `/datosPersonales`

| Panel | Campos que exige | Trámite del proyecto |
|---|---|---|
| Contribuyente que cuente con RFC | RFC (13), CURP *(opcional)*, correo, confirmar correo | **e.firma** (y demás trámites de quien ya tiene RFC) |
| Inscripción al padrón — Personas Morales | RFC del representante legal, razón social, correo, confirmar correo, ¿inscrito en SIGER? | **RFC** (moral) |
| Inscripción al padrón — Personas Físicas | CURP (18), nombre completo, correo, confirmar correo | **RFC** (física) |

Detalles del formulario, comprobados en vivo:

- Hay una **casilla obligatoria** de términos y condiciones + aviso de privacidad.
  Sin marcarla, "Siguiente" queda inhabilitado.
- RFC y CURP se convierten solos a mayúsculas; el campo de confirmar correo
  **bloquea pegar** (`onpaste="return false"`), hay que escribirlo.
- El captcha **no** está en esta pantalla: aparece después de "Siguiente".

### Endpoints internos observados (tráfico XHR de la propia SPA)

- `GET /api/account` — estado de sesión del front.
- `GET /api/captcha` — **entrega la imagen del captcha**. Es la señal más limpia
  para detectar "el portal está pidiendo captcha" → alarma 1.
- `GET /content/json/tc_menu.json` — catálogo de trámites que se pueden hacer en
  línea (no es el catálogo de oficinas).

## El captcha

Es un **captcha de imagen propio del SAT**, no reCAPTCHA ni hCaptcha: texto
distorsionado a color con botón de refrescar y un campo "Confirmar Captcha".
Se sirve desde `/api/captcha`.

Esto **confirma el modelo de dos alarmas**: no existe forma legal de que el
sistema lo resuelva, así que lo resuelve una persona y el monitor solo vigila
dentro de la sesión que esa persona abrió. El código de `selectors.py` referido
al captcha existe únicamente para **detectarlo**, jamás para resolverlo.

## Bloqueo: la disponibilidad está detrás de identidad + captcha

El hallazgo más importante del reconocimiento:

> El portal **no muestra disponibilidad de citas a un visitante anónimo**. Para
> llegar a la pantalla de oficinas y calendario hay que enviar antes datos
> personales reales (RFC o CURP + nombre + correo) y resolver el captcha.

Implicaciones que hay que resolver con el cliente antes de poder terminar los
pasos 3 y 4:

1. **Se necesitan datos reales para vigilar.** El monitor tiene que operar
   dentro de una sesión abierta con un RFC/CURP y un correo verdaderos. El
   cliente debe decidir con qué identidad se abre esa sesión y autorizarlo por
   escrito.
2. **Datos personales en el servidor.** Esos datos viven en `config.json`
   (fuera de git) y en el perfil del navegador. Conviene dejar por escrito
   quién los proporciona y para qué se usan (LFPDPPP).
3. **La sesión es aún más valiosa de lo previsto.** Cada reapertura cuesta
   intervención humana, así que el navegador usa perfil persistente
   (`monitor/browser.py`) para que la sesión sobreviva reinicios.
4. **El aviso del propio SAT.** La página inicial advierte que los servicios
   son gratuitos y que "ninguna persona, asociación o gestor" puede cobrar por
   agendar una cita. No afecta la legalidad del software —que solo detecta y
   avisa— pero es un punto que el cliente debe conocer, porque su operación es
   con gestores. Los términos y condiciones van más lejos y nombran de forma
   expresa la gestoría y el "acaparamiento de citas por parte de terceras
   personas": ver **`docs/terminos-sat.md`**, que hay que leer antes de
   prometerle al cliente que todo está 100 % en regla.

## Qué falta mapear (requiere sesión abierta por un humano)

- Pantalla de selección de oficina/módulo → confirmar cómo aparece Cancún y
  cómo se listan las oficinas de CDMX.
- Calendario de disponibilidad → selector exacto de día/hora disponible y el
  texto real de "no hay citas".
- El **selector ancla de sesión viva**: el elemento que existe únicamente
  cuando de verdad estamos en la pantalla de disponibilidad. Es la pieza que
  evita el falso "cero citas" que preocupa al cliente.

Mientras tanto, los selectores marcados `POR CONFIRMAR` en `selectors.py` son
hipótesis, no verdades.

## Cómo repetir el reconocimiento

```bash
python -m monitor.recon                 # headless, guarda captura + JSON + HTML
python -m monitor.recon --headed        # con interfaz, para mirarlo en vivo
python -m monitor.recon --out data/recon
```
