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
START_SERVICE="yes"
ENABLE_AUTOSTART="yes"
CONFIGURE_FIREWALL="yes"
SKIP_BUILD="no"
ASSUME_YES="no"
NON_INTERACTIVE="no"
ACTION="install"
ALLOW_PROXMOX_HOST_INSTALL="no"
IS_PROXMOX="no"

CONFIG_DIR="/etc/webnas"
CONFIG_FILE="${CONFIG_DIR}/config.yaml"
DATA_DIR="/var/lib/webnas"
LOG_DIR="/var/log/webnas"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
WORK_DIR=""
SOURCE_DIR=""

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
  --help                  Show this help
EOF
}

log() { printf '%b[%s]%b %s\n' "$2" "$1" "$RESET" "$3"; }
info() { log "INFO" "$BLUE" "$1"; }
ok() { log "OK" "$GREEN" "$1"; }
warn() { log "WARN" "$YELLOW" "$1"; }
fail() { log "ERROR" "$RED" "$1"; exit 1; }
section() { printf '\n%b==> %s%b\n' "$BOLD" "$1" "$RESET"; }

on_error() {
  local line="$1"
  local code="$2"
  printf '\n%b[ERROR]%b Installation failed at line %s with exit code %s.\n' "$RED" "$RESET" "$line" "$code" >&2
  printf 'Check the last command output above. If systemd was reached, inspect: journalctl -u %s -n 80 --no-pager\n' "$SERVICE_NAME" >&2
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

ask() {
  local prompt="$1"
  local default="$2"
  local answer=""
  if [[ "$ASSUME_YES" == "yes" ]]; then
    printf '%s [%s]: %s\n' "$prompt" "$default" "$default"
    printf '%s' "$default"
    return
  fi
  read -r -p "${prompt} [${default}]: " answer
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
  read -r -p "${prompt} ${suffix} " answer
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
        passwd procps iproute2 nodejs npm
      ;;
    dnf)
      dnf install -y \
        python3 python3-pip python3-devel gcc gcc-c++ make \
        pam-devel rsync sudo curl ca-certificates tar gzip \
        shadow-utils procps-ng iproute nodejs npm
      ;;
    yum)
      yum install -y \
        python3 python3-pip python3-devel gcc gcc-c++ make \
        pam-devel rsync sudo curl ca-certificates tar gzip \
        shadow-utils procps-ng iproute nodejs npm
      ;;
  esac
  ok "Dependencies installed"
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

prompt_configuration() {
  if [[ "$NON_INTERACTIVE" != "yes" ]]; then
    section "Configuration"
    PORT="$(ask "Application port" "$PORT")"
    INSTALL_DIR="$(ask "Installation directory" "$INSTALL_DIR")"
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
  validate_install_dir

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
    return
  fi

  section "Existing installation detected"
  warn "${INSTALL_DIR} already exists"
  if [[ "$ASSUME_YES" == "yes" ]]; then
    ACTION="backup-update"
    return
  fi
  printf 'Choose action:\n'
  printf '  1) Update existing installation\n'
  printf '  2) Backup and update\n'
  printf '  3) Abort\n'
  local choice=""
  read -r -p "Action [2]: " choice
  case "${choice:-2}" in
    1) ACTION="update" ;;
    2) ACTION="backup-update" ;;
    3) fail "Installation cancelled" ;;
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
trap cleanup EXIT

main() {
  parse_args "$@"
  banner
  require_root
  validate_port
  validate_install_dir
  detect_package_manager
  detect_proxmox_host
  prepare_source
  prompt_configuration
  handle_existing_installation
  install_dependencies
  backup_existing
  ensure_service_user
  systemctl stop "$SERVICE_NAME" 2>/dev/null || true
  copy_application
  setup_python
  write_config
  build_frontend
  install_uninstaller
  write_service
  configure_firewall
  start_service
  validate_installation
  print_finish
}

main "$@"
