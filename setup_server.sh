#!/usr/bin/env bash
# =========================================================================
# Instalacion del bot de monitoreo OLT en un servidor Ubuntu
# (Oracle Cloud Always Free, o cualquier VPS con Ubuntu 22.04 / 24.04)
#
# Uso:
#   sudo bash setup_server.sh https://github.com/TU_USUARIO/TU_REPO.git
#
# Es idempotente: se puede volver a ejecutar para reparar o actualizar.
# =========================================================================
set -euo pipefail

REPO="${1:-}"
APP_DIR="/opt/monitorolt"
RUN_USER="monitor"
SERVICE="monitorolt"

if [ "$(id -u)" != "0" ]; then
  echo "Ejecutalo con root:  sudo bash setup_server.sh <url-del-repo>"
  exit 1
fi

echo "== 1/7 Paquetes base =="
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-venv python3-pip python3-dev git curl ca-certificates

echo "== 2/7 Usuario de servicio =="
if ! id -u "$RUN_USER" >/dev/null 2>&1; then
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$RUN_USER"
fi

echo "== 3/7 Codigo =="
if [ -d "$APP_DIR/.git" ]; then
  BRANCH=$(git -C "$APP_DIR" rev-parse --abbrev-ref HEAD)
  git -C "$APP_DIR" fetch origin
  git -C "$APP_DIR" reset --hard "origin/$BRANCH"
elif [ -n "$REPO" ]; then
  rm -rf "$APP_DIR"
  git clone "$REPO" "$APP_DIR"
else
  echo "No hay codigo en $APP_DIR y no pasaste la URL del repositorio."
  echo "Uso: sudo bash setup_server.sh https://github.com/TU_USUARIO/TU_REPO.git"
  exit 1
fi

echo "== 4/7 Entorno virtual y dependencias Python =="
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "== 5/7 Chromium para Playwright =="
export PLAYWRIGHT_BROWSERS_PATH="$APP_DIR/.pw-browsers"
mkdir -p "$PLAYWRIGHT_BROWSERS_PATH"
"$APP_DIR/.venv/bin/playwright" install --with-deps chromium

echo "== 6/7 Credenciales (.env) =="
if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  echo "  ⚠ Se creo $APP_DIR/.env con valores de ejemplo."
  echo "    Editalo antes de confiar en el bot:"
  echo "      sudo nano $APP_DIR/.env"
fi
chmod 600 "$APP_DIR/.env"
chown -R "$RUN_USER":"$RUN_USER" "$APP_DIR"

echo "== 7/7 Servicio systemd =="
install -m 644 "$APP_DIR/deploy/monitorolt.service" "/etc/systemd/system/${SERVICE}.service"
systemctl daemon-reload
systemctl enable "$SERVICE"
systemctl restart "$SERVICE" || true

cat <<FIN

Instalacion terminada.

Si aun no editaste el .env, hacelo ahora y reinverti el servicio:
  sudo nano $APP_DIR/.env
  sudo systemctl restart $SERVICE

Comandos utiles:
  systemctl status $SERVICE          # estado y ultimo log
  journalctl -u $SERVICE -f          # ver el bot en vivo
  journalctl -u $SERVICE --since -1h # ultima hora

FIN
