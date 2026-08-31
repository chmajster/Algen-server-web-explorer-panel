#!/usr/bin/env bash
set -Eeuo pipefail

# Canonical WebNAS installer entrypoint.
# Keep the implementation and installer variants under install/* so the
# repository root exposes only the stable launcher users should execute.
RAW_LAUNCHER_URL="https://raw.githubusercontent.com/chmajster/Algen-server-web-explorer-panel/main/install/install.sh"
SCRIPT_SOURCE="${BASH_SOURCE[0]:-}"
SCRIPT_DIR=""

if [[ -n "$SCRIPT_SOURCE" && "$SCRIPT_SOURCE" != "bash" && -f "$SCRIPT_SOURCE" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_SOURCE")" 2>/dev/null && pwd || true)"
fi

run_launcher() {
  local launcher="$1"
  shift
  local status=0

  if bash "$launcher" "$@"; then
    status=0
  else
    status=$?
  fi
  return "$status"
}

# Source checkout: use the installer implementation tracked next to this file.
if [[ -n "$SCRIPT_DIR" && -f "${SCRIPT_DIR}/install/install.sh" ]]; then
  exec bash "${SCRIPT_DIR}/install/install.sh" "$@"
fi

# curl/wget entrypoint: fetch the implementation from install/* and preserve
# all arguments. The implementation is responsible for recovering /dev/tty for
# interactive menus when this launcher itself is being executed from a pipe.
temp_launcher="$(mktemp -t webnas-installer.XXXXXX.sh)"
trap 'rm -f -- "$temp_launcher"' EXIT

if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$RAW_LAUNCHER_URL" -o "$temp_launcher"
elif command -v wget >/dev/null 2>&1; then
  wget -qO "$temp_launcher" "$RAW_LAUNCHER_URL"
else
  printf '[ERROR] curl or wget is required to download the WebNAS installer.\n' >&2
  exit 1
fi

run_launcher "$temp_launcher" "$@"
status=$?
rm -f -- "$temp_launcher"
trap - EXIT
exit "$status"
