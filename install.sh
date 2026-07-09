#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="webnas"
SERVICE_NAME="webnas"
REPO_URL="https://github.com/chmajster/Algen-server-web-explorer-panel"
ARCHIVE_URL="${REPO_URL}/archive/refs/heads/main.tar.gz"
RAW_INSTALL_URL="https://raw.githubusercontent.com/chmajster/Algen-server-web-explorer-panel/main/install.sh"

PORT="5000"
INSTALL_DIR="/opt/webnas"
SERVICE_USER="webnas"
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
ALLOW_PROXMOX_HOST_INSTALL="no"
IS_PROXMOX="no"

CONFIG_DIR="/etc/webnas"
CONFIG_FILE="${CONFIG_DIR}/config.yaml"
DATA_DIR="/var/lib/webnas"
LOG_DIR="/var/log/webnas"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
WORK_DIR=""
SOURCE_DIR=""
CURRENT_STEP="startup"
APP_COPY_STARTED="no"
INSTALL_COMPLETED="no"

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
  --existing-action ACTION
                          Existing install action: update, backup-update, remove, remove-app, or abort
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
      --existing-action)
        [[ $# -ge 2 ]] || fail "--existing-action requires a value"
        case "$2" in
          update|backup-update|remove|remove-app|abort) EXISTING_ACTION="$2" ;;
          *) fail "--existing-action must be one of: update, backup-update, remove, remove-app, abort" ;;
        esac
        NON_INTERACTIVE="yes"
        shift 2
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

install_dependencies() {
  section "Installing dependencies"
  case "$PKG_MANAGER" in
    apt)
      apt-get update
      DEBIAN_FRONTEND=noninteractive apt-get install -y \
        python3 python3-pip python3-venv python3-dev build-essential \
        libpam0g-dev rsync sudo curl ca-certificates tar gzip \
        passwd procps iproute2
      ;;
    dnf)
      dnf install -y \
        python3 python3-pip python3-devel gcc gcc-c++ make \
        pam-devel rsync sudo curl ca-certificates tar gzip \
        shadow-utils procps-ng iproute
      ;;
    yum)
      yum install -y \
        python3 python3-pip python3-devel gcc gcc-c++ make \
        pam-devel rsync sudo curl ca-certificates tar gzip \
        shadow-utils procps-ng iproute
      ;;
  esac
  ok "Dependencies installed"
}

node_version_ok() {
  command -v node >/dev/null 2>&1 || return 1
  local version major minor
  version="$(node -p 'process.versions.node' 2>/dev/null || true)"
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
      curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash -
      DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs
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

prepare_source() {
  section "Preparing source"
  local script_dir=""
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
  if [[ -n "$script_dir" && -f "${script_dir}/backend/app/main.py" && -f "${script_dir}/frontend/package.json" ]]; then
    SOURCE_DIR="$script_dir"
    ok "Using local repository: ${SOURCE_DIR}"
    return
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
  printf 'Build frontend:   %s\n' "$([[ "$SKIP_BUILD" == "yes" ]] && printf 'no' || printf 'yes')"
  if [[ "$ASSUME_YES" != "yes" ]]; then
    confirm "Continue installation?" "yes" || fail "Installation cancelled"
  fi
}

handle_existing_installation() {
  if [[ ! -d "$INSTALL_DIR" ]]; then
    ACTION="install"
    section "Installation check"
    ok "No existing installation found in ${INSTALL_DIR}"
    if [[ "$ASSUME_YES" != "yes" ]]; then
      confirm "Start new installation?" "yes" || fail "Installation cancelled"
    fi
    return
  fi

  section "Existing installation detected"
  warn "${INSTALL_DIR} already exists"
  if [[ -n "$EXISTING_ACTION" ]]; then
    ACTION="$EXISTING_ACTION"
    [[ "$ACTION" != "abort" ]] || fail "Installation cancelled"
    return
  fi
  if [[ "$ASSUME_YES" == "yes" ]]; then
    ACTION="backup-update"
    return
  fi
  printf 'Choose action:\n'
  printf '  1) Backup and update\n'
  printf '  2) Remove and fresh install\n'
  printf '  3) Update existing installation\n'
  printf '  4) Remove app only\n'
  printf '  5) Abort\n'
  local choice=""
  if choice="$(read_from_tty "Action [1]: ")"; then
    :
  else
    printf 'Action [1]: 1\n' >&2
    choice="1"
  fi
  case "${choice:-1}" in
    1) ACTION="backup-update" ;;
    2)
      confirm "Remove ${INSTALL_DIR} and install fresh?" "no" || fail "Installation cancelled"
      ACTION="remove"
      ;;
    3) ACTION="update" ;;
    4) ACTION="remove-app" ;;
    5) fail "Installation cancelled" ;;
    *) fail "Invalid choice" ;;
  esac
}

backup_existing() {
  local stamp backup_dir
  stamp="$(date +%Y%m%d-%H%M%S)"
  if [[ "$ACTION" == "backup-update" || -f "$CONFIG_FILE" ]]; then
    backup_dir="/var/backups/webnas/${stamp}"
    install -d -m 0750 "$backup_dir"
    [[ -d "$INSTALL_DIR" ]] && rsync -a "$INSTALL_DIR/" "${backup_dir}/app/"
    [[ -f "$CONFIG_FILE" ]] && cp -a "$CONFIG_FILE" "${backup_dir}/config.yaml"
    ok "Backup created: ${backup_dir}"
  fi
}

remove_existing_installation() {
  if [[ "$ACTION" != "remove" ]]; then
    return
  fi
  section "Removing existing installation"
  validate_install_dir
  rm -rf --one-file-system "$INSTALL_DIR"
  ok "Removed ${INSTALL_DIR}"
}

choose_remove_scope() {
  printf 'Choose removal scope:\n'
  printf '  1) Remove application only\n'
  printf '  2) Remove application and config\n'
  printf '  3) Remove application, data, and logs\n'
  printf '  4) Remove application, config, data, and logs\n'
  printf '  5) Cancel\n'
  local choice=""
  if choice="$(read_from_tty "Removal scope [1]: ")"; then
    :
  else
    printf 'Removal scope [1]: 1\n' >&2
    choice="1"
  fi
  case "${choice:-1}" in
    1) REMOVE_SCOPE="app" ;;
    2) REMOVE_SCOPE="app-config" ;;
    3) REMOVE_SCOPE="app-data-logs" ;;
    4) REMOVE_SCOPE="all" ;;
    5) fail "Installation cancelled" ;;
    *) fail "Invalid choice" ;;
  esac
}

remove_app_only() {
  if [[ "$ACTION" != "remove-app" ]]; then
    return 1
  fi
  section "Removing application"
  validate_install_dir
  assert_removable_path "$INSTALL_DIR"
  assert_removable_path "$CONFIG_DIR"
  assert_removable_path "$DATA_DIR"
  assert_removable_path "$LOG_DIR"
  choose_remove_scope
  case "$REMOVE_SCOPE" in
    app)
      confirm "Remove application files from ${INSTALL_DIR} only?" "no" || fail "Installation cancelled"
      ;;
    app-config)
      confirm "Remove application files and config from ${CONFIG_DIR}?" "no" || fail "Installation cancelled"
      ;;
    app-data-logs)
      confirm "Remove application files, data, and logs from ${DATA_DIR}, ${LOG_DIR}?" "no" || fail "Installation cancelled"
      ;;
    all)
      confirm "Remove application, config, data, and logs?" "no" || fail "Installation cancelled"
      ;;
  esac
  systemctl disable --now "${SERVICE_NAME}.service" 2>/dev/null || true
  rm -f "$SERVICE_FILE"
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
  chown -R "${SERVICE_USER}:${SERVICE_USER}" "$INSTALL_DIR"
  chmod 0755 "$INSTALL_DIR"
  ok "Application copied to ${INSTALL_DIR}"
}

write_config() {
  section "Writing configuration"
  install -d -m 0755 "$CONFIG_DIR" "$DATA_DIR" "$LOG_DIR"
  install -d -m 1777 "${DATA_DIR}/tmp"
  chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "$DATA_DIR" "$LOG_DIR"
  if [[ -f "$CONFIG_FILE" ]]; then
    cp -a "$CONFIG_FILE" "${CONFIG_FILE}.bak.$(date +%Y%m%d-%H%M%S)"
    warn "Existing config backed up before update"
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
  if [[ "$SKIP_BUILD" == "yes" ]]; then
    warn "Frontend build skipped"
    return
  fi
  section "Building frontend"
  (cd "${INSTALL_DIR}/frontend" && npm install && npm run build)
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
# user contexts. Root is required when that impersonation model is enabled.
User=${SERVICE_USER}
Group=${SERVICE_GROUP}
NoNewPrivileges=false
PrivateTmp=true
ProtectSystem=full
ProtectHome=read-only
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
MemoryDenyWriteExecute=true
SystemCallArchitectures=native
ReadWritePaths=${DATA_DIR} ${LOG_DIR} /home ${INSTALL_DIR}

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
  command -v rsync >/dev/null 2>&1 && ok "rsync available" || fail "rsync is missing"
  systemctl list-unit-files "${SERVICE_NAME}.service" >/dev/null 2>&1 && ok "systemd sees ${SERVICE_NAME}.service" || fail "systemd service not visible"
  if [[ "$START_SERVICE" == "yes" ]]; then
    systemctl is-active --quiet "$SERVICE_NAME" && ok "Backend service is active" || fail "Backend service is not active"
    if command -v ss >/dev/null 2>&1; then
      ss -ltn | awk '{print $4}' | grep -Eq "(:|\\])${PORT}$" && ok "Port ${PORT} is listening" || fail "Port ${PORT} is not listening"
    fi
    if command -v curl >/dev/null 2>&1; then
      curl -fsS "http://127.0.0.1:${PORT}/api/health" | grep -q '"status"' && ok "Healthcheck responds" || fail "Healthcheck failed"
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
  return 0
}

cleanup_failed_install() {
  trap - EXIT
  cleanup
  if [[ "$INSTALL_COMPLETED" == "yes" ]]; then
    return 0
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
  if remove_app_only; then
    INSTALL_COMPLETED="yes"
    return
  fi
  detect_package_manager
  detect_proxmox_host
  prepare_source
  prompt_configuration
  install_dependencies
  setup_node_runtime
  backup_existing
  ensure_service_user
  systemctl stop "$SERVICE_NAME" 2>/dev/null || true
  remove_existing_installation
  copy_application
  setup_python
  write_config
  build_frontend
  install_uninstaller
  write_service
  configure_firewall
  start_service
  validate_installation
  INSTALL_COMPLETED="yes"
  print_finish
}

main "$@"
