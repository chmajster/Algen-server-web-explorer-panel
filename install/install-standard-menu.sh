#!/usr/bin/env bash
set -Eeuo pipefail

WEBNAS_INSTALLER_MENU_API_VERSION=2
RAW_BASE_URL="https://raw.githubusercontent.com/chmajster/Algen-server-web-explorer-panel/main"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
FORWARD_ARGS=("$@")
INSTALL_DIR="/opt/webnas"
EXPLICIT_ACTION="no"
ASSUME_YES="no"

for ((i=0; i<${#FORWARD_ARGS[@]}; i++)); do
  arg="${FORWARD_ARGS[$i]}"
  case "$arg" in
    --install-dir|-d)
      if (( i + 1 < ${#FORWARD_ARGS[@]} )); then
        INSTALL_DIR="${FORWARD_ARGS[$((i + 1))]}"
      fi
      ;;
    --install-dir=*)
      INSTALL_DIR="${arg#*=}"
      ;;
    --existing-action|-a|--existing-action=*)
      EXPLICIT_ACTION="yes"
      ;;
    --yes|-y)
      ASSUME_YES="yes"
      ;;
  esac
done

resolve_script() {
  local name="$1"
  local local_path="${SCRIPT_DIR}/${name}"
  local temp_path=""

  if [[ -n "$SCRIPT_DIR" && -f "$local_path" ]]; then
    printf '%s' "$local_path"
    return 0
  fi

  temp_path="$(mktemp -t "webnas-${name%.sh}.XXXXXX.sh")"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "${RAW_BASE_URL}/${name}" -o "$temp_path"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$temp_path" "${RAW_BASE_URL}/${name}"
  else
    printf '[ERROR] curl or wget is required to download %s\n' "$name" >&2
    return 1
  fi
  printf '%s' "$temp_path"
}

cleanup_temp_script() {
  local path="$1"
  if [[ "$path" == /tmp/webnas-* ]]; then
    rm -f -- "$path"
  fi
  # EXIT traps must never replace a successful installer status with the
  # false status of a cleanup predicate. A real installer failure remains the
  # shell's pending exit status even when this cleanup returns successfully.
  return 0
}

run_standard() {
  local standard_script="$1"
  shift
  bash "$standard_script" "$@"
}

existing_install_detected() {
  [[ -e "$INSTALL_DIR" || -e /etc/webnas/config.yaml || -e /var/lib/webnas || -e /var/log/webnas ]]
}

read_menu_choice() {
  local answer=""
  local timeout="5"

  printf 'Choose action (automatic update starts after 5 seconds):\n' >&2
  printf '  1) Update application (backup and keep config) [default]\n' >&2
  printf '  2) Reinstall application (clean app files; keep config, data, and logs)\n' >&2
  printf '  3) Backup configuration only\n' >&2
  printf '  4) Remove application (keep config, data, and logs)\n' >&2
  printf '  5) Remove application and all files\n' >&2
  printf '  6) Abort\n' >&2
  printf '  7) Full Reinstall application (remove all data)\n' >&2
  printf '  8) Restart application\n' >&2

  if IFS= read -r -t "$timeout" -p 'Select [1-8]: ' answer; then
    printf '%s' "${answer:-1}"
    return 0
  fi

  printf '\n[INFO] No action selected within 5 seconds; starting update with configuration backup\n' >&2
  printf '1'
}

configured_application_port() {
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

application_transport_scheme() {
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

wait_for_application_health() {
  local port=""
  local scheme=""
  local attempt=""
  local -a curl_options=(--fail --silent --max-time 2)

  command -v curl >/dev/null 2>&1 || {
    printf '[ERROR] Cannot verify WebNAS readiness after restart: curl is unavailable.\n' >&2
    return 1
  }

  port="$(configured_application_port)"
  scheme="$(application_transport_scheme)"
  [[ "$scheme" != "https" ]] || curl_options+=(--insecure)

  printf '[INFO] Waiting for WebNAS health endpoint on %s://127.0.0.1:%s ...\n' "$scheme" "$port"
  for attempt in {1..20}; do
    if curl "${curl_options[@]}" "${scheme}://127.0.0.1:${port}/api/health" >/dev/null 2>&1; then
      printf '[OK] WebNAS health check passed after restart.\n'
      return 0
    fi
    sleep 1
  done

  printf '[ERROR] WebNAS /api/health did not become ready within 20 seconds.\n' >&2
  return 1
}

print_service_diagnostics() {
  local unit="$1"

  printf '\n[DIAGNOSTICS] %s\n' "$unit" >&2
  systemctl status "$unit" --no-pager -l >&2 2>/dev/null || true
  journalctl -u "$unit" -n 60 --no-pager >&2 2>/dev/null || true
}

resolve_application_unit() {
  local active_slot_file="/etc/webnas/runtime/active-slot"
  local active_slot=""
  local unit=""

  # The persisted blue/green marker is authoritative even when the selected
  # backend is currently failed or stuck in an auto-restart loop. Restricting
  # discovery to `systemctl is-active` makes the Restart action unable to
  # recover exactly the broken runtime it is meant to repair.
  if [[ -r "$active_slot_file" ]]; then
    active_slot="$(tr -d '[:space:]' < "$active_slot_file")"
    if [[ "$active_slot" == "blue" || "$active_slot" == "green" ]]; then
      unit="webnas-backend-${active_slot}.service"
      if systemctl cat "$unit" >/dev/null 2>&1; then
        printf '%s' "$unit"
        return 0
      fi
    fi
  fi

  for unit in webnas-backend-blue.service webnas-backend-green.service webnas.service; do
    if systemctl is-active --quiet "$unit" 2>/dev/null; then
      printf '%s' "$unit"
      return 0
    fi
  done

  # Last-resort recovery for an installed service which is currently failed or
  # activating but predates the active-slot marker.
  for unit in webnas-backend-blue.service webnas-backend-green.service webnas.service; do
    if systemctl cat "$unit" >/dev/null 2>&1; then
      printf '%s' "$unit"
      return 0
    fi
  done

  return 1
}

restart_privileged_broker() {
  systemctl reset-failed webnas-privileged.service 2>/dev/null || true

  if ! systemctl restart webnas-privileged.socket; then
    printf '[ERROR] WebNAS privileged broker socket could not be restarted.\n' >&2
    print_service_diagnostics webnas-privileged.socket
    return 1
  fi

  # Start the broker explicitly even when it was previously inactive. Waiting
  # for a future privileged API call would leave PAM unavailable after a
  # nominally successful application restart.
  if ! systemctl restart webnas-privileged.service; then
    printf '[ERROR] WebNAS privileged broker could not be restarted.\n' >&2
    print_service_diagnostics webnas-privileged.service
    return 1
  fi

  if ! systemctl is-active --quiet webnas-privileged.service; then
    printf '[ERROR] WebNAS privileged broker is not active after restart.\n' >&2
    print_service_diagnostics webnas-privileged.service
    return 1
  fi

  printf '[OK] WebNAS privileged broker is active.\n'
}

restart_application() {
  local unit=""

  command -v systemctl >/dev/null 2>&1 || {
    printf '[ERROR] Cannot restart WebNAS: systemctl is unavailable.\n' >&2
    return 1
  }

  unit="$(resolve_application_unit || true)"
  if [[ -z "$unit" ]]; then
    printf '[ERROR] Cannot restart WebNAS: no installed application service was found.\n' >&2
    return 1
  fi

  printf '\n==> Restarting WebNAS application\n'
  printf '[INFO] Selected application service: %s\n' "$unit"

  restart_privileged_broker

  systemctl reset-failed "$unit" 2>/dev/null || true
  if ! systemctl restart "$unit"; then
    printf '[ERROR] WebNAS service restart command failed: %s\n' "$unit" >&2
    print_service_diagnostics "$unit"
    return 1
  fi

  if ! wait_for_application_health; then
    print_service_diagnostics "$unit"
    print_service_diagnostics webnas-privileged.service
    return 1
  fi

  if ! systemctl is-active --quiet "$unit"; then
    printf '[ERROR] WebNAS health endpoint responded, but service is not active: %s\n' "$unit" >&2
    print_service_diagnostics "$unit"
    return 1
  fi

  printf '[OK] WebNAS application restarted: %s\n' "$unit"
}

full_reinstall_countdown() {
  local seconds=""
  printf '\nFull Reinstall starts automatically. Press Ctrl+C to cancel.\n' >&2
  for seconds in 5 4 3 2 1; do
    printf 'Starting in %s...\n' "$seconds" >&2
    sleep 1
  done
}

remove_all_with_standard_installer() {
  local standard_script="$1"
  local command_line=""
  local command_args=(bash "$standard_script" "${FORWARD_ARGS[@]}" --existing-action remove-all)

  command -v script >/dev/null 2>&1 || {
    printf '[ERROR] Full reinstall requires the util-linux script command for the destructive removal stage.\n' >&2
    return 1
  }

  printf -v command_line '%q ' "${command_args[@]}"
  printf 'y\n' | script --quiet --return --command "$command_line" /dev/null
}

full_reinstall() {
  local standard_script="$1"
  local fresh_args=("${FORWARD_ARGS[@]}")

  full_reinstall_countdown

  printf '\n==> Full reinstall: removing existing WebNAS installation and all data\n'
  remove_all_with_standard_installer "$standard_script"

  if [[ -e "$INSTALL_DIR" || -e /etc/webnas || -e /var/lib/webnas || -e /var/log/webnas ]]; then
    printf '[ERROR] Full reinstall purge did not remove all application/config/data/log paths; fresh installation was not started.\n' >&2
    return 1
  fi

  printf '\n==> Full reinstall: installing a fresh WebNAS instance\n'
  fresh_args+=("--yes")
  run_standard "$standard_script" "${fresh_args[@]}"

  [[ -L "${INSTALL_DIR}/current" ]] || {
    printf '[ERROR] Full reinstall completed without an active release symlink.\n' >&2
    return 1
  }
  [[ -f /etc/webnas/config.yaml ]] || {
    printf '[ERROR] Full reinstall completed without a fresh configuration file.\n' >&2
    return 1
  }
  [[ -d /var/lib/webnas && -d /var/log/webnas ]] || {
    printf '[ERROR] Full reinstall completed without fresh data/log directories.\n' >&2
    return 1
  }

  printf '\n[OK] Full reinstall completed: application, config, data, and logs were recreated from a clean state.\n'
}

standard_script="$(resolve_script install-standard.sh)"
trap 'cleanup_temp_script "$standard_script"' EXIT

# Preserve the standard installer's current behavior for fresh installations,
# explicit CLI actions and --yes/non-interactive operation.
if ! existing_install_detected || [[ "$EXPLICIT_ACTION" == "yes" || "$ASSUME_YES" == "yes" || ! -t 0 ]]; then
  run_standard "$standard_script" "${FORWARD_ARGS[@]}"
  exit $?
fi

choice="$(read_menu_choice)"
case "$choice" in
  1)
    run_standard "$standard_script" "${FORWARD_ARGS[@]}" --existing-action update
    ;;
  2)
    run_standard "$standard_script" "${FORWARD_ARGS[@]}" --existing-action reinstall
    ;;
  3)
    run_standard "$standard_script" "${FORWARD_ARGS[@]}" --existing-action backup-config
    ;;
  4)
    run_standard "$standard_script" "${FORWARD_ARGS[@]}" --existing-action remove-app
    ;;
  5)
    run_standard "$standard_script" "${FORWARD_ARGS[@]}" --existing-action remove-all
    ;;
  6)
    printf '[ERROR] Installation cancelled\n' >&2
    exit 1
    ;;
  7)
    full_reinstall "$standard_script"
    ;;
  8)
    restart_application
    ;;
  *)
    printf '[ERROR] Invalid choice: %s\n' "$choice" >&2
    exit 1
    ;;
esac
