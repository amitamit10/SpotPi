#!/usr/bin/env bash
set -euo pipefail

APP_NAME="pi-connect-speaker"
APP_USER="pi-connect-speaker"
INSTALL_DIR="/opt/${APP_NAME}"
CONFIG_DIR="/etc/${APP_NAME}"
CACHE_DIR="/var/cache/${APP_NAME}"
DATA_DIR="/var/lib/${APP_NAME}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LIBRESPOT_INSTALL_MODE="${LIBRESPOT_INSTALL_MODE:-auto}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo scripts/install.sh" >&2
  exit 1
fi

apt_install() {
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y "$@"
}

ensure_user() {
  if ! id "${APP_USER}" >/dev/null 2>&1; then
    useradd --system --home "${DATA_DIR}" --shell /usr/sbin/nologin "${APP_USER}"
  fi
  usermod -aG audio "${APP_USER}"
  if getent group systemd-journal >/dev/null 2>&1; then
    usermod -aG systemd-journal "${APP_USER}"
  fi
}

install_librespot() {
  if command -v librespot >/dev/null 2>&1; then
    return
  fi

  if [[ "${LIBRESPOT_INSTALL_MODE}" == "existing" ]]; then
    echo "librespot is not installed and LIBRESPOT_INSTALL_MODE=existing" >&2
    exit 1
  fi

  if [[ "${LIBRESPOT_INSTALL_MODE}" == "auto" || "${LIBRESPOT_INSTALL_MODE}" == "apt" ]]; then
    if apt-cache show librespot >/dev/null 2>&1; then
      apt_install librespot
      return
    fi
    if [[ "${LIBRESPOT_INSTALL_MODE}" == "apt" ]]; then
      echo "No librespot apt package is available on this system" >&2
      exit 1
    fi
  fi

  apt_install build-essential pkg-config libasound2-dev libssl-dev curl ca-certificates
  if [[ ! -x "${HOME}/.cargo/bin/cargo" ]]; then
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
  fi
  # shellcheck disable=SC1091
  . "${HOME}/.cargo/env"
  cargo install librespot --locked --no-default-features --features "native-tls alsa-backend with-libmdns"
  install -m 0755 "${HOME}/.cargo/bin/librespot" /usr/local/bin/librespot
}

install_app() {
  apt_install python3 python3-venv python3-pip alsa-utils avahi-daemon sudo curl ca-certificates
  ensure_user

  install -d -m 0755 "${INSTALL_DIR}" "${CONFIG_DIR}" "${DATA_DIR}"
  install -d -m 0750 "${CONFIG_DIR}/profiles" "${CONFIG_DIR}/backups"
  install -d -m 0700 "${CACHE_DIR}" "${CACHE_DIR}/audio" "${CACHE_DIR}/system"
  chown -R "${APP_USER}:${APP_USER}" "${CONFIG_DIR}" "${CACHE_DIR}" "${DATA_DIR}"

  python3 -m venv "${INSTALL_DIR}/venv"
  "${INSTALL_DIR}/venv/bin/python" -m pip install "${REPO_DIR}"

  if [[ ! -f "${CONFIG_DIR}/config.toml" ]]; then
    install -m 0644 "${REPO_DIR}/config/default_config.toml" "${CONFIG_DIR}/config.toml"
    chown "${APP_USER}:${APP_USER}" "${CONFIG_DIR}/config.toml"
  fi

  install -m 0644 "${REPO_DIR}/systemd/${APP_NAME}.service" "/etc/systemd/system/${APP_NAME}.service"
  install -m 0644 "${REPO_DIR}/systemd/${APP_NAME}-librespot.service" "/etc/systemd/system/${APP_NAME}-librespot.service"
  install -m 0440 "${REPO_DIR}/sudoers/${APP_NAME}" "/etc/sudoers.d/${APP_NAME}"
  visudo -cf "/etc/sudoers.d/${APP_NAME}"

  systemctl daemon-reload
  systemctl enable avahi-daemon.service
  systemctl enable "${APP_NAME}.service"
  systemctl enable "${APP_NAME}-librespot.service"

  if [[ "${START_NOW:-1}" == "1" ]]; then
    systemctl start "${APP_NAME}.service"
    systemctl start "${APP_NAME}-librespot.service"
  fi
}

install_librespot
install_app

cat <<EOF
Installed ${APP_NAME}.

Check the installation:
  sudo -u ${APP_USER} ${INSTALL_DIR}/venv/bin/pi-connect-speaker-doctor

Open:
  http://<raspberry-pi-ip>:8080
EOF
