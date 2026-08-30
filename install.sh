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
by default and create the administrator account chris with password 1. Change
this default password immediately after the first login. PAM and optional LDAP
are available later through Settings -> Administration -> Authentication.
Standard installer options such as
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

run_bash_target() {
  local script="$1"
  shift
  local tty_fd=""
  local exit_code=0

  # `curl ... | sudo bash` gives the launcher a pipe on stdin. Pass the real
  # controlling terminal to the downloaded installer when one is available,
  # so interactive menus do not block while trying to recover /dev/tty later.
  if [[ ! -t 0 ]] && { exec {tty_fd}<>/dev/tty; } 2>/dev/null; then
    if bash "$script" "$@" <&"$tty_fd"; then
      exit_code=0
    else
      exit_code=$?
    fi
    exec {tty_fd}>&-
    return "$exit_code"
  fi

  bash "$script" "$@"
}

local_target_is_compatible() {
  local target="$1"
  local path="$2"

  # A standalone install.sh is commonly downloaded into a directory that may
  # still contain an older menu wrapper. Do not let that stale sibling shadow
  # the current menu from main. Versioned menu files remain usable for source
  # checkouts and packaged installer bundles.
  if [[ "$target" == "install-standard-menu.sh" ]]; then
    grep -Fxq 'WEBNAS_INSTALLER_MENU_API_VERSION=2' "$path" 2>/dev/null
    return $?
  fi

  return 0
}

run_target() {
  local target="$1"
  shift
  local local_target="${SCRIPT_DIR}/${target}"
  local temp_script=""
  local exit_code=0

  if [[ -n "$SCRIPT_DIR" && -f "$local_target" ]]; then
    if ! local_target_is_compatible "$target" "$local_target"; then
      printf '[INFO] Ignoring stale local %s; downloading the current version from main.\n' "$target" >&2
    else
      if run_bash_target "$local_target" "$@"; then
        return 0
      else
        exit_code=$?
      fi
      return "$exit_code"
    fi
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

  if run_bash_target "$temp_script" "$@"; then
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

standard_install_dir() {
  local expect_dir="no"
  local install_dir="/opt/webnas"
  local arg=""
  for arg in "${FORWARD_ARGS[@]}"; do
    if [[ "$expect_dir" == "yes" ]]; then
      install_dir="$arg"
      expect_dir="no"
      continue
    fi
    case "$arg" in
      --install-dir|-d) expect_dir="yes" ;;
      --install-dir=*) install_dir="${arg#*=}" ;;
    esac
  done
  printf '%s' "$install_dir"
}

standard_reinstall_backup_snapshot() {
  local state=""
  for state in /var/backups/webnas/*-reinstall.*/installer-state; do
    [[ -f "$state" ]] || continue
    grep -qx 'action=reinstall' "$state" 2>/dev/null || continue
    printf '%s\n' "$state"
  done
}

standard_reinstall_happened() {
  local before_snapshot="$1"
  local state=""
  while IFS= read -r state; do
    [[ -n "$state" ]] || continue
    if ! grep -Fxq -- "$state" <<< "$before_snapshot"; then
      return 0
    fi
  done < <(standard_reinstall_backup_snapshot)
  return 1
}

finalize_standard_reinstall() {
  local install_dir=""
  local requested_install_dir=""
  local active_release=""
  local entry=""
  local release=""
  local entry_name=""

  requested_install_dir="$(standard_install_dir)"
  if [[ "$requested_install_dir" != /* || "$requested_install_dir" == "/" || "$requested_install_dir" == "/etc" || "$requested_install_dir" == "/usr" || "$requested_install_dir" == "/bin" || "$requested_install_dir" == "/lib" ]]; then
    printf '[ERROR] Refusing reinstall cleanup for unsafe installation directory: %s\n' "$requested_install_dir" >&2
    return 1
  fi

  install_dir="$(readlink -f -- "$requested_install_dir" 2>/dev/null || true)"
  if [[ -z "$install_dir" || "$install_dir" == "/" || "$install_dir" == "/etc" || "$install_dir" == "/usr" || "$install_dir" == "/bin" || "$install_dir" == "/lib" ]]; then
    printf '[ERROR] Refusing reinstall cleanup because the installation directory could not be safely canonicalized: %s\n' "$requested_install_dir" >&2
    return 1
  fi
  if [[ ! -L "${install_dir}/current" || ! -d "${install_dir}/releases" ]]; then
    printf '[ERROR] Reinstall completed without a valid release layout in %s\n' "$install_dir" >&2
    return 1
  fi

  active_release="$(readlink -f "${install_dir}/current" 2>/dev/null || true)"
  case "$active_release" in
    "${install_dir}/releases/"*) ;;
    *)
      printf '[ERROR] Refusing reinstall cleanup because current points outside %s/releases\n' "$install_dir" >&2
      return 1
      ;;
  esac
  [[ -d "$active_release" ]] || {
    printf '[ERROR] Active release does not exist after reinstall: %s\n' "$active_release" >&2
    return 1
  }

  printf '\n==> Cleaning previous application files\n'
  printf '[INFO] Replacement release is active; removing all stale WebNAS application files while preserving config, data, and logs.\n'

  # The release helper rewrites the privileged broker unit to the new release,
  # but an already-running broker keeps executing the old binary until it is
  # restarted. Restart it before deleting any previous release tree.
  if systemctl is-active --quiet webnas-privileged.service 2>/dev/null; then
    if ! systemctl restart webnas-privileged.service; then
      printf '[ERROR] Could not restart webnas-privileged.service on the active release; old application files were not removed.\n' >&2
      return 1
    fi
  fi

  for release in "${install_dir}/releases"/*; do
    [[ -e "$release" ]] || continue
    [[ "$(readlink -f "$release" 2>/dev/null || true)" == "$active_release" ]] && continue
    rm -rf --one-file-system -- "$release"
  done

  shopt -s nullglob dotglob
  for entry in "${install_dir}"/*; do
    entry_name="${entry##*/}"
    case "$entry_name" in
      current|releases|uninstall.sh|webnas_release.py) continue ;;
    esac
    rm -rf --one-file-system -- "$entry"
  done
  shopt -u dotglob nullglob

  printf '[OK] Clean reinstall finalized: all stale application files removed; config, data, and logs preserved.\n'
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
    printf '[INFO] Fresh installations create the local administrator chris with default password 1; change it immediately after the first login.\n'
    printf '[INFO] PAM and optional LDAP can be enabled later in Settings -> Administration -> Authentication.\n'
  elif [[ "$mode" == "system" ]]; then
    printf '[OK] Authentication mode: System authentication (PAM + optional LDAP)\n'
    printf '[INFO] The existing authentication mode was preserved.\n'
  else
    printf '[WARN] Authentication mode could not be determined from /api/auth/config.\n' >&2
  fi
}

standard_installer_target() {
  # A source checkout contains both files and uses the interactive menu wrapper.
  # Small launcher harnesses and downstream packaging may intentionally provide
  # only install-standard.sh; keep that local installer authoritative instead
  # of downloading a mismatched menu wrapper from the main branch.
  if [[ -n "$SCRIPT_DIR" && -f "${SCRIPT_DIR}/install-standard.sh" && ! -f "${SCRIPT_DIR}/install-standard-menu.sh" ]]; then
    printf '%s' "install-standard.sh"
  else
    printf '%s' "install-standard-menu.sh"
  fi
}

if [[ "$MODE" == "portable" ]]; then
  run_target "install-portable.sh" "${FORWARD_ARGS[@]}"
else
  reinstall_backups_before="$(standard_reinstall_backup_snapshot)"
  run_target "$(standard_installer_target)" "${FORWARD_ARGS[@]}"
  if standard_reinstall_happened "$reinstall_backups_before"; then
    finalize_standard_reinstall
  fi
  # Updates run through the long-lived privileged broker. The release helper
  # rewrites its unit to the newly activated release, so restart an active
  # broker after a successful install/update before reporting completion.
  if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet webnas-privileged.service 2>/dev/null; then
    systemctl restart webnas-privileged.service
  fi
  print_standard_authentication_summary
fi
