#!/usr/bin/env bash
set -Eeuo pipefail

SERVICE_NAME="webnas"
REPO_URL="https://github.com/chmajster/Algen-server-web-explorer-panel"
ARCHIVE_URL="${REPO_URL}/archive/refs/heads/main.tar.gz"
RAW_INSTALL_URL="https://raw.githubusercontent.com/chmajster/Algen-server-web-explorer-panel/main/install.sh"

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

CONFIG_DIR="/etc/webnas"
CONFIG_FILE="${CONFIG_DIR}/config.yaml"
DATA_DIR="/var/lib/webnas"
LOG_DIR="/var/log/webnas"
BACKUP_ROOT="/var/backups/webnas"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
PAM_SERVICE_FILE="/etc/pam.d/${SERVICE_NAME}"
USB_SERVICE_FILE="/etc/systemd/system/webnas-usb-mount@.service"
USB_UDEV_RULE_FILE="/etc/udev/rules.d/99-webnas-usb-automount.rules"
USB_MOUNT_ROOT="/media/webnas-usb"
USB_STATE_DIR="/run/webnas/usb-mounts"
WORK_DIR=""
SOURCE_DIR=""
APT_TEMP_DIR=""
APT_SOURCE_OPTIONS=()
APT_SOURCES_ROOT="/etc/apt"
CURRENT_STEP="startup"
APP_COPY_STARTED="no"
INSTALL_COMPLETED="no"
LAST_BACKUP_DIR=""
SERVICE_WAS_ACTIVE="no"

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
  --port PORT             Application port (default: 5000)
  --install-dir PATH      Installation directory (default: /opt/webnas)
  --user USER             System user for the service (default: webnas)
  --yes                   Non-interactive mode; accept defaults
  --no-firewall           Do not configure ufw/firewalld
  --skip-build            Skip frontend build
  --allow-proxmox-host-install
                          Explicitly allow restricted installation on a Proxmox VE host
  --grant-journal-access  Add the service user to systemd-journal for system log access
  --existing-action ACTION
                          Existing install action: update, reinstall, backup-config, remove, remove-app, remove-all, or abort
  --update-config         Also regenerate config.yaml during update actions
  --help                  Show this help
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

on_error() {
  local line="$1"
  local code="$2"
  trap - ERR
  printf '\n%b[ERROR]%b Installation failed at line %s with exit code %s.\n' "$RED" "$RESET" "$line" "$code" >&2
  printf 'Failed step: %s\n' "$CURRENT_STEP" >&2
  printf 'Check the command output directly above this error.\n' >&2
  if [[ -f "$SERVICE_FILE" ]]; then
    printf 'Systemd service exists; inspect: journalctl -u %s -n 80 --no-pager\n' "$SERVICE_NAME" >&2
  else
    printf 'Systemd service was not installed yet, so journalctl may have no entries.\n' >&2
  fi
  cleanup_failed_install
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
      --port)
        [[ $# -ge 2 ]] || fail "--port requires a value"
        PORT="$2"
        PORT_EXPLICIT="yes"
        NON_INTERACTIVE="yes"
        shift 2
        ;;
      --install-dir)
        [[ $# -ge 2 ]] || fail "--install-dir requires a value"
        INSTALL_DIR="$2"
        NON_INTERACTIVE="yes"
        shift 2
        ;;
      --user)
        [[ $# -ge 2 ]] || fail "--user requires a value"
        SERVICE_USER="$2"
        SERVICE_USER_EXPLICIT="yes"
        NON_INTERACTIVE="yes"
        shift 2
        ;;
      --yes)
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
      --existing-action)
        [[ $# -ge 2 ]] || fail "--existing-action requires a value"
        case "$2" in
          update|reinstall|backup-config|remove|remove-app|remove-all|abort) EXISTING_ACTION="$2" ;;
          *) fail "--existing-action must be one of: update, reinstall, backup-config, remove, remove-app, remove-all, abort" ;;
        esac
        NON_INTERACTIVE="yes"
        shift 2
        ;;
      --update-config)
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
  if [[ -e /dev/tty ]]; then
    read -r -p "$prompt" answer </dev/tty || return 1
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
  [[ -e /dev/tty ]] || return 1
  [[ "$timeout" =~ ^[1-9][0-9]*$ ]] || return 1
  deadline=$((SECONDS + timeout))
  while (( (remaining = deadline - SECONDS) > 0 )); do
    printf '\r\033[2K%s (auto update in %ss): %s' "$prompt" "$remaining" "$answer" >/dev/tty
    key=""
    if IFS= read -r -s -n 1 -t 1 key </dev/tty; then
      case "$key" in
        "")
          printf '\r\033[2K%s: %s\n' "$prompt" "$answer" >/dev/tty
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
  printf '\r\033[2K' >/dev/tty
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
  command -v systemctl >/dev/null 2>&1 || fail "systemd is required but systemctl was not found"
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
  apt-get "${APT_SOURCE_OPTIONS[@]}" "$@"
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

ensure_download_tools() {
  local tool=""
  local missing=()
  for tool in curl wget tar rsync; do
    command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
  done
  if [[ ${#missing[@]} -eq 0 ]]; then
    ok "Download, archive, and synchronization tools are available: curl, wget, tar, rsync"
    return
  fi

  section "Installing required download tools"
  info "Missing tools: ${missing[*]}"
  case "$PKG_MANAGER" in
    apt)
      refresh_apt_metadata
      DEBIAN_FRONTEND=noninteractive apt_get install -y "${missing[@]}"
      ;;
    dnf)
      dnf install -y "${missing[@]}"
      ;;
    yum)
      yum install -y "${missing[@]}"
      ;;
  esac
  for tool in curl wget tar rsync; do
    command -v "$tool" >/dev/null 2>&1 || fail "Required tool was not installed: ${tool}"
  done
  ok "Download, archive, and synchronization tools installed"
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

install_dependencies() {
  section "Installing dependencies"
  case "$PKG_MANAGER" in
    apt)
      refresh_apt_metadata
      DEBIAN_FRONTEND=noninteractive apt_get install -y \
        python3 python3-pip python3-venv python3-dev build-essential \
        libpam0g-dev rsync sudo curl wget ca-certificates tar gzip \
        passwd procps iproute2 ethtool traceroute screen quota util-linux udev
      DEBIAN_FRONTEND=noninteractive apt_get install -y ntfs-3g || warn "Optional NTFS tools could not be installed"
      DEBIAN_FRONTEND=noninteractive apt_get install -y exfatprogs || warn "Optional exFAT tools could not be installed"
      ;;
    dnf)
      dnf install -y \
        python3 python3-pip python3-devel gcc gcc-c++ make \
        pam-devel rsync sudo curl wget ca-certificates tar gzip \
        shadow-utils procps-ng iproute ethtool traceroute screen quota util-linux systemd-udev
      dnf install -y ntfs-3g exfatprogs || warn "Optional NTFS/exFAT tools could not be installed"
      ;;
    yum)
      yum install -y \
        python3 python3-pip python3-devel gcc gcc-c++ make \
        pam-devel rsync sudo curl wget ca-certificates tar gzip \
        shadow-utils procps-ng iproute ethtool traceroute screen quota util-linux systemd-udev
      yum install -y ntfs-3g exfatprogs || warn "Optional NTFS/exFAT tools could not be installed"
      ;;
  esac
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
  systemctl status "$SERVICE_NAME" --no-pager -l >&2 || true
  printf '\nRecent service logs:\n' >&2
  journalctl -u "$SERVICE_NAME" -n 120 --no-pager >&2 || true
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
  section "Preparing source"
  local script_dir=""
  local resolved_script_dir=""
  local resolved_install_dir=""
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
  resolved_script_dir="$(readlink -f "$script_dir" 2>/dev/null || printf '%s' "$script_dir")"
  resolved_install_dir="$(readlink -f "$INSTALL_DIR" 2>/dev/null || printf '%s' "$INSTALL_DIR")"
  if [[ -n "$script_dir" && -f "${script_dir}/backend/app/main.py" && -f "${script_dir}/frontend/package.json" ]]; then
    if [[ "$resolved_script_dir" == "$resolved_install_dir" && "$ACTION" != "install" ]]; then
      warn "Installer is running from the current application directory; downloading a fresh source archive before ${ACTION}"
    else
      SOURCE_DIR="$script_dir"
      ok "Using local repository: ${SOURCE_DIR}"
      return
    fi
  fi

  WORK_DIR="$(mktemp -d)"
  info "Downloading WebNAS source archive"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$ARCHIVE_URL" -o "${WORK_DIR}/webnas.tar.gz"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "${WORK_DIR}/webnas.tar.gz" "$ARCHIVE_URL"
  else
    fail "curl or wget is required to download WebNAS"
  fi
  tar -xzf "${WORK_DIR}/webnas.tar.gz" -C "$WORK_DIR"
  SOURCE_DIR="$(find "$WORK_DIR" -maxdepth 1 -type d -name 'Algen-server-web-explorer-panel-*' | head -n 1)"
  [[ -n "$SOURCE_DIR" && -f "${SOURCE_DIR}/backend/app/main.py" ]] || fail "Downloaded archive does not contain WebNAS source"
  ok "Source downloaded"
}

prompt_install_dir() {
  validate_install_dir
}

prompt_configuration() {
  if [[ "$ACTION" == "update" || "$ACTION" == "reinstall" ]]; then
    validate_port
    section "Operation summary"
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
    if [[ "$ASSUME_YES" != "yes" ]]; then
      confirm "Start new installation?" "yes" || fail "Installation cancelled"
    fi
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
    /usr/bin/python3 "${INSTALL_DIR}/scripts/usb_automount.py" cleanup 2>/dev/null || \
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
  rm -f "$SERVICE_FILE"
  rm -f "$PAM_SERVICE_FILE"
  systemctl daemon-reload 2>/dev/null || true
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
  local source_revision=""
  if [[ -d "${SOURCE_DIR}/.git" ]] && command -v git >/dev/null 2>&1; then
    source_revision="$(git -C "$SOURCE_DIR" rev-parse HEAD 2>/dev/null || true)"
  fi
  if [[ -z "$source_revision" ]] && command -v git >/dev/null 2>&1; then
    source_revision="$(git ls-remote "${REPO_URL}.git" refs/heads/main 2>/dev/null | awk 'NR == 1 {print $1}')"
  fi
  if [[ "$source_revision" =~ ^[0-9a-fA-F]{40,64}$ ]]; then
    printf '%s\n' "$source_revision" > "${INSTALL_DIR}/.webnas-revision"
  else
    warn "Could not record the installed source revision; update status will request an initial refresh"
  fi
  chown -R "${SERVICE_USER}:${SERVICE_USER}" "$INSTALL_DIR"
  chmod 0755 "$INSTALL_DIR"
  ok "Application copied to ${INSTALL_DIR}"
}

write_config() {
  # This also runs during updates that preserve config.
  install -d -o root -g root -m 0711 /mnt/webnas /mnt/webnas/mnt
  if [[ ("$ACTION" == "update" || "$ACTION" == "reinstall") && -f "$CONFIG_FILE" && "$UPDATE_CONFIG" != "yes" ]]; then
    ok "Keeping existing config: ${CONFIG_FILE}"
    return
  fi
  section "Writing configuration"
  install -d -m 0755 "$CONFIG_DIR" "$DATA_DIR" "$LOG_DIR"
  install -d -m 1777 "${DATA_DIR}/tmp"
  # Users may traverse verified mounted resources, but only the privileged
  # backend can create or replace mount-point directories.
  chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "$DATA_DIR" "$LOG_DIR"
  if [[ -f "$CONFIG_FILE" && "$UPDATE_CONFIG" != "yes" ]]; then
    ok "Keeping existing config: ${CONFIG_FILE}"
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
  info "Panel login uses local Linux users authenticated through PAM service '${SERVICE_NAME}'"
}

setup_python() {
  section "Installing Python packages"
  python3 - <<'PY'
import sys

required = (3, 11)
if sys.version_info < required:
    version = ".".join(str(part) for part in sys.version_info[:3])
    raise SystemExit(f"WebNAS requires Python {required[0]}.{required[1]} or newer; found Python {version}")
PY
  python3 -m venv "${INSTALL_DIR}/backend/.venv"
  "${INSTALL_DIR}/backend/.venv/bin/pip" install --upgrade pip wheel
  "${INSTALL_DIR}/backend/.venv/bin/pip" install -r "${INSTALL_DIR}/backend/requirements.txt"
  ok "Python virtualenv ready"
}

build_frontend() {
  local audit_report=""
  local vulnerability_count=""
  if [[ "$SKIP_BUILD" == "yes" ]]; then
    warn "Frontend build skipped"
    return
  fi
  section "Building frontend"
  (cd "${INSTALL_DIR}/frontend" && npm install)
  audit_report="$(mktemp -t webnas-npm-audit.XXXXXX)"
  (cd "${INSTALL_DIR}/frontend" && npm audit --json > "$audit_report") || true
  vulnerability_count="$(python3 - "$audit_report" <<'PY'
import json
import sys

try:
    report = json.load(open(sys.argv[1], encoding="utf-8"))
    print(int(report.get("metadata", {}).get("vulnerabilities", {}).get("total", 0)))
except (OSError, TypeError, ValueError, json.JSONDecodeError):
    print("")
PY
)"
  rm -f -- "$audit_report"
  warn "npm found ${vulnerability_count} frontend package vulnerabilities"

  if [[ "$vulnerability_count" =~ ^[1-9][0-9]*$ ]]; then
    if confirm_npm_audit_fix 5; then
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
  (cd "${INSTALL_DIR}/frontend" && npm run build)
  chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}/frontend"
  ok "Frontend built"
}

write_service() {
  section "Installing systemd service"
  cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=WebNAS web administration panel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}/backend
Environment=PYTHONPATH=${INSTALL_DIR}/backend
Environment=WEBNAS_CONFIG=${CONFIG_FILE}
ExecStart=${INSTALL_DIR}/backend/.venv/bin/python -m app.run
Restart=on-failure
RestartSec=3
# WebNAS uses PAM and drops file-operation workers into authenticated Linux
# user contexts. Package Center also performs validated apt/dnf/systemd actions.
User=root
Group=root
NoNewPrivileges=false
PrivateTmp=true
# A read-only system tree would prevent the package manager from writing its
# database and installing files. Package Center never accepts commands from UI.
ProtectSystem=false
# File workers drop privileges to the authenticated account and must retain
# normal Unix write access to that account's allowed home directory.
ProtectHome=false
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
# Validated package-manager jobs must be able to install distribution packages
# containing required SUID/SGID helpers (for example cifs-utils/mount.cifs).
RestrictSUIDSGID=false
LockPersonality=true
MemoryDenyWriteExecute=true
SystemCallArchitectures=native
ReadWritePaths=${DATA_DIR} ${LOG_DIR} /home /mnt/webnas ${INSTALL_DIR}

[Install]
WantedBy=multi-user.target
EOF
  chmod 0644 "$SERVICE_FILE"
  systemctl daemon-reload
  if [[ "$ENABLE_AUTOSTART" == "yes" ]]; then
    systemctl enable "$SERVICE_NAME"
    ok "Autostart enabled"
  else
    systemctl disable "$SERVICE_NAME" 2>/dev/null || true
    warn "Autostart disabled"
  fi
}

install_usb_automount() {
  section "Installing USB automount"
  [[ -f "${INSTALL_DIR}/scripts/usb_automount.py" ]] || fail "USB automount helper is missing"
  [[ -f "${INSTALL_DIR}/packaging/99-webnas-usb-automount.rules" ]] || fail "USB automount udev rule is missing"
  command -v udevadm >/dev/null 2>&1 || fail "udevadm is required for USB automount"
  command -v findmnt >/dev/null 2>&1 || fail "findmnt is required for USB automount"

  chown root:root "${INSTALL_DIR}/scripts/usb_automount.py"
  chmod 0755 "${INSTALL_DIR}/scripts/usb_automount.py"
  install -d -o root -g root -m 0755 "$USB_MOUNT_ROOT"
  install -d -o root -g root -m 0700 "$USB_STATE_DIR"
  install -D -o root -g root -m 0644 \
    "${INSTALL_DIR}/packaging/99-webnas-usb-automount.rules" "$USB_UDEV_RULE_FILE"

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
ExecStart=/usr/bin/python3 ${INSTALL_DIR}/scripts/usb_automount.py mount /dev/%I
ExecStop=/usr/bin/python3 ${INSTALL_DIR}/scripts/usb_automount.py unmount /dev/%I
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
  chmod 0644 "$USB_SERVICE_FILE"
  systemctl daemon-reload
  udevadm control --reload-rules

  # SYSTEMD_WANTS is evaluated when a device first becomes active. Start a
  # matching instance explicitly for USB filesystems already present now.
  start_existing_usb_filesystems
  ok "USB filesystems will be mounted below ${USB_MOUNT_ROOT}"
}

configure_firewall() {
  [[ "$CONFIGURE_FIREWALL" == "yes" ]] || return
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

install_uninstaller() {
  if [[ -f "${INSTALL_DIR}/uninstall.sh" ]]; then
    chmod 0755 "${INSTALL_DIR}/uninstall.sh"
  fi
}

start_service() {
  [[ "$START_SERVICE" == "yes" ]] || return
  section "Starting service"
  systemctl restart "$SERVICE_NAME"
  ok "Service started"
}

validate_installation() {
  section "Validation"
  if command -v rsync >/dev/null 2>&1; then ok "rsync available"; else fail "rsync is missing"; fi
  if systemctl list-unit-files "${SERVICE_NAME}.service" >/dev/null 2>&1; then ok "systemd sees ${SERVICE_NAME}.service"; else fail "systemd service not visible"; fi
  if [[ "$START_SERVICE" == "yes" ]]; then
    if systemctl is-active --quiet "$SERVICE_NAME"; then
      ok "Backend service is active"
    else
      print_runtime_diagnostics
      fail "Backend service is not active"
    fi
    local service_uid
    service_uid="$(systemctl show "$SERVICE_NAME" -p MainPID --value | xargs -r -I{} ps -o euid= -p {} 2>/dev/null | tr -d ' ')"
    if [[ "$service_uid" == "0" ]]; then
      ok "Backend service runs as root for PAM and per-user impersonation"
    else
      print_runtime_diagnostics
      fail "Backend service must run as root for local PAM authentication; current euid=${service_uid:-unknown}"
    fi
    if command -v ss >/dev/null 2>&1; then
      local port_ready="no"
      for _ in {1..20}; do
        if ss -ltn | awk '{print $4}' | grep -Eq "(:|\\])${PORT}$"; then
          port_ready="yes"
          break
        fi
        sleep 1
      done
      if [[ "$port_ready" == "yes" ]]; then
        ok "Port ${PORT} is listening"
      else
        print_runtime_diagnostics
        fail "Port ${PORT} is not listening"
      fi
    fi
    if command -v curl >/dev/null 2>&1; then
      local scheme="http"
      grep -Eq '^[[:space:]]*use_https:[[:space:]]*true' "$CONFIG_FILE" 2>/dev/null && scheme="https"
      local health_ready="no"
      local health_url="${scheme}://127.0.0.1:${PORT}/api/health"
      local health_output=""
      for _ in {1..10}; do
        health_output="$(curl -kfsS "$health_url" 2>&1 || true)"
        if printf '%s' "$health_output" | grep -q '"status"'; then
          health_ready="yes"
          break
        fi
        sleep 1
      done
      if [[ "$health_ready" == "yes" ]]; then
        ok "Healthcheck responds"
      else
        printf 'Healthcheck URL: %s\n' "$health_url" >&2
        printf 'Last healthcheck output:\n%s\n' "${health_output:-<empty>}" >&2
        print_runtime_diagnostics
        fail "Healthcheck failed for ${health_url}"
      fi
    fi
  else
    warn "Runtime validation skipped because service was not started"
  fi
}

print_finish() {
  local ip_addr
  ip_addr="$(hostname -I 2>/dev/null | awk '{print $1}')"
  [[ -n "$ip_addr" ]] || ip_addr="IP_SERWERA"
  section "Installation complete"
  printf '%b[OK]%b WebNAS panel: http://%s:%s\n' "$GREEN" "$RESET" "$ip_addr" "$PORT"
  cat <<EOF

Helpful commands:
  systemctl status ${SERVICE_NAME}
  systemctl restart ${SERVICE_NAME}
  journalctl -u ${SERVICE_NAME} -f
  ${INSTALL_DIR}/uninstall.sh

Installer URL:
  ${RAW_INSTALL_URL}
EOF
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
  if restore_failed_reinstall; then
    return 0
  fi
  if [[ "$ACTION" == "update" && -n "$LAST_BACKUP_DIR" && -f "${LAST_BACKUP_DIR}/config.yaml" && "$UPDATE_CONFIG" == "yes" ]]; then
    cp -a "${LAST_BACKUP_DIR}/config.yaml" "$CONFIG_FILE" 2>/dev/null || warn "Could not restore the previous configuration after the failed update"
  fi
  case "$ACTION" in
    install|remove)
      if [[ "$APP_COPY_STARTED" == "yes" && -d "$INSTALL_DIR" ]]; then
        warn "Cleaning up partial application files from ${INSTALL_DIR}"
        validate_install_dir
        rm -rf --one-file-system "$INSTALL_DIR"
      fi
      ;;
  esac
  if [[ "$ACTION" == "install" || "$ACTION" == "remove" ]]; then
    remove_usb_automount_integration
    rm -f "$SERVICE_FILE"
    systemctl daemon-reload 2>/dev/null || true
  fi
  return 0
}
trap cleanup EXIT

main() {
  parse_args "$@"
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
  prompt_configuration
  install_dependencies
  setup_node_runtime
  backup_before_application_change
  ensure_service_user
  if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    SERVICE_WAS_ACTIVE="yes"
  fi
  systemctl stop "$SERVICE_NAME" 2>/dev/null || true
  remove_existing_installation
  copy_application
  setup_python
  write_config
  write_pam_service
  build_frontend
  install_uninstaller
  write_service
  install_usb_automount
  configure_firewall
  start_service
  validate_installation
  INSTALL_COMPLETED="yes"
  print_finish
}

main "$@"
