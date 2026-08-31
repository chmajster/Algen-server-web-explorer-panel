#!/usr/bin/env bash
set -Eeuo pipefail

SERVICE_NAME="webnas"
REPO_URL="https://github.com/chmajster/Algen-server-web-explorer-panel"
ARCHIVE_URL=""
RAW_INSTALL_URL="https://raw.githubusercontent.com/chmajster/Algen-server-web-explorer-panel/main/install/install.sh"

#TEST
PORT="5000"
PORT_EXPLICIT="no"
INSTALL_DIR="/opt/webnas"
SERVICE_USER="webnas"
SERVICE_USER_EXPLICIT="no"
SERVICE_GROUP="webnas"
NODE_MAJOR="22"
START_SERVICE="yes"
ENABLE_AUTOSTART="yes"
CONFIGURE_FIREWALL="yes"
SKIP_BUILD="no"
NPM_AUDIT_FIX="no"
ASSUME_YES="no"
NON_INTERACTIVE="no"
ACTION="install"
EXISTING_ACTION=""
REMOVE_SCOPE=""
UPDATE_CONFIG="no"
EXISTING_ACTION_TIMEOUT="5"
ALLOW_PROXMOX_HOST_INSTALL="no"
GRANT_JOURNAL_ACCESS="no"
IS_PROXMOX="no"
IS_WSL="no"
WSL_VERSION=""

CONFIG_DIR="/etc/webnas"
CONFIG_FILE="${CONFIG_DIR}/config.yaml"
DATA_DIR="/var/lib/webnas"
LOG_DIR="/var/log/webnas"
BACKUP_ROOT="/var/backups/webnas"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
BACKEND_BLUE_FILE="/etc/systemd/system/webnas-backend-blue.service"
BACKEND_GREEN_FILE="/etc/systemd/system/webnas-backend-green.service"
NGINX_CONFIG_FILE="/etc/nginx/conf.d/webnas.conf"
PAM_SERVICE_FILE="/etc/pam.d/${SERVICE_NAME}"
USB_SERVICE_FILE="/etc/systemd/system/webnas-usb-mount@.service"
USB_UDEV_RULE_FILE="/etc/udev/rules.d/99-webnas-usb-automount.rules"
USB_MOUNT_ROOT="/media/webnas-usb"
USB_STATE_DIR="/run/webnas/usb-mounts"
WORK_DIR=""
SOURCE_DIR=""
SOURCE_REVISION=""
APT_TEMP_DIR=""
APT_SOURCE_OPTIONS=()
APT_METADATA_REFRESHED="no"
APT_SOURCES_ROOT="/etc/apt"
CURRENT_STEP="startup"
APP_COPY_STARTED="no"
INSTALL_COMPLETED="no"
LAST_BACKUP_DIR=""
SERVICE_WAS_ACTIVE="no"
ACTIVE_RELEASE=""
USB_AUTOMOUNT_STAGE="not started"
PYTHON_BIN="$(command -v python3.14 || true)"
WEBNAS_OS_RELEASE_FILE="${WEBNAS_OS_RELEASE_FILE:-/etc/os-release}"
WEBNAS_KERNEL_RELEASE_FILE="${WEBNAS_KERNEL_RELEASE_FILE:-/proc/sys/kernel/osrelease}"

if [[ -t 1 ]]; then
  RED="$(printf '\033[31m')"
  GREEN="$(printf '\033[32m')"
  YELLOW="$(printf '\033[33m')"
  BLUE="$(printf '\033[34m')"
  BOLD="$(printf '\033[1m')"
  RESET="$(printf '\033[0m')"
else
  RED=""
  GREEN=""
  YELLOW=""
  BLUE=""
  BOLD=""
  RESET=""
fi

usage() {
  cat <<EOF
WebNAS installer

Usage:
  sudo ./install.sh [options]
  curl -fsSL ${RAW_INSTALL_URL} | sudo bash -s -- [options]

Options:
  -p, --port PORT         Application port (default: 5000)
  -d, --install-dir PATH  Installation directory (default: /opt/webnas)
  -u, --user USER         System user for the service (default: webnas)
  -y, --yes               Non-interactive mode; accept defaults
  --no-firewall           Do not configure ufw/firewalld
  --skip-build            Deprecated; application installs require a matching frontend build
  --npm-audit-fix         Run npm audit fix before building the frontend
  --allow-proxmox-host-install
                          Explicitly allow restricted installation on a Proxmox VE host
  --grant-journal-access  Add the service user to systemd-journal for system log access
  -a, --existing-action ACTION
                          Existing install action: update, reinstall, backup-config, remove, remove-app, remove-all, or abort
  -c, --update-config     Also regenerate config.yaml during update actions
  -h, --help              Show this help
EOF
}

log() { printf '%b[%s]%b %s\n' "$2" "$1" "$RESET" "$3"; }
info() { log "INFO" "$BLUE" "$1"; }
ok() { log "OK" "$GREEN" "$1"; }
warn() { log "WARN" "$YELLOW" "$1"; }
fail() { log "ERROR" "$RED" "$1"; exit 1; }
section() {
  CURRENT_STEP="$1"
  printf '\n%b==> %s%b\n' "$BOLD" "$1" "$RESET"
}

update_step() {
  [[ "$ACTION" == "update" ]] || return 0
  printf 'Update step: %s %s\n' "$1" "$2"
}

print_error_context() {
  local os_name=""
  local required_command=""
  os_name="$(os_release_value PRETTY_NAME 2>/dev/null || true)"
  printf '\nDiagnostic context:\n' >&2
  printf '  Action:            %s\n' "$ACTION" >&2
  printf '  Operating system:  %s\n' "${os_name:-unknown}" >&2
  printf '  Kernel:            %s\n' "$(uname -sr 2>/dev/null || printf 'unknown')" >&2
  printf '  Architecture:      %s\n' "$(uname -m 2>/dev/null || printf 'unknown')" >&2
  printf '  Install directory: %s\n' "$INSTALL_DIR" >&2
  [[ -z "$ACTIVE_RELEASE" ]] || printf '  Candidate release: %s\n' "$ACTIVE_RELEASE" >&2

  if [[ "$CURRENT_STEP" == "Installing USB automount" ]]; then
    printf '\nUSB automount diagnostics:\n' >&2
    printf '  Last operation:    %s\n' "$USB_AUTOMOUNT_STAGE" >&2
    printf '  Helper source:     %s (%s)\n' "${INSTALL_DIR}/scripts/usb_automount.py" "$([[ -f "${INSTALL_DIR}/scripts/usb_automount.py" ]] && printf 'present' || printf 'missing')" >&2
    printf '  Udev rule source:  %s (%s)\n' "${INSTALL_DIR}/packaging/99-webnas-usb-automount.rules" "$([[ -f "${INSTALL_DIR}/packaging/99-webnas-usb-automount.rules" ]] && printf 'present' || printf 'missing')" >&2
    printf '  Udev rule target:  %s (%s)\n' "$USB_UDEV_RULE_FILE" "$([[ -f "$USB_UDEV_RULE_FILE" ]] && printf 'present' || printf 'missing')" >&2
    printf '  Systemd unit:      %s (%s)\n' "$USB_SERVICE_FILE" "$([[ -f "$USB_SERVICE_FILE" ]] && printf 'present' || printf 'missing')" >&2
    for required_command in udevadm findmnt systemctl; do
      printf '  Command %-10s %s\n' "${required_command}:" "$(command -v "$required_command" 2>/dev/null || printf 'missing')" >&2
    done
    printf '\nRecommended checks:\n' >&2
    printf '  systemctl status systemd-udevd --no-pager -l\n' >&2
    printf '  journalctl -u systemd-udevd -n 80 --no-pager\n' >&2
    printf '  systemd-analyze verify %s\n' "$USB_SERVICE_FILE" >&2
    printf '  udevadm control --reload-rules\n' >&2
  fi
}

on_error() {
  local line="$1"
  local code="$2"
  trap - ERR
  printf '\n%b[ERROR]%b Installation failed at line %s with exit code %s.\n' "$RED" "$RESET" "$line" "$code" >&2
  printf 'Failed step: %s\n' "$CURRENT_STEP" >&2
  printf 'Check the command output directly above this error.\n' >&2
  print_error_context || true
  if [[ -f "$SERVICE_FILE" ]]; then
    printf 'Systemd service exists; inspect: journalctl -u %s -n 80 --no-pager\n' "$SERVICE_NAME" >&2
  else
    printf 'Systemd service was not installed yet, so journalctl may have no entries.\n' >&2
  fi
}
trap 'on_error "$LINENO" "$?"' ERR

banner() {
  cat <<'EOF'
 __        __   _     _   _    _    ____
 \ \      / /__| |__ | \ | |  / \  / ___|
  \ \ /\ / / _ \ '_ \|  \| | / _ \ \___ \
   \ V  V /  __/ |_) | |\  |/ ___ \ ___) |
    \_/\_/ \___|_.__/|_| \_/_/   \_\____/

EOF
  printf '%s\n' "Professional one-command installer for WebNAS"
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --port|-p)
        [[ $# -ge 2 ]] || fail "--port requires a value"
        PORT="$2"
        PORT_EXPLICIT="yes"
        NON_INTERACTIVE="yes"
        shift 2
        ;;
      --install-dir|-d)
        [[ $# -ge 2 ]] || fail "--install-dir requires a value"
        INSTALL_DIR="$2"
        NON_INTERACTIVE="yes"
        shift 2
        ;;
      --user|-u)
        [[ $# -ge 2 ]] || fail "--user requires a value"
        SERVICE_USER="$2"
        SERVICE_USER_EXPLICIT="yes"
        NON_INTERACTIVE="yes"
        shift 2
        ;;
      --yes|-y)
        ASSUME_YES="yes"
        NON_INTERACTIVE="yes"
        shift
        ;;
      --no-firewall)
        CONFIGURE_FIREWALL="no"
        NON_INTERACTIVE="yes"
        shift
        ;;
      --skip-build)
        SKIP_BUILD="yes"
        NON_INTERACTIVE="yes"
        shift
        ;;
      --npm-audit-fix)
        NPM_AUDIT_FIX="yes"
        NON_INTERACTIVE="yes"
        shift
        ;;
      --allow-proxmox-host-install)
        ALLOW_PROXMOX_HOST_INSTALL="yes"
        NON_INTERACTIVE="yes"
        shift
        ;;
      --grant-journal-access)
        GRANT_JOURNAL_ACCESS="yes"
        NON_INTERACTIVE="yes"
        shift
        ;;
      --existing-action|-a)
        [[ $# -ge 2 ]] || fail "--existing-action requires a value"
        case "$2" in
          update|reinstall|backup-config|remove|remove-app|remove-all|abort) EXISTING_ACTION="$2" ;;
          *) fail "--existing-action must be one of: update, reinstall, backup-config, remove, remove-app, remove-all, abort" ;;
        esac
        NON_INTERACTIVE="yes"
        shift 2
        ;;
      --update-config|-c)
        UPDATE_CONFIG="yes"
        NON_INTERACTIVE="yes"
        shift
        ;;
      --help|-h)
        usage
        exit 0
        ;;
      *)
        fail "Unknown option: $1"
        ;;
    esac
  done
}

read_from_tty() {
  local prompt="$1"
  local answer=""
  local tty_fd=""
  if [[ -t 0 ]]; then
    read -r -p "$prompt" answer || return 1
    printf '%s' "$answer"
    return 0
  fi
  if { exec {tty_fd}<>/dev/tty; } 2>/dev/null; then
    read -r -p "$prompt" answer <&"$tty_fd" || {
      exec {tty_fd}>&-
      return 1
    }
    exec {tty_fd}>&-
    printf '%s' "$answer"
    return 0
  fi
  return 1
}

read_from_tty_timeout() {
  local prompt="$1"
  local timeout="$2"
  local answer=""
  local key=""
  local deadline=0
  local remaining=0
  local tty_fd=""
  [[ "$timeout" =~ ^[1-9][0-9]*$ ]] || return 1
  if [[ -t 0 ]]; then
    tty_fd=0
  elif ! { exec {tty_fd}<>/dev/tty; } 2>/dev/null; then
    return 1
  fi
  deadline=$((SECONDS + timeout))
  while (( (remaining = deadline - SECONDS) > 0 )); do
    printf '\r\033[2K%s (auto update in %ss): %s' "$prompt" "$remaining" "$answer" >&"$tty_fd"
    key=""
    if IFS= read -r -s -n 1 -t 1 key <&"$tty_fd"; then
      case "$key" in
        "")
          printf '\r\033[2K%s: %s\n' "$prompt" "$answer" >&"$tty_fd"
          [[ "$tty_fd" == "0" ]] || exec {tty_fd}>&-
          printf '%s' "$answer"
          return 0
          ;;
        $'\b'|$'\177')
          [[ -z "$answer" ]] || answer="${answer%?}"
          ;;
        *) answer+="$key" ;;
      esac
    fi
  done
  printf '\r\033[2K' >&"$tty_fd"
  [[ "$tty_fd" == "0" ]] || exec {tty_fd}>&-
  return 1
}

ask() {
  local prompt="$1"
  local default="$2"
  local answer=""
  if [[ "$ASSUME_YES" == "yes" ]]; then
    printf '%s [%s]: %s\n' "$prompt" "$default" "$default" >&2
    printf '%s' "$default"
    return
  fi
  if answer="$(read_from_tty "${prompt} [${default}]: ")"; then
    :
  else
    printf '%s [%s]: %s\n' "$prompt" "$default" "$default" >&2
    answer="$default"
  fi
  printf '%s' "${answer:-$default}"
}

confirm() {
  local prompt="$1"
  local default="${2:-yes}"
  local suffix="[Y/n]"
  [[ "$default" == "no" ]] && suffix="[y/N]"
  if [[ "$ASSUME_YES" == "yes" ]]; then
    [[ "$default" == "yes" ]]
    return
  fi
  local answer=""
  if answer="$(read_from_tty "${prompt} ${suffix} ")"; then
    :
  else
    printf '%s %s %s\n' "$prompt" "$suffix" "$default" >&2
    answer="$default"
  fi
  answer="${answer:-$default}"
  [[ "$answer" =~ ^[Yy] ]]
}

confirm_npm_audit_fix() {

  local timeout="${1:-5}"
  local answer=""
  [[ "$timeout" =~ ^[1-9][0-9]*$ ]] || timeout="5"
  if [[ "$ASSUME_YES" == "yes" || ! -e /dev/tty ]]; then
    printf 'Run npm audit fix now? [y/N] (default in %ss): no\n' "$timeout" >&2
    return 1
  fi
  printf 'Run npm audit fix now? [y/N] (continuing with NO in %ss): ' "$timeout" >/dev/tty
  if IFS= read -r -t "$timeout" answer </dev/tty; then
    :
  else
    printf '\nNo answer received; continuing with NO.\n' >/dev/tty
    return 1
  fi
  answer="${answer:-no}"
  [[ "$answer" =~ ^[Yy]([Ee][Ss])?$ ]]
}

require_root() {
  [[ "${EUID}" -eq 0 ]] || fail "Run as root, for example: sudo ./install.sh"
  require_systemd
}

require_systemd() {
  command -v systemctl >/dev/null 2>&1 || fail "systemd is required but systemctl was not found"
  if [[ "$IS_WSL" == "yes" ]] && ! systemctl show-environment >/dev/null 2>&1; then
    fail "WSL requires systemd. Add [boot] and systemd=true to /etc/wsl.conf, run 'wsl.exe --shutdown' from Windows PowerShell, restart the distribution, and retry."
  fi
}

detect_wsl_environment() {
  local kernel_release=""
  if [[ -r "$WEBNAS_KERNEL_RELEASE_FILE" ]]; then
    IFS= read -r kernel_release < "$WEBNAS_KERNEL_RELEASE_FILE" || true
  fi
  if [[ -n "${WSL_INTEROP:-}" || "${kernel_release,,}" == *microsoft* ]]; then
    IS_WSL="yes"
    if [[ "${kernel_release,,}" == *wsl2* || "${kernel_release,,}" == *microsoft-standard* ]]; then
      WSL_VERSION="2"
    else
      WSL_VERSION="1"
    fi
  fi
}

validate_port() {
  [[ "$PORT" =~ ^[0-9]+$ ]] || fail "Port must be numeric"
  (( PORT >= 1 && PORT <= 65535 )) || fail "Port must be between 1 and 65535"
}

validate_install_dir() {
  [[ "$INSTALL_DIR" = /* ]] || fail "Installation directory must be an absolute path"
  [[ "$INSTALL_DIR" != "/" ]] || fail "Installation directory cannot be /"
  [[ "$INSTALL_DIR" != "/etc" && "$INSTALL_DIR" != "/usr" && "$INSTALL_DIR" != "/bin" && "$INSTALL_DIR" != "/lib" ]] || fail "Choose a dedicated installation directory, for example /opt/webnas"
}



assert_removable_path() {
  local path="$1"
  case "$path" in
    "$INSTALL_DIR"|"$CONFIG_DIR"|"$DATA_DIR"|"$LOG_DIR") return 0 ;;
    ""|/|/etc|/var|/opt|/home|/root|/mnt|/mnt/pve|/var/lib/vz|/etc/pve) ;;
  esac
  fail "Refusing unsafe removal path: ${path}"
}

detect_package_manager() {
  if command -v apt-get >/dev/null 2>&1; then
    PKG_MANAGER="apt"
  elif command -v dnf >/dev/null 2>&1; then
    PKG_MANAGER="dnf"
  elif command -v yum >/dev/null 2>&1; then
    PKG_MANAGER="yum"
  else
    fail "Supported package manager not found. Install dependencies manually and retry."
  fi
  ok "Detected package manager: ${PKG_MANAGER}"
}

detect_proxmox_host() {
  IS_PROXMOX="no"
  [[ -d /etc/pve ]] && IS_PROXMOX="yes"
  command -v pveversion >/dev/null 2>&1 && IS_PROXMOX="yes"
  for service in pvedaemon pveproxy pvestatd pve-cluster; do
    if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files "${service}.service" 2>/dev/null | grep -q "$service"; then
      IS_PROXMOX="yes"
    fi
  done
  if [[ "$IS_PROXMOX" == "yes" ]]; then
    section "Proxmox VE host detected"
    cat <<'EOF'
[WARN] WebNAS can run on a Proxmox VE host only in Proxmox Safe Mode.
[WARN] The installer will not modify Proxmox cluster, storage, network, /etc/pve,
[WARN] pve services, Proxmox repositories, or host reboot state.
[WARN] Production recommendation: install WebNAS inside a VM or LXC container.
EOF
    if [[ "$ALLOW_PROXMOX_HOST_INSTALL" != "yes" ]]; then
      fail "Refusing direct Proxmox host installation without --allow-proxmox-host-install"
    fi
    ok "Explicit Proxmox host installation flag accepted; Safe Mode remains enabled"
  fi
}

apt_error_is_unsubscribed_proxmox() {
  local output_file="$1"
  grep -qi 'enterprise\.proxmox\.com' "$output_file" &&
    grep -Eqi '401|403|unauthorized|forbidden|subscription|authentication required|does not have a release file|no longer has a release file|is not signed' "$output_file"
}

prepare_apt_sources_without_proxmox_enterprise() {
  local source_root="$APT_SOURCES_ROOT"
  local source_list=""
  local source_parts=""
  local candidate=""
  local removed="no"
  APT_TEMP_DIR="$(mktemp -d -t webnas-apt.XXXXXX)"
  source_list="${APT_TEMP_DIR}/sources.list"
  source_parts="${APT_TEMP_DIR}/sources.list.d"
  install -d -m 0700 "$source_parts"
  if [[ -f "${source_root}/sources.list" ]]; then
    grep -Evi 'enterprise\.proxmox\.com' "${source_root}/sources.list" > "$source_list" || true
    grep -qi 'enterprise\.proxmox\.com' "${source_root}/sources.list" && removed="yes" || true
  else
    : > "$source_list"
  fi
  if [[ -d "${source_root}/sources.list.d" ]]; then
    while IFS= read -r -d '' candidate; do
      grep -qi 'enterprise\.proxmox\.com' "$candidate" && removed="yes" || true
      case "$candidate" in
        *.sources)
          awk 'BEGIN { RS=""; ORS="\n\n" } tolower($0) !~ /enterprise\.proxmox\.com/ { print }' "$candidate" > "${source_parts}/$(basename "$candidate")"
          ;;
        *.list)
          grep -Evi 'enterprise\.proxmox\.com' "$candidate" > "${source_parts}/$(basename "$candidate")" || true
          ;;
      esac
      [[ -s "${source_parts}/$(basename "$candidate")" ]] || rm -f "${source_parts}/$(basename "$candidate")"
    done < <(find "${source_root}/sources.list.d" -maxdepth 1 -type f \( -name '*.list' -o -name '*.sources' \) -print0)
  fi
  if [[ "$removed" != "yes" ]]; then
    rm -rf -- "$APT_TEMP_DIR"
    APT_TEMP_DIR=""
    return 1
  fi
  APT_SOURCE_OPTIONS=(
    -o "Dir::Etc::sourcelist=${source_list}"
    -o "Dir::Etc::sourceparts=${source_parts}"
  )
}

apt_get() {
  NEEDRESTART_MODE=l DEBIAN_FRONTEND=noninteractive apt-get "${APT_SOURCE_OPTIONS[@]}" "$@"
}

apt_cache() {
  apt-cache "${APT_SOURCE_OPTIONS[@]}" "$@"
}

refresh_apt_metadata() {
  local output_file=""
  local exit_code="0"
  output_file="$(mktemp -t webnas-apt-output.XXXXXX)"
  if apt-get update 2>&1 | tee "$output_file"; then
    rm -f "$output_file"
    return 0
  else
    exit_code="${PIPESTATUS[0]}"
  fi
  if apt_error_is_unsubscribed_proxmox "$output_file" && prepare_apt_sources_without_proxmox_enterprise; then
    warn "Proxmox Enterprise requires an active subscription; retrying APT with that repository temporarily omitted"
    rm -f "$output_file"
    apt_get update
    return
  fi
  rm -f "$output_file"
  return "$exit_code"
}

refresh_apt_metadata_for_installation() {
  if [[ "$ACTION" == "update" ]]; then
    info "Skipping system repository metadata refresh during WebNAS update"
    return 0
  fi
  [[ "$APT_METADATA_REFRESHED" == "yes" ]] && return 0
  refresh_apt_metadata
  APT_METADATA_REFRESHED="yes"
}

ensure_download_tools() {
  local tool=""
  local missing=()
  for tool in curl wget tar rsync git ; do
    command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
  done
  if [[ ${#missing[@]} -eq 0 ]]; then
    ok "Download, archive, synchronization, and revision tools are available: curl, wget, tar, rsync, git"
    return
  fi

  section "Installing required download tools"
  info "Missing tools: ${missing[*]}"
  case "$PKG_MANAGER" in
    apt)
      refresh_apt_metadata_for_installation
      DEBIAN_FRONTEND=noninteractive apt_get install -y "${missing[@]}"
      ;;
    dnf)
      dnf install -y "${missing[@]}"
      ;;
    yum)
      yum install -y "${missing[@]}"
      ;;
  esac
  for tool in curl wget tar rsync git; do
    command -v "$tool" >/dev/null 2>&1 || fail "Required tool was not installed: ${tool}"
  done
  ok "Download, archive, and synchronization tools installed"
}

resolve_remote_source_revision() {
  local revision=""
  revision="$(git ls-remote "${REPO_URL}.git" refs/heads/main 2>/dev/null | awk 'NR == 1 {print $1}')"
  [[ "$revision" =~ ^[0-9a-fA-F]{40,64}$ ]] || fail "Could not resolve the WebNAS main branch revision"
  SOURCE_REVISION="$revision"
  ARCHIVE_URL="${REPO_URL}/archive/${SOURCE_REVISION}.tar.gz"
}

setup_nodesource_repository() {
  if [[ ${#APT_SOURCE_OPTIONS[@]} -eq 0 ]]; then
    curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash -
    return
  fi
  local apt_config="${APT_TEMP_DIR}/apt.conf"
  local previous_temp="$APT_TEMP_DIR"
  printf 'Dir::Etc::sourcelist "%s";\nDir::Etc::sourceparts "%s";\n' \
    "${APT_TEMP_DIR}/sources.list" "${APT_TEMP_DIR}/sources.list.d" > "$apt_config"
  curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | APT_CONFIG="$apt_config" bash -
  APT_TEMP_DIR=""
  APT_SOURCE_OPTIONS=()
  case "$previous_temp" in
    /tmp/webnas-apt.*|/var/tmp/webnas-apt.*) rm -rf -- "$previous_temp" ;;
    *) fail "Unexpected APT temporary path: ${previous_temp}" ;;
  esac
  prepare_apt_sources_without_proxmox_enterprise || fail "Could not rebuild temporary APT sources after configuring NodeSource"
  apt_get update
}

apt_python314_packages_available() {
  apt_cache show python3.14 python3.14-venv python3.14-dev >/dev/null 2>&1
}

os_release_value() {
  local key="$1"
  local value=""
  [[ -f "$WEBNAS_OS_RELEASE_FILE" ]] || return 1
  value="$(sed -n "s/^${key}=//p" "$WEBNAS_OS_RELEASE_FILE" | head -n 1)"
  value="${value%\"}"
  value="${value#\"}"
  printf '%s' "$value"
}

ensure_python314_apt_repository() {
  apt_python314_packages_available && return 0

  local distro_id=""
  local distro_codename=""
  distro_id="$(os_release_value ID || true)"
  distro_codename="$(os_release_value VERSION_CODENAME || true)"

  if [[ "$distro_id" != "ubuntu" || ( "$distro_codename" != "noble" && "$distro_codename" != "jammy" ) ]]; then
    fail "Python 3.14 packages are unavailable for ${distro_id:-this distribution} ${distro_codename:-unknown}. Configure a repository providing python3.14, python3.14-venv, and python3.14-dev, then retry."
  fi

  warn "Ubuntu ${distro_codename} does not provide Python 3.14 in its standard repositories; enabling ppa:deadsnakes/ppa"
  DEBIAN_FRONTEND=noninteractive apt_get install -y software-properties-common ca-certificates
  command -v add-apt-repository >/dev/null 2>&1 || fail "Could not install add-apt-repository required to enable Python 3.14 on Ubuntu"
  add-apt-repository -y -n ppa:deadsnakes/ppa || fail "Could not enable ppa:deadsnakes/ppa for Python 3.14"
  refresh_apt_metadata
  apt_python314_packages_available || fail "ppa:deadsnakes/ppa does not provide the required Python 3.14 packages for Ubuntu ${distro_codename} on this architecture"
}

install_dependencies() {
  section "Installing dependencies"
  case "$PKG_MANAGER" in
    apt)
      refresh_apt_metadata_for_installation
      ensure_python314_apt_repository
      DEBIAN_FRONTEND=noninteractive apt_get install -y \
        python3.14 python3.14-venv python3.14-dev || \
        fail "Python 3.14 packages were found, but python3.14, python3.14-venv, or python3.14-dev could not be installed. Inspect the APT error above and retry."
      DEBIAN_FRONTEND=noninteractive apt_get install -y \
        build-essential \
        libpam0g-dev rsync sudo curl wget ca-certificates tar gzip \
        passwd procps iproute2 ethtool traceroute screen quota util-linux udev nginx cifs-utils
      DEBIAN_FRONTEND=noninteractive apt_get install -y exfatprogs || warn "Optional exFAT tools could not be installed"
      ;;
    dnf)
      dnf install -y python3.14 python3.14-devel || \
        fail "Python 3.14 packages are unavailable. Enable a repository providing python3.14 and python3.14-devel, then retry."
      dnf install -y \
        gcc gcc-c++ make \
        pam-devel rsync sudo curl wget ca-certificates tar gzip \
        shadow-utils procps-ng iproute ethtool traceroute screen quota util-linux systemd-udev nginx cifs-utils
      dnf install -y ntfs-3g exfatprogs || warn "Optional NTFS/exFAT tools could not be installed"
      ;;
    yum)
      yum install -y python3.14 python3.14-devel || \
        fail "Python 3.14 packages are unavailable. Enable a repository providing python3.14 and python3.14-devel, then retry."
      yum install -y \
        gcc gcc-c++ make \
        pam-devel rsync sudo curl wget ca-certificates tar gzip \
        shadow-utils procps-ng iproute ethtool traceroute screen quota util-linux systemd-udev nginx cifs-utils
      yum install -y ntfs-3g exfatprogs || warn "Optional NTFS/exFAT tools could not be installed"
      ;;
  esac
  command -v mount.cifs >/dev/null 2>&1 || fail "cifs-utils was installed, but mount.cifs is unavailable; SMB/CIFS mounts cannot work"
  ok "SMB/CIFS runtime is ready (cifs-utils)"
  PYTHON_BIN="$(command -v python3.14 || true)"
  [[ -n "$PYTHON_BIN" ]] || fail "Python 3.14 is required, but python3.14 was not found after dependency installation"
  "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 14) else 1)' || fail "python3.14 does not provide the required Python 3.14 runtime"
  ok "Dependencies installed"
}

node_version_ok() {
  command -v node >/dev/null 2>&1 || return 1
  local version major minor
  # Do not execute JavaScript just to detect the runtime version. Some hardened
  # environments allow `node --version` while rejecting `node -p`, which used
  # to make a compatible installation appear unsupported.
  version="$(node --version 2>/dev/null || true)"
  version="${version#v}"
  version="${version#V}"
  major="${version%%.*}"
  minor="${version#*.}"
  minor="${minor%%.*}"
  [[ "$major" =~ ^[0-9]+$ && "$minor" =~ ^[0-9]+$ ]] || return 1
  (( major > 22 || (major == 22 && minor >= 12) || (major == 20 && minor >= 19) ))
}

setup_node_runtime() {
  if [[ "$SKIP_BUILD" == "yes" ]]; then
    return
  fi
  section "Preparing Node.js runtime"
  if node_version_ok && command -v npm >/dev/null 2>&1; then
    ok "Node.js $(node -v) is compatible"
    return
  fi
  warn "Node.js 20.19+ or 22.12+ is required for the frontend build"
  case "$PKG_MANAGER" in
    apt)
      setup_nodesource_repository
      DEBIAN_FRONTEND=noninteractive apt_get install -y nodejs
      ;;
    dnf)
      curl -fsSL "https://rpm.nodesource.com/setup_${NODE_MAJOR}.x" | bash -
      dnf install -y nodejs
      ;;
    yum)
      curl -fsSL "https://rpm.nodesource.com/setup_${NODE_MAJOR}.x" | bash -
      yum install -y nodejs
      ;;
  esac
  node_version_ok || fail "Node.js installation is still incompatible: $(node -v 2>/dev/null || printf 'not found')"
  command -v npm >/dev/null 2>&1 || fail "npm was not installed with Node.js"
  ok "Node.js $(node -v) ready"
}

print_runtime_diagnostics() {
  section "Runtime diagnostics"
  printf 'Expected port: %s\n' "$PORT" >&2
  printf 'Config file:   %s\n' "$CONFIG_FILE" >&2
  if [[ -f "$CONFIG_FILE" ]]; then
    printf '\nConfig server section:\n' >&2
    awk '
      /^server:/ {show=1}
      show {print}
      show && NR > 1 && /^[^[:space:]][^:]*:/ && !/^server:/ {exit}
    ' "$CONFIG_FILE" >&2 || true
  else
    printf 'Config file does not exist.\n' >&2
  fi
  printf '\nService status:\n' >&2
  systemctl status nginx webnas-backend-blue webnas-backend-green "$SERVICE_NAME" --no-pager -l >&2 || true
  printf '\nRecent service logs:\n' >&2
  journalctl -u nginx -u webnas-backend-blue -u webnas-backend-green -u "$SERVICE_NAME" -n 120 --no-pager >&2 || true
  if command -v ss >/dev/null 2>&1; then
    printf '\nListening TCP sockets:\n' >&2
    ss -ltnp >&2 || ss -ltn >&2 || true
  fi
  if command -v pgrep >/dev/null 2>&1; then
    printf '\nWebNAS/Python processes:\n' >&2
    pgrep -af 'webnas|uvicorn|python -m app.run' >&2 || true
  fi
}

prepare_source() {
  update_step download_repository completed
  update_step download_version started
  section "Preparing source"
  local script_dir=""
  local source_root=""
  local resolved_script_dir=""
  local resolved_install_dir=""
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
  source_root="$script_dir"
  if [[ -n "$script_dir" && -f "${script_dir}/../backend/app/main.py" && -f "${script_dir}/../frontend/package.json" ]]; then
    source_root="$(cd "${script_dir}/.." 2>/dev/null && pwd || true)"
  fi
  resolved_script_dir="$(readlink -f "$source_root" 2>/dev/null || printf '%s' "$source_root")"
  resolved_install_dir="$(readlink -f "$INSTALL_DIR" 2>/dev/null || printf '%s' "$INSTALL_DIR")"
  if [[ -n "$source_root" && -f "${source_root}/backend/app/main.py" && -f "${source_root}/frontend/package.json" ]]; then
    if [[ "$resolved_script_dir" == "$resolved_install_dir" && "$ACTION" != "install" ]]; then
      warn "Installer is running from the current application directory; downloading a fresh source archive before ${ACTION}"
    else
      SOURCE_DIR="$source_root"
      if [[ -d "${SOURCE_DIR}/.git" ]]; then
        SOURCE_REVISION="$(git -C "$SOURCE_DIR" rev-parse HEAD 2>/dev/null || true)"
      elif [[ -f "${SOURCE_DIR}/.webnas-revision" ]]; then
        SOURCE_REVISION="$(head -n 1 "${SOURCE_DIR}/.webnas-revision" 2>/dev/null || true)"
      fi
      ok "Using local repository: ${SOURCE_DIR}"
      update_step download_version completed
      return
    fi
  fi

  WORK_DIR="$(mktemp -d)"
  resolve_remote_source_revision
  info "Downloading WebNAS source archive"
  if command -v curl >/dev/null 2>&1; then
    curl --fail --location --progress-bar --output "${WORK_DIR}/webnas.tar.gz" "$ARCHIVE_URL"
  elif command -v wget >/dev/null 2>&1; then
    wget --progress=bar:force:noscroll --output-document="${WORK_DIR}/webnas.tar.gz" "$ARCHIVE_URL"
  else
    fail "curl or wget is required to download WebNAS"
  fi
  tar -xzf "${WORK_DIR}/webnas.tar.gz" -C "$WORK_DIR"
  SOURCE_DIR="$(find "$WORK_DIR" -maxdepth 1 -type d -name 'Algen-server-web-explorer-panel-*' | head -n 1)"
  [[ -n "$SOURCE_DIR" && -f "${SOURCE_DIR}/backend/app/main.py" ]] || fail "Downloaded archive does not contain WebNAS source"
  ok "Source downloaded"
  update_step download_version completed
}

prompt_install_dir() {
  validate_install_dir
}

os_release_value() {
  local key="$1"
  local line=""
  local value=""
  [[ -r "$WEBNAS_OS_RELEASE_FILE" ]] || return 1
  while IFS= read -r line; do
    [[ "$line" == "${key}="* ]] || continue
    value="${line#*=}"
    if [[ "$value" == \"*\" && "$value" == *\" ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
      value="${value:1:${#value}-2}"
    fi
    printf '%s' "$value"
    return 0
  done < "$WEBNAS_OS_RELEASE_FILE"
  return 1
}

print_environment_summary() {
  local os_name=""
  local os_id=""
  local os_version=""
  local python_version="not installed (Python 3.14 will be installed)"
  local node_version="not installed (Node.js ${NODE_MAJOR} will be installed)"
  os_name="$(os_release_value PRETTY_NAME || true)"
  os_id="$(os_release_value ID || true)"
  os_version="$(os_release_value VERSION_ID || true)"
  if [[ -z "$os_name" ]]; then
    os_name="${os_id:-unknown}${os_version:+ ${os_version}}"
  fi
  if [[ -n "$PYTHON_BIN" && -x "$PYTHON_BIN" ]]; then
    python_version="$($PYTHON_BIN --version 2>&1 || true)"
  fi
  if command -v node >/dev/null 2>&1; then
    node_version="Node.js $(node --version 2>/dev/null || printf 'unknown')"
  fi
  printf 'Operating system:  %s\n' "$os_name"
  printf 'Kernel:            %s\n' "$(uname -sr 2>/dev/null || printf 'unknown')"
  printf 'Architecture:      %s\n' "$(uname -m 2>/dev/null || printf 'unknown')"
  printf 'Package manager:   %s\n' "${PKG_MANAGER:-unknown}"
  if [[ "$IS_WSL" == "yes" ]]; then
    printf 'Environment:       Windows Subsystem for Linux (WSL%s)\n' "$WSL_VERSION"
  elif [[ "$IS_PROXMOX" == "yes" ]]; then
    printf 'Environment:       Proxmox VE host (Safe Mode)\n'
  else
    printf 'Environment:       standard Linux host\n'
  fi
  printf 'Python runtime:    %s\n' "$python_version"
  printf 'Node.js runtime:   %s\n' "$node_version"
}

prompt_configuration() {
  if [[ "$ACTION" == "update" || "$ACTION" == "reinstall" ]]; then
    validate_port
    section "Operation summary"
    print_environment_summary
    printf 'Action:           %s\n' "$ACTION"
    printf 'Port:             %s\n' "$PORT"
    printf 'Install dir:      %s\n' "$INSTALL_DIR"
    printf 'Service user:     %s\n' "$SERVICE_USER"
    printf 'Update config:    %s\n' "$UPDATE_CONFIG"
    printf 'Config backup:    yes\n'
    printf 'Build frontend:   %s\n' "$([[ "$SKIP_BUILD" == "yes" ]] && printf 'no' || printf 'yes')"
    return
  fi
  if [[ "$NON_INTERACTIVE" != "yes" ]]; then
    section "Configuration"
    info "Values in brackets are defaults; press Enter to accept them. [Y/n] defaults to Yes."
    PORT="$(ask "Application port" "$PORT")"
    SERVICE_USER="$(ask "Service user" "$SERVICE_USER")"
    confirm "Start service after installation?" "yes" && START_SERVICE="yes" || START_SERVICE="no"
    confirm "Enable systemd autostart?" "yes" && ENABLE_AUTOSTART="yes" || ENABLE_AUTOSTART="no"
    if command -v ufw >/dev/null 2>&1 || command -v firewall-cmd >/dev/null 2>&1; then
      confirm "Configure firewall for port ${PORT}?" "yes" && CONFIGURE_FIREWALL="yes" || CONFIGURE_FIREWALL="no"
    else
      CONFIGURE_FIREWALL="no"
    fi
  fi

  validate_port

  section "Summary"
  print_environment_summary
  printf 'Port:             %s\n' "$PORT"
  printf 'Install dir:      %s\n' "$INSTALL_DIR"
  printf 'Service user:     %s\n' "$SERVICE_USER"
  printf 'Start now:        %s\n' "$START_SERVICE"
  printf 'Autostart:        %s\n' "$ENABLE_AUTOSTART"
  printf 'Firewall:         %s\n' "$CONFIGURE_FIREWALL"
  printf 'Update config:    %s\n' "$UPDATE_CONFIG"
  printf 'Build frontend:   %s\n' "$([[ "$SKIP_BUILD" == "yes" ]] && printf 'no' || printf 'yes')"
  if [[ "$ASSUME_YES" != "yes" ]]; then
    confirm "Continue installation?" "yes" || fail "Installation cancelled"
  fi
}

load_existing_installation_defaults() {
  local configured_port=""
  local install_owner=""
  if [[ "$PORT_EXPLICIT" != "yes" && -f "$CONFIG_FILE" ]]; then
    configured_port="$(awk '
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
    ' "$CONFIG_FILE" 2>/dev/null || true)"
    if [[ "$configured_port" =~ ^[0-9]+$ ]] && (( configured_port >= 1 && configured_port <= 65535 )); then
      PORT="$configured_port"
      info "Using port ${PORT} from existing configuration"
    else
      warn "Could not read a valid port from ${CONFIG_FILE}; keeping ${PORT}"
    fi
  fi
  if [[ "$SERVICE_USER_EXPLICIT" != "yes" ]]; then
    install_owner="$(stat -c '%U' "$INSTALL_DIR" 2>/dev/null || true)"
    if [[ -n "$install_owner" && "$install_owner" != "root" ]] && id "$install_owner" >/dev/null 2>&1; then
      SERVICE_USER="$install_owner"
      info "Using service file owner ${SERVICE_USER} from existing installation"
    fi
  fi
}

handle_existing_installation() {
  if [[ ! -d "$INSTALL_DIR" ]]; then
    ACTION="install"
    UPDATE_CONFIG="yes"
    section "Installation check"
    ok "No existing installation found in ${INSTALL_DIR}"
    return
  fi

  section "Existing installation detected"
  warn "${INSTALL_DIR} already exists"
  load_existing_installation_defaults
  if [[ -n "$EXISTING_ACTION" ]]; then
    ACTION="$EXISTING_ACTION"
    [[ "$ACTION" != "abort" ]] || fail "Installation cancelled"
    prompt_config_update
    return
  fi
  if [[ "$ASSUME_YES" == "yes" ]]; then
    ACTION="update"
    UPDATE_CONFIG="no"
    info "Automatic update selected; existing configuration will be backed up and preserved"
    return
  fi
  printf 'Choose action (automatic update starts after %s seconds):\n' "$EXISTING_ACTION_TIMEOUT"
  printf '  1) Update application (backup and keep config) [default]\n'
  printf '  2) Reinstall application (clean app files; keep config, data, and logs)\n'
  printf '  3) Backup config only\n'
  printf '  4) Remove app (keep config, data, and logs)\n'
  printf '  5) Remove app and all files\n'
  printf '  6) Abort\n'
  local choice=""
  if choice="$(read_from_tty_timeout "Action [1]" "$EXISTING_ACTION_TIMEOUT")"; then
    :
  else
    printf '\n' >&2
    info "No action selected within ${EXISTING_ACTION_TIMEOUT} seconds; starting update with configuration backup"
    choice="1"
  fi
  case "${choice:-1}" in
    1)
      ACTION="update"
      UPDATE_CONFIG="no"
      ;;
    2)
      ACTION="reinstall"
      UPDATE_CONFIG="no"
      ;;
    3) ACTION="backup-config" ;;
    4) ACTION="remove-app" ;;
    5) ACTION="remove-all" ;;
    6) fail "Installation cancelled" ;;
    *) fail "Invalid choice" ;;
  esac
}

prompt_config_update() {
  case "$ACTION" in
    update)
      if [[ "$UPDATE_CONFIG" == "yes" ]]; then
        return
      fi
      if [[ "$ASSUME_YES" == "yes" || "$NON_INTERACTIVE" == "yes" ]]; then
        UPDATE_CONFIG="no"
        return
      fi
      confirm "Update configuration file ${CONFIG_FILE}?" "no" && UPDATE_CONFIG="yes" || UPDATE_CONFIG="no"
      ;;
    reinstall)
      if [[ "$UPDATE_CONFIG" == "yes" ]]; then
        warn "Reinstall will regenerate config because --update-config was explicitly provided"
      else
        UPDATE_CONFIG="no"
      fi
      ;;
    install|remove)
      UPDATE_CONFIG="yes"
      ;;
  esac
}

backup_config_only() {
  if [[ "$ACTION" != "backup-config" ]]; then
    return 1
  fi
  section "Backing up config"
  if [[ ! -f "$CONFIG_FILE" ]]; then
    fail "Config file does not exist: ${CONFIG_FILE}"
  fi
  local stamp backup_dir
  stamp="$(date +%Y%m%d-%H%M%S)"
  install -d -m 0750 "$BACKUP_ROOT"
  backup_dir="$(mktemp -d "${BACKUP_ROOT}/${stamp}-manual.XXXXXX")"
  chmod 0750 "$backup_dir"
  cp -a "$CONFIG_FILE" "${backup_dir}/config.yaml"
  printf 'action=backup-config\ncreated_at=%s\ninstall_dir=%s\n' "$(date --iso-8601=seconds)" "$INSTALL_DIR" > "${backup_dir}/installer-state"
  chmod 0640 "${backup_dir}/config.yaml" "${backup_dir}/installer-state"
  ok "Config backup created: ${backup_dir}/config.yaml"
  return 0
}

backup_before_application_change() {
  case "$ACTION" in
    update|reinstall|remove) ;;
    *) return ;;
  esac
  section "Backing up existing installation"
  local stamp backup_dir
  stamp="$(date +%Y%m%d-%H%M%S)"
  install -d -m 0750 "$BACKUP_ROOT"
  backup_dir="$(mktemp -d "${BACKUP_ROOT}/${stamp}-${ACTION}.XXXXXX")"
  chmod 0750 "$backup_dir"
  LAST_BACKUP_DIR="$backup_dir"
  if [[ -f "$CONFIG_FILE" ]]; then
    cp -a "$CONFIG_FILE" "${backup_dir}/config.yaml"
    chmod 0640 "${backup_dir}/config.yaml"
  else
    warn "No existing config found at ${CONFIG_FILE}; the installer will create one"
  fi
  if [[ "$ACTION" == "reinstall" || "$ACTION" == "remove" ]]; then
    [[ -d "$INSTALL_DIR" ]] && rsync -a "$INSTALL_DIR/" "${backup_dir}/app/"
  fi
  [[ -f "$SERVICE_FILE" ]] && cp -a "$SERVICE_FILE" "${backup_dir}/webnas.service"
  [[ -f "$PAM_SERVICE_FILE" ]] && cp -a "$PAM_SERVICE_FILE" "${backup_dir}/webnas.pam"
  printf 'action=%s\ncreated_at=%s\ninstall_dir=%s\nconfig_file=%s\n' "$ACTION" "$(date --iso-8601=seconds)" "$INSTALL_DIR" "$CONFIG_FILE" > "${backup_dir}/installer-state"
  chmod 0640 "${backup_dir}/installer-state"
  ok "Safety backup created: ${backup_dir}"
}

remove_existing_installation() {
  if [[ "$ACTION" != "reinstall" && "$ACTION" != "remove" ]]; then
    return
  fi
  section "Preparing clean application reinstall"
  stop_usb_automount_instances
  validate_install_dir
  assert_removable_path "$INSTALL_DIR"
  rm -rf --one-file-system "$INSTALL_DIR"
  ok "Removed old application files from ${INSTALL_DIR}; config, data, and logs remain untouched"
}

stop_usb_automount_instances() {
  systemctl stop 'webnas-usb-mount@*.service' 2>/dev/null || true
  if [[ -x "${INSTALL_DIR}/scripts/usb_automount.py" ]]; then
    "$PYTHON_BIN" "${INSTALL_DIR}/scripts/usb_automount.py" cleanup 2>/dev/null || \
      warn "One or more busy USB filesystems could not be unmounted"
  fi
}

remove_usb_automount_integration() {
  stop_usb_automount_instances
  rm -f "$USB_SERVICE_FILE" "$USB_UDEV_RULE_FILE"
  systemctl daemon-reload 2>/dev/null || true
  if command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload-rules 2>/dev/null || true
  fi
}

start_existing_usb_filesystems() {
  [[ -f "$USB_SERVICE_FILE" ]] || return 0
  command -v udevadm >/dev/null 2>&1 || return 0
  local sys_block kname properties
  for sys_block in /sys/class/block/*; do
    [[ -e "$sys_block" ]] || continue
    kname="${sys_block##*/}"
    [[ "$kname" =~ ^[A-Za-z0-9._+-]{1,128}$ ]] || continue
    properties="$(udevadm info --query=property --name="/dev/${kname}" 2>/dev/null || true)"
    if grep -qx 'ID_BUS=usb' <<< "$properties" && grep -qx 'ID_FS_USAGE=filesystem' <<< "$properties"; then
      systemctl start --no-block "webnas-usb-mount@${kname}.service" 2>/dev/null || \
        warn "Could not queue USB automount for /dev/${kname}"
    fi
  done
}

remove_app_only() {
  if [[ "$ACTION" != "remove-app" && "$ACTION" != "remove-all" ]]; then
    return 1
  fi
  section "Removing application"
  validate_install_dir
  assert_removable_path "$INSTALL_DIR"
  assert_removable_path "$CONFIG_DIR"
  assert_removable_path "$DATA_DIR"
  assert_removable_path "$LOG_DIR"
  if [[ "$ACTION" == "remove-all" ]]; then
    REMOVE_SCOPE="all"
    confirm "Remove application, config, data, and logs?" "no" || fail "Installation cancelled"
  else
    REMOVE_SCOPE="app"
    confirm "Remove application files from ${INSTALL_DIR} only?" "no" || fail "Installation cancelled"
  fi
  remove_usb_automount_integration
  systemctl disable --now "${SERVICE_NAME}.service" 2>/dev/null || true
  systemctl disable --now webnas-backend-blue.service webnas-backend-green.service 2>/dev/null || true
  rm -f "$SERVICE_FILE" "$BACKEND_BLUE_FILE" "$BACKEND_GREEN_FILE" "$NGINX_CONFIG_FILE"
  rm -f "$PAM_SERVICE_FILE"
  systemctl daemon-reload 2>/dev/null || true
  systemctl reload nginx 2>/dev/null || true
  rm -rf --one-file-system "$INSTALL_DIR"
  ok "Removed application files from ${INSTALL_DIR}"
  case "$REMOVE_SCOPE" in
    app)
      ok "Kept config, data, and logs in ${CONFIG_DIR}, ${DATA_DIR}, ${LOG_DIR}"
      ;;
    app-config)
      rm -rf --one-file-system "$CONFIG_DIR"
      ok "Removed config from ${CONFIG_DIR}"
      ok "Kept data and logs in ${DATA_DIR}, ${LOG_DIR}"
      ;;
    app-data-logs)
      rm -rf --one-file-system "$DATA_DIR" "$LOG_DIR"
      ok "Removed data and logs from ${DATA_DIR}, ${LOG_DIR}"
      ok "Kept config in ${CONFIG_DIR}"
      ;;
    all)
      rm -rf --one-file-system "$CONFIG_DIR" "$DATA_DIR" "$LOG_DIR"
      ok "Removed config, data, and logs from ${CONFIG_DIR}, ${DATA_DIR}, ${LOG_DIR}"
      ;;
  esac
  return 0
}

ensure_service_user() {
  section "Preparing system user"
  if id "$SERVICE_USER" >/dev/null 2>&1; then
    SERVICE_GROUP="$(id -gn "$SERVICE_USER")"
    ok "User exists: ${SERVICE_USER}"
  else
    useradd --system --user-group --home "$INSTALL_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
    SERVICE_GROUP="$(id -gn "$SERVICE_USER")"
    ok "Created system user: ${SERVICE_USER}"
  fi
  if getent group systemd-journal >/dev/null 2>&1; then
    if [[ "$GRANT_JOURNAL_ACCESS" == "yes" ]]; then
      usermod -a -G systemd-journal "$SERVICE_USER"
      ok "Granted ${SERVICE_USER} read access through systemd-journal"
    elif ! id -nG "$SERVICE_USER" | tr ' ' '\n' | grep -Fxq systemd-journal; then
      warn "System journal access was not granted. Re-run with --grant-journal-access or add ${SERVICE_USER} to systemd-journal manually."
    fi
  else
    warn "The systemd-journal group is unavailable; journal visibility depends on this distribution's journal ACL policy."
  fi
}

copy_application() {
  section "Copying application"
  APP_COPY_STARTED="yes"
  install -d -m 0755 "$INSTALL_DIR"
  rsync -a --delete \
    --exclude ".git" \
    --exclude "backend/.venv" \
    --exclude "frontend/node_modules" \
    --exclude "frontend/dist" \
    "$SOURCE_DIR/" "$INSTALL_DIR/"
  if [[ "$SOURCE_REVISION" =~ ^[0-9a-fA-F]{40,64}$ ]]; then
    printf '%s\n' "$SOURCE_REVISION" > "${INSTALL_DIR}/.webnas-revision"
  else
    warn "Could not record the installed source revision; update status will request an initial refresh"
  fi
  chown -R "${SERVICE_USER}:${SERVICE_USER}" "$INSTALL_DIR"
  chmod 0755 "$INSTALL_DIR"
  ok "Application copied to ${INSTALL_DIR}"
}

prepare_runtime_directories() {
  install -d -m 0755 "$CONFIG_DIR" "$DATA_DIR" "$LOG_DIR"
  install -d -m 1777 "${DATA_DIR}/tmp"
  # Users may traverse verified mounted resources, but only the privileged
  # backend can create or replace mount-point directories.
  chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "$DATA_DIR" "$LOG_DIR"
}

write_config() {
  update_step update_configuration started
  # Runtime paths must exist even when an update preserves config.yaml. A
  # missing data directory otherwise leaves every SQLite-backed scheduler in
  # a permanent retry loop after the release handover.
  install -d -o root -g root -m 0711 /mnt/webnas /mnt/webnas/mnt
  prepare_runtime_directories
  if [[ ("$ACTION" == "update" || "$ACTION" == "reinstall") && -f "$CONFIG_FILE" && "$UPDATE_CONFIG" != "yes" ]]; then
    ok "Keeping existing config: ${CONFIG_FILE}"
    update_step update_configuration skipped
    return
  fi
  section "Writing configuration"
  if [[ -f "$CONFIG_FILE" && "$UPDATE_CONFIG" != "yes" ]]; then
    ok "Keeping existing config: ${CONFIG_FILE}"
    update_step update_configuration skipped
    return
  fi
  if [[ -f "$CONFIG_FILE" ]]; then
    cp -a "$CONFIG_FILE" "${CONFIG_FILE}.bak.$(date +%Y%m%d-%H%M%S)"
    warn "Existing config backed up before config update"
  fi
  local secret
  secret="$("${INSTALL_DIR}/backend/.venv/bin/python" - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)"
  sed \
    -e "s/port: 5000/port: ${PORT}/" \
    -e "s/change-this-secret-during-install/${secret}/" \
    "${INSTALL_DIR}/config.example.yaml" > "$CONFIG_FILE"
  chmod 0640 "$CONFIG_FILE"
  chown "root:${SERVICE_GROUP}" "$CONFIG_FILE" || chown root:root "$CONFIG_FILE"
  ok "Config written: ${CONFIG_FILE}"
  update_step update_configuration completed
}

write_pam_service() {
  section "Installing PAM service"
  if [[ -f /etc/pam.d/common-auth && -f /etc/pam.d/common-account ]]; then
    cat > "$PAM_SERVICE_FILE" <<'EOF'
# PAM policy for WebNAS local Linux user login.
auth      include common-auth
account   include common-account
password  include common-password
session   include common-session
EOF
  elif [[ -f /etc/pam.d/system-auth ]]; then
    cat > "$PAM_SERVICE_FILE" <<'EOF'
# PAM policy for WebNAS local Linux user login.
auth      include system-auth
account   include system-auth
password  include system-auth
session   include system-auth
EOF
  else
    fail "Could not find a supported PAM base policy in /etc/pam.d"
  fi
  chmod 0644 "$PAM_SERVICE_FILE"
  [[ -f "$PAM_SERVICE_FILE" ]] || fail "PAM service file was not created: ${PAM_SERVICE_FILE}"
  ok "PAM service installed: ${PAM_SERVICE_FILE}"
  info "PAM service '${SERVICE_NAME}' is available when System authentication mode is enabled"
}

setup_python() {
  update_step install_backend_dependencies started
  section "Installing Python packages"
  "$PYTHON_BIN" - <<'PY'
import sys

required = (3, 14)
if sys.version_info[:2] != required:
    version = ".".join(str(part) for part in sys.version_info[:3])
    raise SystemExit(f"WebNAS requires Python {required[0]}.{required[1]}; found Python {version}")
PY
  "$PYTHON_BIN" -m venv "${INSTALL_DIR}/backend/.venv" || fail "Could not create a Python 3.14 virtualenv. Install python3.14-venv or the distribution equivalent."
  "${INSTALL_DIR}/backend/.venv/bin/pip" install --upgrade pip wheel
  "${INSTALL_DIR}/backend/.venv/bin/pip" install -r "${INSTALL_DIR}/backend/requirements.txt"
  ok "Python virtualenv ready"
  update_step install_backend_dependencies completed
}

print_npm_funding_packages() {
  local funding_report="$1"
  "$PYTHON_BIN" - "$funding_report" <<'PY'
import json
import re
import sys


def clean(value, fallback="unknown"):
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or "")).strip()
    return text[:300] or fallback


def funding_urls(value):
    if isinstance(value, str):
        return [clean(value, "")]
    if isinstance(value, dict):
        return [clean(value.get("url"), "")]
    if isinstance(value, list):
        urls = []
        for entry in value:
            urls.extend(funding_urls(entry))
        return urls
    return []


try:
    with open(sys.argv[1], encoding="utf-8") as stream:
        report = json.load(stream)
except (OSError, TypeError, ValueError, json.JSONDecodeError):
    raise SystemExit(0)

packages = []


def collect(dependencies):
    if not isinstance(dependencies, dict):
        return
    for package_name, details in dependencies.items():
        if not isinstance(details, dict):
            continue
        urls = list(dict.fromkeys(url for url in funding_urls(details.get("funding")) if url))
        if urls:
            packages.append((clean(package_name), clean(details.get("version"), "version unknown"), urls))
        collect(details.get("dependencies"))


collect(report.get("dependencies", {}))
if not packages:
    raise SystemExit(0)

unique_packages = []
seen = set()
for package in packages:
    identity = (package[0], package[1])
    if identity not in seen:
        seen.add(identity)
        unique_packages.append(package)

for package_name, version, urls in sorted(unique_packages, key=lambda item: item[0].lower()):
    print(f"  - {package_name}@{version}")
    for url in urls:
        print(f"    Funding: {url}")
PY
}

print_npm_audit_vulnerabilities() {
  local audit_report="$1"
  "$PYTHON_BIN" - "$audit_report" <<'PY'
import json
import re
import sys


def clean(value, fallback="unknown"):
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or "")).strip()
    return text[:300] or fallback


try:
    with open(sys.argv[1], encoding="utf-8") as stream:
        report = json.load(stream)
except (OSError, TypeError, ValueError, json.JSONDecodeError):
    raise SystemExit(0)

vulnerabilities = report.get("vulnerabilities", {})
if not isinstance(vulnerabilities, dict) or not vulnerabilities:
    raise SystemExit(0)

severity_order = {"critical": 0, "high": 1, "moderate": 2, "low": 3, "info": 4}


def sort_key(item):
    details = item[1] if isinstance(item[1], dict) else {}
    severity = str(details.get("severity", "")).lower()
    return severity_order.get(severity, 5), item[0].lower()


items = sorted(
    vulnerabilities.items(),
    key=sort_key,
)
print("Vulnerable frontend packages:")
for package_name, details in items:
    if not isinstance(details, dict):
        continue
    severity = clean(details.get("severity"))
    dependency_type = "direct dependency" if details.get("isDirect") else "transitive dependency"
    affected_range = clean(details.get("range"), "unspecified")
    print(f"  - {clean(package_name)}: {severity} ({dependency_type}); affected: {affected_range}")

    advisories = []
    for advisory in details.get("via", []):
        if not isinstance(advisory, dict):
            continue
        title = clean(advisory.get("title"), "")
        url = clean(advisory.get("url"), "")
        label = " — ".join(value for value in (title, url) if value)
        if label and label not in advisories:
            advisories.append(label)
    for advisory in advisories:
        print(f"    Issue: {advisory}")

    fix = details.get("fixAvailable")
    if isinstance(fix, dict):
        target = f"{clean(fix.get('name'), clean(package_name))}@{clean(fix.get('version'))}"
        suffix = " (major-version update)" if fix.get("isSemVerMajor") else ""
        print(f"    Fix: update to {target}{suffix}")
    elif fix is True:
        print("    Fix: available through npm audit fix")
    else:
        print("    Fix: no automatic fix currently available")
PY
}

build_frontend() {
  local audit_report=""
  local funding_report=""
  local vulnerability_count=""
  local frontend_dir="${INSTALL_DIR}/frontend"
  local staging_dist="${INSTALL_DIR}/frontend/dist.next"
  local active_dist="${INSTALL_DIR}/frontend/dist"
  if [[ "$SKIP_BUILD" == "yes" ]]; then
    fail "--skip-build cannot be used for install, update, or reinstall because it can leave an incompatible frontend bundle"
  fi
  update_step install_frontend_dependencies started
  section "Installing frontend dependencies"
  (cd "$frontend_dir" && npm ci)
  funding_report="$(mktemp -t webnas-npm-fund.XXXXXX)"
  if (cd "$frontend_dir" && npm fund --json > "$funding_report"); then
    print_npm_funding_packages "$funding_report"
  else
    warn "npm could not list packages looking for funding; continuing installation"
  fi
  rm -f -- "$funding_report"
  audit_report="$(mktemp -t webnas-npm-audit.XXXXXX)"
  (cd "${INSTALL_DIR}/frontend" && npm audit --json > "$audit_report") || true
  vulnerability_count="$("$PYTHON_BIN" - "$audit_report" <<'PY'
import json
import sys

try:
    report = json.load(open(sys.argv[1], encoding="utf-8"))
    print(int(report.get("metadata", {}).get("vulnerabilities", {}).get("total", 0)))
except (OSError, TypeError, ValueError, json.JSONDecodeError):
    print("")
PY
)"

  if [[ "$vulnerability_count" =~ ^[1-9][0-9]*$ ]]; then
    warn "npm found ${vulnerability_count} frontend package vulnerabilities"
    print_npm_audit_vulnerabilities "$audit_report"
    if [[ "$NPM_AUDIT_FIX" == "yes" ]] || confirm_npm_audit_fix 5; then
      info "Running npm audit fix"
      (cd "${INSTALL_DIR}/frontend" && npm audit fix)
      ok "npm audit fix completed"
    else
      warn "npm audit fix skipped"
    fi
  elif [[ "$vulnerability_count" == "0" ]]; then
    ok "npm audit found no frontend package vulnerabilities"
  else
    warn "npm audit could not determine the frontend vulnerability count; continuing without automatic changes"
  fi
  rm -f -- "$audit_report"
  update_step install_frontend_dependencies completed
  update_step build_frontend started
  section "Building frontend"
  rm -rf --one-file-system "$staging_dist"
  (cd "$frontend_dir" && npm run build -- --outDir "$(basename "$staging_dist")")
  "$PYTHON_BIN" "${INSTALL_DIR}/scripts/verify_frontend_build.py" "$staging_dist"

  # Publish every hashed asset before atomically replacing index.html. The old
  # index therefore always references available files throughout an update.
  install -d -m 0755 "$active_dist"
  rsync -a --exclude "index.html" "$staging_dist/" "$active_dist/"
  install -m 0644 "$staging_dist/index.html" "$active_dist/index.html.next"
  mv -f "$active_dist/index.html.next" "$active_dist/index.html"
  rm -rf --one-file-system "$staging_dist"
  "$PYTHON_BIN" "${INSTALL_DIR}/scripts/verify_frontend_build.py" "$active_dist"
  chown -R "${SERVICE_USER}:${SERVICE_USER}" "$frontend_dir"
  ok "Frontend built and activated with a matching index"
  update_step build_frontend completed
}

prepare_release() {
  local application_root="$INSTALL_DIR"
  local release_id=""
  local release_dir=""
  local current_runtime=""
  release_id="$(date +%Y%m%d-%H%M%S)-$$"
  release_dir="${application_root}/releases/${release_id}"
  [[ "$release_dir" == "${application_root}/releases/"* ]] || fail "Invalid release staging path"
  section "Preparing isolated release ${release_id}"
  install -d -m 0755 "${application_root}/releases" "$release_dir"

  # Reuse the normal copy/build helpers against a brand-new directory.  The
  # running release and its virtualenv/dist are never modified by rsync.
  INSTALL_DIR="$release_dir"
  copy_application
  setup_python
  write_pam_service
  build_frontend
  write_config
  INSTALL_DIR="$application_root"

  # Existing browser sessions may still request lazily loaded chunks from the
  # previous index. Keep those immutable hashes available in the candidate;
  # the new index still references only the freshly built assets.
  local previous_assets="${application_root}/current/frontend/dist/assets"
  [[ -d "$previous_assets" ]] || previous_assets="${application_root}/frontend/dist/assets"
  if [[ -d "$previous_assets" ]]; then
    rsync -a --ignore-existing \
      "${previous_assets}/" \
      "${release_dir}/frontend/dist/assets/"
  fi

  [[ -x "${release_dir}/backend/.venv/bin/python" ]] || fail "Candidate virtualenv is missing"
  [[ -f "${release_dir}/frontend/dist/index.html" ]] || fail "Candidate frontend is missing"
  ACTIVE_RELEASE="$release_dir"
  current_runtime="${release_dir}/scripts/webnas_release.py"
  [[ -f "$current_runtime" ]] || fail "Release activation helper is missing"

  section "Validating and switching release"
  "$PYTHON_BIN" "$current_runtime" \
    --root "$application_root" \
    --release "$release_dir" \
    --config "$CONFIG_FILE" \
    --public-port "$PORT" \
    --service-user "$SERVICE_USER"

  # Keep stable administrative entry points outside release directories.
  install -m 0755 "${release_dir}/uninstall.sh" "${application_root}/uninstall.sh"
  install -m 0755 "${release_dir}/scripts/webnas_release.py" "${application_root}/webnas_release.py"
  chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "$release_dir"
  ok "Release activated: ${release_dir}"
}

install_release_integrations() {
  local application_root="$INSTALL_DIR"
  [[ -L "${application_root}/current" ]] || fail "Active release link is missing"
  if [[ "$IS_WSL" == "yes" ]]; then
    warn "Skipping Linux udev USB automount on WSL; use Windows drive mounts below /mnt or attach disks with wsl.exe --mount"
    return 0
  fi
  INSTALL_DIR="${application_root}/current"
  install_usb_automount
  INSTALL_DIR="$application_root"
}

effective_transport_scheme() {
  local transport_state="${DATA_DIR}/settings/transport.json"
  if [[ -f "$transport_state" ]]; then
    if grep -Eq '"use_https"[[:space:]]*:[[:space:]]*true' "$transport_state"; then
      printf '%s' "https"
    else
      printf '%s' "http"
    fi
    return
  fi
  if grep -Eq '^\s*use_https:\s*true\s*$' "$CONFIG_FILE"; then
    printf '%s' "https"
  else
    printf '%s' "http"
  fi
}

validate_release_installation() {
  section "Validation"
  local scheme=""
  local curl_options=(--fail --silent --show-error --max-time 3)
  scheme="$(effective_transport_scheme)"
  [[ "$scheme" != "https" ]] || curl_options+=(--insecure)
  systemctl is-active --quiet nginx || fail "Stable nginx gateway is not active"
  [[ -L "${INSTALL_DIR}/current" ]] || fail "Active release symlink is unavailable"
  [[ -f "${INSTALL_DIR}/current/frontend/dist/index.html" ]] || fail "Active frontend is unavailable"
  curl "${curl_options[@]}" "${scheme}://127.0.0.1:${PORT}/api/health" >/dev/null || fail "Public health endpoint did not survive the release handover"
  ok "Gateway, active backend, frontend and public health endpoint are ready"
}

install_usb_automount() {
  section "Installing USB automount"
  USB_AUTOMOUNT_STAGE="checking required files and commands"
  [[ -f "${INSTALL_DIR}/scripts/usb_automount.py" ]] || fail "USB automount helper is missing"
  [[ -f "${INSTALL_DIR}/packaging/99-webnas-usb-automount.rules" ]] || fail "USB automount udev rule is missing"
  command -v udevadm >/dev/null 2>&1 || fail "udevadm is required for USB automount"
  command -v findmnt >/dev/null 2>&1 || fail "findmnt is required for USB automount"

  USB_AUTOMOUNT_STAGE="setting helper ownership and permissions"
  chown root:root "${INSTALL_DIR}/scripts/usb_automount.py"
  chmod 0755 "${INSTALL_DIR}/scripts/usb_automount.py"
  USB_AUTOMOUNT_STAGE="creating mount and runtime directories"
  install -d -o root -g root -m 0755 "$USB_MOUNT_ROOT"
  install -d -o root -g root -m 0700 "$USB_STATE_DIR"
  USB_AUTOMOUNT_STAGE="installing the udev rule"
  install -D -o root -g root -m 0644 \
    "${INSTALL_DIR}/packaging/99-webnas-usb-automount.rules" "$USB_UDEV_RULE_FILE"

  USB_AUTOMOUNT_STAGE="writing the systemd template unit"
  cat > "$USB_SERVICE_FILE" <<EOF
[Unit]
Description=WebNAS automount for USB filesystem /dev/%I
BindsTo=dev-%i.device
After=dev-%i.device
Before=umount.target
Conflicts=umount.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=${PYTHON_BIN} ${INSTALL_DIR}/scripts/usb_automount.py mount /dev/%I
ExecStop=${PYTHON_BIN} ${INSTALL_DIR}/scripts/usb_automount.py unmount /dev/%I
TimeoutStartSec=45
TimeoutStopSec=45
User=root
Group=root
RuntimeDirectory=webnas
RuntimeDirectoryMode=0755
RuntimeDirectoryPreserve=yes
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ReadWritePaths=${USB_MOUNT_ROOT} /run/webnas
ProtectHome=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
LockPersonality=yes
SystemCallArchitectures=native
CapabilityBoundingSet=CAP_SYS_ADMIN CAP_DAC_OVERRIDE CAP_CHOWN CAP_FOWNER
EOF
  USB_AUTOMOUNT_STAGE="setting systemd unit permissions"
  chmod 0644 "$USB_SERVICE_FILE"
  USB_AUTOMOUNT_STAGE="reloading systemd units"
  systemctl daemon-reload
  USB_AUTOMOUNT_STAGE="reloading udev rules"
  udevadm control --reload-rules

  # SYSTEMD_WANTS is evaluated when a device first becomes active. Start a
  # matching instance explicitly for USB filesystems already present now.
  USB_AUTOMOUNT_STAGE="starting services for connected USB filesystems"
  start_existing_usb_filesystems
  USB_AUTOMOUNT_STAGE="completed"
  ok "USB filesystems will be mounted below ${USB_MOUNT_ROOT}"
}

configure_firewall() {
  [[ "$CONFIGURE_FIREWALL" == "yes" ]] || return
  if [[ "$IS_WSL" == "yes" ]]; then
    warn "Skipping ufw/firewalld configuration on WSL; manage inbound access with Windows Defender Firewall"
    return 0
  fi
  section "Configuring firewall"
  if command -v ufw >/dev/null 2>&1 && ufw status | grep -qi "Status: active"; then
    ufw allow "${PORT}/tcp"
    ok "ufw allows ${PORT}/tcp"
  elif command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld; then
    firewall-cmd --permanent --add-port="${PORT}/tcp"
    firewall-cmd --reload
    ok "firewalld allows ${PORT}/tcp"
  else
    warn "No active ufw/firewalld detected"
  fi
}

print_finish() {
  local scheme ip_addr
  scheme="$(effective_transport_scheme)"
  ip_addr="$(hostname -I 2>/dev/null | awk '{print $1}')"
  [[ -n "$ip_addr" ]] || ip_addr="IP_SERWERA"
  section "Installation complete"
  printf '%b[OK]%b WebNAS panel: %s://%s:%s\n' "$GREEN" "$RESET" "$scheme" "$ip_addr" "$PORT"
  cat <<EOF

Helpful commands:
  systemctl status nginx webnas-backend-blue webnas-backend-green
  journalctl -u 'webnas-backend-*' -f
  cat ${DATA_DIR}/settings/deployment.json
  ${INSTALL_DIR}/uninstall.sh

Installer URL:
  ${RAW_INSTALL_URL}
EOF
}

status_operation_name() {
  case "$ACTION" in
    update) printf '%s' "Aktualizacja" ;;
    reinstall) printf '%s' "Ponowna instalacja" ;;
    backup-config) printf '%s' "Kopia konfiguracji" ;;
    remove|remove-app|remove-all) printf '%s' "Operacja usuwania" ;;
    *) printf '%s' "Instalacja" ;;
  esac
}

print_final_status() {
  local code="$1"
  local operation
  operation="$(status_operation_name)"
  if [[ "$code" -eq 0 && "$INSTALL_COMPLETED" == "yes" ]]; then
    printf '\n%b[STATUS: OK]%b %s zakończona pomyślnie.\n' "$GREEN" "$RESET" "$operation"
  elif [[ "$code" -ne 0 ]]; then
    printf '\n%b[STATUS: BŁĄD]%b Wystąpił błąd podczas operacji: %s.\n' "$RED" "$RESET" "$operation" >&2
    printf 'Etap: %s | kod wyjścia: %s\n' "$CURRENT_STEP" "$code" >&2
  fi
}

cleanup() {
  [[ -n "$WORK_DIR" && -d "$WORK_DIR" ]] && rm -rf "$WORK_DIR"
  if [[ -n "$APT_TEMP_DIR" && -d "$APT_TEMP_DIR" ]]; then
    case "$APT_TEMP_DIR" in
      /tmp/webnas-apt.*|/var/tmp/webnas-apt.*) rm -rf -- "$APT_TEMP_DIR" ;;
      *) warn "Refusing to remove unexpected APT temporary path: ${APT_TEMP_DIR}" ;;
    esac
  fi
  return 0
}

restore_failed_reinstall() {
  [[ "$ACTION" == "reinstall" && "$APP_COPY_STARTED" == "yes" ]] || return 1
  [[ -n "$LAST_BACKUP_DIR" && -d "${LAST_BACKUP_DIR}/app" ]] || return 1
  warn "Reinstall failed; restoring the previous application from ${LAST_BACKUP_DIR}"
  validate_install_dir
  assert_removable_path "$INSTALL_DIR"
  rm -rf --one-file-system "$INSTALL_DIR" || return 1
  install -d -m 0755 "$INSTALL_DIR" || return 1
  rsync -a "${LAST_BACKUP_DIR}/app/" "$INSTALL_DIR/" || return 1
  [[ ! -f "${LAST_BACKUP_DIR}/config.yaml" ]] || cp -a "${LAST_BACKUP_DIR}/config.yaml" "$CONFIG_FILE" || return 1
  [[ ! -f "${LAST_BACKUP_DIR}/webnas.service" ]] || cp -a "${LAST_BACKUP_DIR}/webnas.service" "$SERVICE_FILE" || return 1
  [[ ! -f "${LAST_BACKUP_DIR}/webnas.pam" ]] || cp -a "${LAST_BACKUP_DIR}/webnas.pam" "$PAM_SERVICE_FILE" || return 1
  systemctl daemon-reload 2>/dev/null || true
  if [[ -x "${INSTALL_DIR}/scripts/usb_automount.py" ]]; then
    start_existing_usb_filesystems
  else
    rm -f "$USB_SERVICE_FILE" "$USB_UDEV_RULE_FILE"
    systemctl daemon-reload 2>/dev/null || true
    command -v udevadm >/dev/null 2>&1 && udevadm control --reload-rules 2>/dev/null || true
  fi
  if [[ "$SERVICE_WAS_ACTIVE" == "yes" ]]; then
    systemctl start "$SERVICE_NAME" 2>/dev/null || warn "Previous application was restored, but the service could not be restarted automatically"
  fi
  ok "Previous application and configuration restored"
  return 0
}

cleanup_failed_install() {
  trap - EXIT
  cleanup
  if [[ "$INSTALL_COMPLETED" == "yes" ]]; then
    return 0
  fi
  if [[ -n "$ACTIVE_RELEASE" && -d "$ACTIVE_RELEASE" ]]; then
    local active_target=""
    active_target="$(readlink -f "${INSTALL_DIR}/current" 2>/dev/null || true)"
    if [[ "$active_target" != "$ACTIVE_RELEASE" && "$ACTIVE_RELEASE" == "${INSTALL_DIR}/releases/"* ]]; then
      warn "Removing failed candidate release ${ACTIVE_RELEASE}"
      rm -rf --one-file-system "$ACTIVE_RELEASE"
    fi
  fi
  if [[ "$ACTION" == "update" && -n "$LAST_BACKUP_DIR" && -f "${LAST_BACKUP_DIR}/config.yaml" && "$UPDATE_CONFIG" == "yes" ]]; then
    cp -a "${LAST_BACKUP_DIR}/config.yaml" "$CONFIG_FILE" 2>/dev/null || warn "Could not restore the previous configuration after the failed update"
  fi
  if [[ "$ACTION" == "remove" ]]; then
    remove_usb_automount_integration
    rm -f "$SERVICE_FILE"
    systemctl daemon-reload 2>/dev/null || true
  fi
  return 0
}

on_exit() {
  local code="$?"
  trap - EXIT
  set +e
  if [[ "$code" -eq 0 ]]; then
    cleanup
  else
    cleanup_failed_install
  fi
  print_final_status "$code"
  exit "$code"
}
trap on_exit EXIT


print_initial_local_admin() {
  section "Authentication"
  local helper="${INSTALL_DIR}/current/scripts/consume_local_bootstrap.py"
  local python="${INSTALL_DIR}/current/backend/.venv/bin/python"
  [[ -x "$python" && -f "$helper" ]] || fail "Local administrator bootstrap helper is unavailable"
  if command -v runuser >/dev/null 2>&1; then
    runuser -u "$SERVICE_USER" -- env \
      WEBNAS_CONFIG="$CONFIG_FILE" \
      PYTHONPATH="${INSTALL_DIR}/current/backend" \
      "$python" "$helper" "chris" "1"
  else
    fail "runuser is required to initialize the Local database administrator"
  fi
  info "Default authentication mode: Local database. Default account: chris / password: 1. Change it immediately after the first login."
  info "PAM and optional LDAP can be enabled later in Settings -> Administration -> Authentication."
}

main() {
  parse_args "$@"
  detect_wsl_environment
  banner
  require_root
  prompt_install_dir
  handle_existing_installation
  if backup_config_only; then
    INSTALL_COMPLETED="yes"
    return
  fi
  if remove_app_only; then
    INSTALL_COMPLETED="yes"
    return
  fi
  detect_package_manager
  detect_proxmox_host
  ensure_download_tools
  prepare_source
  update_step verify_files started
  [[ -f "${SOURCE_DIR}/backend/app/main.py" && -f "${SOURCE_DIR}/frontend/package.json" && -f "${SOURCE_DIR}/backend/requirements.txt" ]] || fail "Downloaded source is incomplete"
  update_step verify_files completed
  prompt_configuration
  install_dependencies
  setup_node_runtime
  backup_before_application_change
  ensure_service_user
  # The active backend remains untouched while the complete candidate release
  # (Python dependencies and frontend included) is prepared and validated.
  prepare_release
  install_release_integrations
  configure_firewall
  validate_release_installation
  print_initial_local_admin
  INSTALL_COMPLETED="yes"
  print_finish
}

main "$@"
