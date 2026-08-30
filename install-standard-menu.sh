#!/usr/bin/env bash
set -Eeuo pipefail

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
  [[ "$path" == /tmp/webnas-* ]] && rm -f -- "$path"
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

  printf 'Choose action (automatic update starts after 5 seconds):\n'
  printf '  1) Update application (backup and keep config) [default]\n'
  printf '  2) Reinstall application (clean app files; keep config, data, and logs)\n'
  printf '  3) Backup configuration only\n'
  printf '  4) Remove application (keep config, data, and logs)\n'
  printf '  5) Remove application and all files\n'
  printf '  6) Abort\n'
  printf '  7) Full Reinstall application (remove all data)\n'

  if IFS= read -r -t "$timeout" -p 'Select [1-7]: ' answer; then
    printf '%s' "${answer:-1}"
    return 0
  fi

  printf '\n[INFO] No action selected within 5 seconds; starting update with configuration backup\n' >&2
  printf '1'
}

confirm_full_reinstall() {
  local typed=""
  printf '\n[WARNING] Full Reinstall permanently removes application files, configuration, databases/data, and logs.\n' >&2
  printf '[WARNING] Backups stored outside /opt/webnas, /etc/webnas, /var/lib/webnas and /var/log/webnas are not removed.\n' >&2
  if ! IFS= read -r -p "Type 'FULL-REINSTALL' to continue: " typed; then
    printf '[ERROR] Full reinstall cancelled.\n' >&2
    return 1
  fi
  if [[ "$typed" != "FULL-REINSTALL" ]]; then
    printf '[ERROR] Full reinstall cancelled: confirmation text did not match.\n' >&2
    return 1
  fi
}

full_reinstall() {
  local standard_script="$1"
  local uninstall_script=""
  local uninstall_from_install="${INSTALL_DIR}/uninstall.sh"
  local fresh_args=("${FORWARD_ARGS[@]}")

  confirm_full_reinstall

  printf '\n==> Full reinstall: removing existing WebNAS installation and all data\n'
  if [[ -x "$uninstall_from_install" || -f "$uninstall_from_install" ]]; then
    uninstall_script="$uninstall_from_install"
  else
    uninstall_script="$(resolve_script uninstall.sh)"
  fi

  # uninstall.sh requires an explicit text confirmation even with --yes.
  # Feed only that mandatory token; --remove-data performs the destructive
  # config/data/log purge without a second interactive prompt.
  printf 'REMOVE WEBNAS\n' | WEBNAS_INSTALL_DIR="$INSTALL_DIR" bash "$uninstall_script" --yes --remove-data --install-dir "$INSTALL_DIR"
  cleanup_temp_script "$uninstall_script"

  printf '\n==> Full reinstall: installing a fresh WebNAS instance\n'
  fresh_args+=("--yes")
  run_standard "$standard_script" "${fresh_args[@]}"
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
  *)
    printf '[ERROR] Invalid choice: %s\n' "$choice" >&2
    exit 1
    ;;
esac
