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
  -y, --y, --yes           Non-interactive mode; automatically accept defaults

Portable options:
  -p, --port PORT          Application port (default: 5000)
  --bind-host ADDRESS      Listen address (default: 127.0.0.1)
  --keep-workdir           Keep the temporary runtime directory after exit
  -h, --help               Show help for the selected mode

Fresh standard installations use the WebNAS Local database authentication mode
by default. The initial administrator password is generated randomly and shown
once by the standard installer; it is never written to a plaintext credential
file. PAM and optional LDAP are available later through Settings ->
Administration -> Authentication. Standard installer options such as
--install-dir, --user and --existing-action remain available.
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
  local exit_code=0

  if [[ -n "$SCRIPT_DIR" && -f "$local_target" ]]; then
    if bash "$local_target" "$@"; then
      return 0
    else
      exit_code=$?
    fi
    return "$exit_code"
  fi

  temp_script="$(mktemp -t webnas-launcher.XXXXXX.sh)"
  trap "rm -f -- $(printf '%q' "$temp_script")" EXIT

  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "${RAW_BASE_URL}/${target}" -o "$temp_script"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$temp_script" "${RAW_BASE_URL}/${target}"
  else
    printf '[ERROR] curl or wget is required to download %s\n' "$target" >&2
    return 1
  fi

  if bash "$temp_script" "$@"; then
    exit_code=0
  else
    exit_code=$?
  fi

  rm -f -- "$temp_script"
  trap - EXIT
  return "$exit_code"
}

standard_action_has_runtime() {
  local expect_action="no"
  local action=""
  local arg=""
  for arg in "${FORWARD_ARGS[@]}"; do
    if [[ "$expect_action" == "yes" ]]; then
      action="$arg"
      expect_action="no"
      continue
    fi
    case "$arg" in
      --existing-action|-a) expect_action="yes" ;;
      --existing-action=*) action="${arg#*=}" ;;
    esac
  done
  case "$action" in
    backup-config|remove|remove-app|remove-all|abort) return 1 ;;
    *) return 0 ;;
  esac
}

standard_config_port() {
  local config_file="/etc/webnas/config.yaml"
  local configured=""
  if [[ -r "$config_file" ]]; then
    configured="$(awk '
      /^server:[[:space:]]*$/ { in_server=1; next }
      in_server && /^[^[:space:]]/ { exit }
      in_server && /^[[:space:]]+port:[[:space:]]*/ {
        sub(/^[[:space:]]+port:[[:space:]]*/, "")
        sub(/[[:space:]#].*$/, "")
        gsub(/"/, "")
        gsub(/\047/, "")
        print
        exit
      }
    ' "$config_file" 2>/dev/null || true)"
  fi
  if [[ "$configured" =~ ^[0-9]+$ ]] && (( configured >= 1 && configured <= 65535 )); then
    printf '%s' "$configured"
  else
    printf '%s' "5000"
  fi
}

standard_transport_scheme() {
  local config_file="/etc/webnas/config.yaml"
  local transport_file="/var/lib/webnas/settings/transport.json"
  if [[ -r "$transport_file" ]] && grep -Eq '"use_https"[[:space:]]*:[[:space:]]*true' "$transport_file"; then
    printf '%s' "https"
    return
  fi
  if [[ -r "$config_file" ]] && grep -Eq '^[[:space:]]*use_https:[[:space:]]*true[[:space:]]*$' "$config_file"; then
    printf '%s' "https"
  else
    printf '%s' "http"
  fi
}

print_standard_authentication_summary() {
  local port=""
  local scheme=""
  local response_file=""
  local mode=""
  local curl_options=(--fail --silent --show-error --max-time 5)

  standard_action_has_runtime || return 0
  command -v curl >/dev/null 2>&1 || return 0

  port="$(standard_config_port)"
  scheme="$(standard_transport_scheme)"
  [[ "$scheme" != "https" ]] || curl_options+=(--insecure)
  response_file="$(mktemp -t webnas-auth-config.XXXXXX.json)"

  if ! curl "${curl_options[@]}" "${scheme}://127.0.0.1:${port}/api/auth/config" -o "$response_file"; then
    rm -f -- "$response_file"
    printf '[WARN] WebNAS is installed, but the authentication status could not be read.\n' >&2
    return 0
  fi

  if command -v python3.14 >/dev/null 2>&1; then
    mode="$(python3.14 - "$response_file" <<'PY' 2>/dev/null || true
import json
import sys

try:
    payload = json.load(open(sys.argv[1], encoding="utf-8"))
except (OSError, ValueError, TypeError):
    raise SystemExit(0)
mode = payload.get("mode")
if mode in {"local", "system"}:
    print(mode)
PY
)"
  fi
  rm -f -- "$response_file"

  printf '\n==> Authentication summary\n'
  if [[ "$mode" == "local" ]]; then
    printf '[OK] Authentication mode: Local database (default)\n'
    printf '[INFO] A newly generated administrator password is printed once by the standard installer and is not retained in plaintext.\n'
    printf '[INFO] PAM and optional LDAP can be enabled later in Settings -> Administration -> Authentication.\n'
  elif [[ "$mode" == "system" ]]; then
    printf '[OK] Authentication mode: System authentication (PAM + optional LDAP)\n'
    printf '[INFO] The existing authentication mode was preserved.\n'
  else
    printf '[WARN] Authentication mode could not be determined from /api/auth/config.\n' >&2
  fi
}

if [[ "$MODE" == "portable" ]]; then
  run_target "install-portable.sh" "${FORWARD_ARGS[@]}"
else
  run_target "install-standard.sh" "${FORWARD_ARGS[@]}"
  print_standard_authentication_summary
fi
