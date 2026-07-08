#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${PORT:-5000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  [[ -n "$BACKEND_PID" ]] && kill "$BACKEND_PID" 2>/dev/null || true
  [[ -n "$FRONTEND_PID" ]] && kill "$FRONTEND_PID" 2>/dev/null || true
  return 0
}
trap cleanup EXIT INT TERM

command -v python3 >/dev/null 2>&1 || { echo "python3 is required" >&2; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "npm is required" >&2; exit 1; }

if [[ ! -d "${ROOT_DIR}/backend/.venv" ]]; then
  python3 -m venv "${ROOT_DIR}/backend/.venv"
fi

"${ROOT_DIR}/backend/.venv/bin/pip" install -r "${ROOT_DIR}/backend/requirements.txt"

if [[ ! -d "${ROOT_DIR}/frontend/node_modules" ]]; then
  (cd "${ROOT_DIR}/frontend" && npm install)
fi

echo "Starting WebNAS backend on http://127.0.0.1:${PORT}"
(
  cd "${ROOT_DIR}/backend"
  PYTHONPATH="${ROOT_DIR}/backend" "${ROOT_DIR}/backend/.venv/bin/uvicorn" app.main:app --reload --host 0.0.0.0 --port "$PORT"
) &
BACKEND_PID="$!"

echo "Starting WebNAS frontend on http://127.0.0.1:${FRONTEND_PORT}"
(cd "${ROOT_DIR}/frontend" && npm run dev -- --host 0.0.0.0 --port "$FRONTEND_PORT") &
FRONTEND_PID="$!"

wait "$BACKEND_PID" "$FRONTEND_PID"
