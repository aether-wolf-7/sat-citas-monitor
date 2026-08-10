# Términos y condiciones del SAT — lo que afecta a este proyecto

Documento oficial enlazado desde la casilla obligatoria del formulario de citas:
`TerminosCondiciones_UsoCookies_FilaVirtual_y_ServicioOficinaVirtual.pdf`
(7 páginas, revisado el **2026-08-10**).

Se resume aquí porque el requisito del cliente es explícito: **100 % legal, sin
violar los términos del portal**. Esto no es asesoría legal; es lo que dice el
documento, con la cita textual para que el cliente y su abogado decidan.

## 1. El punto que toca directamente el modelo de negocio

De "Consideraciones de la Fila Virtual", inciso a):

> "El Servicio de Administración Tributaria (SAT) se reserva la permanencia en
> la Fila Virtual para solicitudes de contribuyentes que se identifiquen con
> **actos de gestión de negocios** a que se refiere el artículo 19 del Código
> Fiscal de la Federación **o acaparamiento de citas por parte de terceras
> personas**."

El inciso e) aclara que aplican también "todos los términos, condiciones y
políticas... vigentes para el aplicativo **CitaSAT**", que es justamente el
portal que vigila este sistema.

Es decir: el SAT nombra de forma expresa dos conductas —la gestoría de negocios
y el acaparamiento de citas por terceros— y se reserva el derecho de actuar
contra ellas. **Esto no habla del software, habla de cómo se usen las citas.**

## 2. Límite de frecuencia

Inciso b): sólo se puede solicitar la asignación de una cita mediante esa
facilidad **una vez cada 15 días naturales**.

## 3. Datos verdaderos, del propio titular

El usuario "se compromete a proporcionar los datos e información necesaria...
misma que se considerará **verdadera, exacta, completa y actualizada**,
incluyendo los datos relativos a su identidad".

Para registrar la cita el portal pide: RFC **o** CURP, nombre completo, correo
personal y tipo de servicio. Consecuencia práctica: **no se vale inventar datos
ni usar la identidad de alguien más sin su autorización**. Quien abra la sesión
tiene que ser un titular real y consciente de ello.

## 4. La cláusula sobre software

> "El USUARIO por ningún motivo podrá utilizar dispositivos, software,
> complementos, malware o cualquier otro medio **tendiente a interferir** tanto
> en las actividades u operaciones de la Oficina Virtual."

La prohibición está redactada sobre la **interferencia**. Un monitor que sólo
lee disponibilidad, a ritmo de usuario humano, sin resolver captcha y sin
agendar, no interfiere en la operación del portal. Aun así es una redacción
amplia y la lectura final no la hace un desarrollador.

De ahí que el diseño ya acordado —detectar y avisar, humano en el captcha,
humano en el agendado, cadencia espaciada— sea también la postura más defendible
frente a esta cláusula.

## 5. Obligaciones generales

- Usar el servicio "únicamente para fines lícitos o en forma diligente y
  correcta" y conforme a un "uso correcto de buena fe o racional".
- El SAT "se reserva el derecho de expulsar o dar por terminados los servicios...
  sin previo aviso" si no se respetan los términos, y puede "interrumpir,
  desactivar o cancelar" el acceso en cualquier momento.

## Qué implica para el sistema

Lo que se construye —detectar disponibilidad y avisar a una persona— es una
herramienta de monitoreo. El punto 1 no cuestiona el software: cuestiona el uso
de citas por terceros. Esa parte es decisión y responsabilidad del cliente, y
conviene que la tome informado y por escrito, no de sobremesa.

Lo que sí queda del lado técnico, y ya está en el diseño:

- Cadencia responsable (mínimo 20 s, con jitter) — nada de martilleo.
- Cero resolución de captcha, cero agendado automático.
- Sesión abierta por una persona real con sus propios datos y su consentimiento.
- Registro completo en SQLite de cada consulta, por si alguna vez hay que
  demostrar cómo se comportó el sistema.
