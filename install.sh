#!/usr/bin/env bash
set -Eeuo pipefail

RAW_BASE_URL="https://raw.githubusercontent.com/chmajster/Algen-server-web-explorer-panel/main"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
MODE="standard"
FORWARD_ARGS=()

usage() {
  cat <<EOF_USAGE
WebNAS installer launcher

Usage:
  sudo ./install.sh [standard installer options]
  sudo ./install.sh --portable [portable options]
  curl -fsSL ${RAW_BASE_URL}/install.sh | sudo bash -s -- [options]

Launcher mode:
  -P, --portable           Run WebNAS in disposable portable mode. No systemd
                           service, /etc configuration, service user or firewall
                           rule is created. Runtime files are removed on exit.

Standard installer options:
  -y, --y, --yes          Non-interactive mode; automatically accept defaults

Portable options:
  -p, --port PORT          Application port (default: 5000)
  --bind-host ADDRESS      Listen address (default: 0.0.0.0)
  --keep-workdir           Keep the temporary runtime directory after exit
  -h, --help               Show help for the selected mode

Without --portable the existing installer is executed unchanged. Standard
installer options such as --install-dir, --user and --existing-action remain
available.
EOF_USAGE
}

for arg in "$@"; do
  case "$arg" in
    --portable|-P)
      MODE="portable"
      ;;
    --y)
      FORWARD_ARGS+=("--yes")
      ;;
    *)
      FORWARD_ARGS+=("$arg")
      ;;
  esac
done

if [[ "$MODE" == "standard" ]]; then
  for arg in "${FORWARD_ARGS[@]}"; do
    if [[ "$arg" == "--help" || "$arg" == "-h" ]]; then
      usage
      exit 0
    fi
  done
fi

run_target() {
  local target="$1"
  shift
  local local_target="${SCRIPT_DIR}/${target}"
  local temp_script=""

  if [[ -n "$SCRIPT_DIR" && -f "$local_target" ]]; then
    exec bash "$local_target" "$@"
  fi

  temp_script="$(mktemp -t webnas-launcher.XXXXXX.sh)"
  trap 'rm -f -- "$temp_script"' EXIT
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "${RAW_BASE_URL}/${target}" -o "$temp_script"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$temp_script" "${RAW_BASE_URL}/${target}"
  else
    printf '[ERROR] curl or wget is required to download %s\n' "$target" >&2
    exit 1
  fi
  bash "$temp_script" "$@"
}

if [[ "$MODE" == "portable" ]]; then
  run_target "install-portable.sh" "${FORWARD_ARGS[@]}"
else
  run_target "install-standard.sh" "${FORWARD_ARGS[@]}"
fi
