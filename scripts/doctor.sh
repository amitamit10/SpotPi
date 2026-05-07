#!/usr/bin/env bash
set -euo pipefail

APP_NAME="spotpi"
DOCTOR="/opt/${APP_NAME}/venv/bin/spotpi-doctor"

if [[ -x "${DOCTOR}" ]]; then
  exec "${DOCTOR}"
fi

PYTHONPATH="$(cd "$(dirname "${BASH_SOURCE[0]}")/../src" && pwd)" exec python3 -m spotpi.cli doctor
