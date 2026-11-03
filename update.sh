#!/usr/bin/env bash
# Actualiza el bot desde GitHub y reinicia el servicio.
# Lo invoca el workflow de despliegue, o lo puedes correr a mano:
#   sudo bash /opt/monitorolt/update.sh
set -euo pipefail

APP_DIR="/opt/monitorolt"
SERVICE="monitorolt"

if [ "$(id -u)" != "0" ]; then
  echo "Ejecutalo con root:  sudo bash $0"
  exit 1
fi

cd "$APP_DIR"
git fetch origin
git reset --hard "origin/$(git rev-parse --abbrev-ref HEAD)"

"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

# Reinicio planificado: el bot sale en silencio, sin avisar una falsa incidencia.
systemctl restart "$SERVICE"

sleep 3
systemctl --no-pager -l status "$SERVICE" | head -12
