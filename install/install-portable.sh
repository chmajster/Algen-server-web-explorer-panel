#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CORE_SCRIPT="${SCRIPT_DIR}/core/install-portable.sh"

[[ -f "$CORE_SCRIPT" ]] || {
  printf '[ERROR] Missing portable installer core: %s\n' "$CORE_SCRIPT" >&2
  exit 1
}

if [[ -f "${REPO_ROOT}/backend/app/main.py" && -f "${REPO_ROOT}/frontend/package.json" ]]; then
  proxy="${REPO_ROOT}/.webnas-portable-installer.$$.$RANDOM.sh"
  if ln -s "install/core/install-portable.sh" "$proxy" 2>/dev/null; then
    cleanup() { rm -f -- "$proxy"; }
    trap cleanup EXIT INT TERM
    status=0
    if bash "$proxy" "$@"; then
      status=0
    else
      status=$?
    fi
    cleanup
    trap - EXIT INT TERM
    exit "$status"
  fi
fi

exec bash "$CORE_SCRIPT" "$@"
