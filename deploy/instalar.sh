#!/usr/bin/env bash
# Instalación del monitor de citas SAT en un VPS Ubuntu 22.04.
#
# Se puede correr varias veces sin romper nada: sólo instala lo que falte.
#
#   sudo bash deploy/instalar.sh
#
# Deja listo:
#   - Python + entorno virtual con Playwright y Chromium
#   - Xvfb + x11vnc + noVNC, para que una persona resuelva el captcha
#     desde el celular viendo SÓLO el navegador (nunca un escritorio real)
#   - El usuario de servicio y las carpetas de datos
set -euo pipefail

APP_USER="${APP_USER:-satmon}"
APP_DIR="${APP_DIR:-/opt/sat-citas-monitor}"

log() { echo -e "\n=== $* ==="; }

if [[ $EUID -ne 0 ]]; then
  echo "Corre esto con sudo." >&2
  exit 1
fi

log "Paquetes del sistema"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
  python3 python3-venv python3-pip \
  xvfb x11vnc novnc websockify \
  curl ca-certificates git \
  fonts-liberation fonts-noto-color-emoji \
  >/dev/null
echo "listo"

log "Usuario de servicio: ${APP_USER}"
# Usuario sin shell ni contraseña: si alguien se cuela por el navegador, no
# encuentra una cuenta usable esperándolo.
if ! id -u "${APP_USER}" >/dev/null 2>&1; then
  useradd --system --create-home --shell /usr/sbin/nologin "${APP_USER}"
  echo "creado"
else
  echo "ya existía"
fi

log "Carpetas en ${APP_DIR}"
mkdir -p "${APP_DIR}"/{data,screenshots,logs}
chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"
echo "listo"

log "Entorno virtual de Python"
if [[ ! -d "${APP_DIR}/.venv" ]]; then
  python3 -m venv "${APP_DIR}/.venv"
fi
"${APP_DIR}/.venv/bin/pip" install --quiet --upgrade pip
echo "python: $("${APP_DIR}/.venv/bin/python" --version)"

log "Dependencias de Python"
"${APP_DIR}/.venv/bin/pip" install --quiet playwright httpx
echo "listo"

log "Chromium para Playwright (esto tarda: son ~150 MB)"
"${APP_DIR}/.venv/bin/playwright" install --with-deps chromium 2>&1 | tail -3
chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"
# Playwright guarda el navegador en el HOME de quien lo instala; el usuario de
# servicio necesita poder leerlo.
if [[ -d /root/.cache/ms-playwright ]]; then
  mkdir -p "/home/${APP_USER}/.cache"
  cp -r /root/.cache/ms-playwright "/home/${APP_USER}/.cache/" 2>/dev/null || true
  chown -R "${APP_USER}:${APP_USER}" "/home/${APP_USER}/.cache"
fi

log "Comprobaciones"
echo -n "  Xvfb:      "; command -v Xvfb || echo FALTA
echo -n "  x11vnc:    "; command -v x11vnc || echo FALTA
echo -n "  websockify:"; command -v websockify || echo FALTA
echo -n "  noVNC:     "; [[ -d /usr/share/novnc ]] && echo /usr/share/novnc || echo FALTA
echo -n "  chromium:  "; ls "/home/${APP_USER}/.cache/ms-playwright" 2>/dev/null | head -1 || echo "(revisar)"

log "Instalación terminada"
echo "Sigue: copiar el código a ${APP_DIR} y crear config.json"
