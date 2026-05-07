#!/usr/bin/env bash
set -euo pipefail

APP_NAME="spotpi"
APP_USER="spotpi"
PURGE="${1:-}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo scripts/uninstall.sh" >&2
  exit 1
fi

systemctl disable --now "${APP_NAME}.service" >/dev/null 2>&1 || true
systemctl disable --now "${APP_NAME}-librespot.service" >/dev/null 2>&1 || true
rm -f "/etc/systemd/system/${APP_NAME}.service"
rm -f "/etc/systemd/system/${APP_NAME}-librespot.service"
rm -f "/etc/sudoers.d/${APP_NAME}"
systemctl daemon-reload

rm -rf "/opt/${APP_NAME}"

if [[ "${PURGE}" == "--purge" ]]; then
  rm -rf "/etc/${APP_NAME}" "/var/cache/${APP_NAME}" "/var/lib/${APP_NAME}"
  userdel "${APP_USER}" >/dev/null 2>&1 || true
fi

echo "Uninstalled ${APP_NAME}."
