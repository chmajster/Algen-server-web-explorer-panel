#!/usr/bin/env bash
set -Eeuo pipefail

RAW_BASE_URL="https://raw.githubusercontent.com/chmajster/Algen-server-web-explorer-panel/main"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"

if [[ -n "$SCRIPT_DIR" && -f "${SCRIPT_DIR}/install/install.sh" ]]; then
  exec bash "${SCRIPT_DIR}/install/install.sh" "$@"
fi

TEMP_DIR="$(mktemp -d -t webnas-installer.XXXXXX)"
cleanup() { rm -rf -- "$TEMP_DIR"; }
trap cleanup EXIT INT TERM
mkdir -p "${TEMP_DIR}/install/core"

fetch() {
  local path="$1"
  local target="${TEMP_DIR}/${path}"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "${RAW_BASE_URL}/${path}" -o "$target"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$target" "${RAW_BASE_URL}/${path}"
  else
    printf '[ERROR] curl or wget is required to download WebNAS installer files\n' >&2
    return 1
  fi
}

for path in \
  install/install.sh \
  install/install-standard-menu.sh \
  install/install-standard.sh \
  install/install-portable.sh \
  install/core/install-standard.sh \
  install/core/install-portable.sh
do
  fetch "$path"
done

status=0
if bash "${TEMP_DIR}/install/install.sh" "$@"; then
  status=0
else
  status=$?
fi
cleanup
trap - EXIT INT TERM
exit "$status"
