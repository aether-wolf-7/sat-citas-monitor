# Cómo opera el sistema (modelo definitivo)

Dos hechos, uno del portal y otro del cliente, definen toda la operación:

1. **La ventana dura 5 minutos** y sólo la abre una persona resolviendo el
   captcha (ver `portal-map.md`).
2. **No hay horario fijo.** El cliente lo dijo claro el 2026-08-13: "habrá
   semanas que no tendremos la necesidad de cazar citas y épocas que
   necesitaremos tomar muchas... podemos conectarnos también muchas veces al
   día". Trabajan por demanda, a ráfagas.

De ahí sale el modelo: **el sistema no persigue al portal, espera al gestor.**

## Lo que se descartó y por qué

- **Monitoreo continuo 24/7.** Imposible sin resolver captchas cada 5 minutos
  (~288 al día por oficina). Automatizarlos está prohibido por el cliente y
  chocaría con los términos del SAT.
- **Barridos programados por horario.** Era el plan B, y también se cae: no
  sirve programar las 8, la 1 y las 6 si hay semanas enteras sin necesidad y
  días con diez búsquedas. Mandaría avisos que nadie va a atender, y el aviso
  que se ignora por costumbre deja de ser aviso.

## El modelo que sí aplica: a demanda

1. El gestor le escribe al bot desde el celular cuando quiere buscar.
2. El sistema abre el navegador en el servidor y le regresa una liga (noVNC).
3. El gestor abre la liga, ve el portal en vivo y **resuelve el captcha él**.
4. En cuanto el reloj aparece, el sistema barre las 11 oficinas en ~1 minuto.
5. Regresa por Telegram y WhatsApp: dónde hay lugar, qué días, qué horarios,
   con captura y liga. **Quien agenda es el gestor.**

Ventajas que no son casualidad, sino consecuencia de respetar los dos hechos:

- Cuesta cero cuando no se usa. Semanas sin buscar = servidor en reposo.
- Se puede usar diez veces en un día sin cambiarle nada.
- Cada sesión la abre una persona con sus datos y su consentimiento, que es
  justo lo que exigen los términos del SAT.
- El captcha nunca lo toca el sistema.

## Qué implica para el código

- El paso 7 deja de ser "programador de barridos" y pasa a ser **disparador a
  demanda**: un bot de Telegram escuchando un comando.
- El paso 8 (Xvfb + noVNC) sube de prioridad: es la superficie que el gestor
  toca **cada vez**, desde el celular. Si se siente lento o incómodo, el
  producto no se usa. Es el punto donde más cuidado hay que poner.
- El watchdog cambia de sentido: ya no vigila silencio del portal (no hay nada
  corriendo entre sesión y sesión), sino que una sesión pedida no se quede
  colgada sin respuesta.
