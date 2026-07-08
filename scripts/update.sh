#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/webnas"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo ./scripts/update.sh"
  exit 1
fi

if ! command -v rsync >/dev/null 2>&1; then
  echo "rsync is required. Install it first, for example: sudo apt-get install -y rsync"
  exit 1
fi

systemctl stop webnas.service 2>/dev/null || true
rsync -a --delete --exclude ".git" --exclude "frontend/node_modules" --exclude "frontend/dist" "${SRC_DIR}/" "${APP_DIR}/"
"${APP_DIR}/backend/.venv/bin/pip" install -r "${APP_DIR}/backend/requirements.txt"
cd "${APP_DIR}/frontend"
npm install
npm run build
systemctl daemon-reload
systemctl start webnas.service
systemctl --no-pager status webnas.service || true
