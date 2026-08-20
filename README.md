# sat-citas-monitor

Monitor 24/7 de disponibilidad de citas del SAT con alertas instantáneas
(WhatsApp / Telegram / correo).

**El sistema únicamente detecta y alerta.** Nunca agenda citas, nunca resuelve
ni evade captchas, nunca manipula el portal del SAT. Las dos acciones sensibles
las realiza siempre una persona (modelo de dos alarmas):

1. **Alarma de sesión/captcha** — el sistema detecta que la sesión expiró o que
   apareció un captcha, y avisa para que un gestor abra la sesión a mano.
2. **Alarma de cita** — con la sesión viva, si aparece disponibilidad para el
   trámite objetivo, avisa con captura de pantalla y liga directa para que un
   gestor agende a mano.

Cada alerta indica: **SAT (Cancún o CDMX)** + **módulo/oficina** + **trámite
(RFC o e.firma)** + **captura** + **liga directa**.

## Arquitectura

- **Python 3.10+ / Playwright** (Chromium): carga el portal, valida por
  selectores que la pantalla de disponibilidad realmente está viva antes de
  decidir "no hay citas", detecta estado de sesión/captcha y toma capturas.
- **Heartbeat / watchdog:** el silencio nunca significa "no hay citas";
  si pasa demasiado tiempo sin una lectura válida, se alerta.
- **Alertas:** Telegram (Bot API), correo (SMTP) y WhatsApp no oficial vía un
  bridge en Node (una sesión compartida — por eso Telegram corre como respaldo
  en paralelo).
- **Almacenamiento:** SQLite (historial de chequeos/detecciones) + JSON (config).
- **Operación 24/7:** Ubuntu VPS + systemd (reinicio automático). Para el
  traspaso de captcha: Chromium con interfaz dentro de Xvfb expuesto por noVNC,
  para que el gestor resuelva el captcha en vivo desde una liga.

## Estructura

```
monitor/    # motor en Python (detección, alarmas, polling)
bridge/     # bridge de WhatsApp en Node (Baileys)
deploy/     # scripts de despliegue, unidad systemd
docs/       # manual de instalación y de usuario
```

## Configuración

Copia `config.example.json` a `config.json` y llena tokens, destinos y
oficinas. `config.json`, `.env`, la base de datos y las capturas **no** se
versionan.
