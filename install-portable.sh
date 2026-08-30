#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="https://github.com/chmajster/Algen-server-web-explorer-panel"
ARCHIVE_URL="${REPO_URL}/archive/refs/heads/main.tar.gz"
PORT="5000"
BIND_HOST="127.0.0.1"
KEEP_WORKDIR="no"
LAUNCH_DIR="$(pwd -P)"
WORK_DIR="${LAUNCH_DIR}/portable-run"
SOURCE_DIR=""
BACKEND_PID=""
PORTABLE_CONFIG=""
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"

usage() {
  cat <<'EOF_USAGE'
WebNAS portable mode

Runs WebNAS without installing it as a system service. The application source,
Python virtual environment, frontend dependencies, configuration and runtime
data live in ./portable-run/ relative to the directory where the installer was
started. The directory is removed when the process exits unless --keep-workdir
is used. System packages are never installed or changed by portable mode.

Portable mode intentionally uses plaintext HTTP. It binds to loopback by
default. Use --bind-host 0.0.0.0 only in an isolated trusted network.

Authentication in portable mode uses System/PAM. The standard installed mode
uses the WebNAS Local database by default. Portable mode does not install the
privileged broker needed to provision Local-database POSIX companion accounts.

Usage:
  sudo ./install.sh --portable [options]
  ./install-portable.sh [options]

Options:
  -p, --port PORT          Application port (default: 5000)
  --bind-host ADDRESS      Listen address (default: 127.0.0.1)
  --keep-workdir           Keep ./portable-run/ after exit
  -y, --yes                Accepted for installer compatibility; portable mode
                           is already non-interactive
  -h, --help               Show this help

Required host runtimes:
  Python 3.14 with venv support, Node.js 20.19+ or 22.12+, npm and tar.
  curl or wget is additionally required when started outside a repository clone.
EOF_USAGE
}

info() { printf '[INFO] %s\n' "$1"; }
ok() { printf '[OK] %s\n' "$1"; }
warn() { printf '[WARN] %s\n' "$1" >&2; }
fail() { printf '[ERROR] %s\n' "$1" >&2; exit 1; }

cleanup() {
  local code=$?
  trap - EXIT INT TERM
  if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" 2>/dev/null || true
  fi
  if [[ -d "$WORK_DIR" ]]; then
    if [[ "$KEEP_WORKDIR" == "yes" ]]; then
      printf '[INFO] Portable work directory kept at: %s\n' "$WORK_DIR"
    else
      rm -rf --one-file-system "$WORK_DIR" 2>/dev/null || rm -rf "$WORK_DIR"
    fi
  fi
  exit "$code"
}
trap cleanup EXIT INT TERM

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --portable|-P)
        shift
        ;;
      --port|-p)
        [[ $# -ge 2 ]] || fail "--port requires a value"
        PORT="$2"
        shift 2
        ;;
      --bind-host)
        [[ $# -ge 2 ]] || fail "--bind-host requires a value"
        BIND_HOST="$2"
        shift 2
        ;;
      --keep-workdir)
        KEEP_WORKDIR="yes"
        shift
        ;;
      --yes|-y)
        shift
        ;;
      --help|-h)
        usage
        exit 0
        ;;
      *)
        fail "Unknown portable option: $1"
        ;;
    esac
  done
}

validate_options() {
  [[ "$PORT" =~ ^[0-9]+$ ]] || fail "Port must be numeric"
  (( PORT >= 1 && PORT <= 65535 )) || fail "Port must be between 1 and 65535"
  [[ -n "$BIND_HOST" ]] || fail "Bind host cannot be empty"
  [[ "$WORK_DIR" == "${LAUNCH_DIR}/portable-run" ]] || fail "Unsafe portable work directory: ${WORK_DIR}"
  [[ "$WORK_DIR" != "/portable-run" ]] || fail "Refusing to use /portable-run as the portable work directory"
}

node_version_ok() {
  command -v node >/dev/null 2>&1 || return 1
  local version major minor
  version="$(node --version 2>/dev/null || true)"
  version="${version#v}"
  version="${version#V}"
  major="${version%%.*}"
  minor="${version#*.}"
  minor="${minor%%.*}"
  [[ "$major" =~ ^[0-9]+$ && "$minor" =~ ^[0-9]+$ ]] || return 1
  (( major > 22 || (major == 22 && minor >= 12) || (major == 20 && minor >= 19) ))
}

check_prerequisites() {
  command -v python3.14 >/dev/null 2>&1 || fail "Python 3.14 is required. Portable mode does not install system packages."
  python3.14 -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 14) else 1)' || fail "python3.14 does not provide Python 3.14"
  python3.14 -m venv --help >/dev/null 2>&1 || fail "Python 3.14 venv support is required"
  command -v npm >/dev/null 2>&1 || fail "npm is required. Portable mode does not install Node.js."
  node_version_ok || fail "Node.js 20.19+ or 22.12+ is required; found $(node --version 2>/dev/null || printf 'not installed')"
  command -v tar >/dev/null 2>&1 || fail "tar is required"
}

copy_local_source() {
  local destination="$1"
  mkdir -p "$destination"
  tar -C "$SCRIPT_DIR" \
    --exclude='./.git' \
    --exclude='./portable-run' \
    --exclude='./backend/.venv' \
    --exclude='./frontend/node_modules' \
    --exclude='./frontend/dist' \
    -cf - . | tar -C "$destination" -xf -
}

prepare_source() {
  if [[ -e "$WORK_DIR" ]]; then
    info "Removing previous ./portable-run/ runtime"
    rm -rf --one-file-system "$WORK_DIR" 2>/dev/null || rm -rf "$WORK_DIR"
  fi
  mkdir -p "$WORK_DIR"
  SOURCE_DIR="${WORK_DIR}/app"
  info "Portable runtime directory: ${WORK_DIR}"

  if [[ -n "$SCRIPT_DIR" && -f "${SCRIPT_DIR}/backend/app/main.py" && -f "${SCRIPT_DIR}/frontend/package.json" ]]; then
    info "Copying the local repository into ./portable-run/app"
    copy_local_source "$SOURCE_DIR"
  else
    mkdir -p "$SOURCE_DIR"
    info "Downloading WebNAS source into ./portable-run/"
    if command -v curl >/dev/null 2>&1; then
      curl -fsSL "$ARCHIVE_URL" -o "${WORK_DIR}/webnas.tar.gz"
    elif command -v wget >/dev/null 2>&1; then
      wget -qO "${WORK_DIR}/webnas.tar.gz" "$ARCHIVE_URL"
    else
      fail "curl or wget is required when portable mode is started outside a repository clone"
    fi
    mkdir -p "${WORK_DIR}/archive"
    tar -xzf "${WORK_DIR}/webnas.tar.gz" -C "${WORK_DIR}/archive"
    local extracted=""
    extracted="$(find "${WORK_DIR}/archive" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
    [[ -n "$extracted" && -f "${extracted}/backend/app/main.py" && -f "${extracted}/frontend/package.json" ]] || fail "Downloaded archive does not contain WebNAS source"
    cp -a "${extracted}/." "$SOURCE_DIR/"
  fi

  [[ -f "${SOURCE_DIR}/backend/requirements.txt" ]] || fail "Backend requirements are missing"
  [[ -f "${SOURCE_DIR}/frontend/package-lock.json" ]] || fail "Frontend package-lock.json is missing"
  ok "Portable source ready at ${SOURCE_DIR}"
}

prepare_runtime() {
  info "Creating portable Python virtual environment"
  python3.14 -m venv "${SOURCE_DIR}/backend/.venv" || fail "Could not create Python 3.14 virtual environment"
  "${SOURCE_DIR}/backend/.venv/bin/pip" install --disable-pip-version-check --upgrade pip wheel
  "${SOURCE_DIR}/backend/.venv/bin/pip" install --disable-pip-version-check -r "${SOURCE_DIR}/backend/requirements.txt"

  info "Installing and building frontend dependencies"
  (cd "${SOURCE_DIR}/frontend" && npm ci)
  (cd "${SOURCE_DIR}/frontend" && npm run build)
  [[ -f "${SOURCE_DIR}/frontend/dist/index.html" ]] || fail "Frontend build did not produce dist/index.html"
  ok "Portable application runtime prepared"
}

select_pam_service() {
  local candidate
  for candidate in login common-auth system-auth; do
    if [[ -f "/etc/pam.d/${candidate}" ]]; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  printf '%s' "login"
}

write_portable_config() {
  local runtime_root="${WORK_DIR}/runtime"
  local pam_service=""
  local secret=""
  pam_service="$(select_pam_service)"
  secret="$(python3.14 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)"
  mkdir -p "${runtime_root}/data" "${runtime_root}/log" "${runtime_root}/tmp"
  PORTABLE_CONFIG="${runtime_root}/config.yaml"
  cat > "$PORTABLE_CONFIG" <<EOF_CONFIG
server:
  host: "${BIND_HOST}"
  port: ${PORT}
  use_https: false

auth:
  provider: pam
  pam_service: "${pam_service}"

paths:
  default_root: home
  allowed_roots: []
  data_dir: "${runtime_root}/data"
  log_dir: "${runtime_root}/log"
  temp_dir: "${runtime_root}/tmp"

security:
  session_secret: "${secret}"
  cookie_secure: false
  allow_insecure_http: true
EOF_CONFIG
  chmod 0600 "$PORTABLE_CONFIG"
  ok "Portable configuration created at ${PORTABLE_CONFIG}; /etc/webnas is not used"
}

initialize_portable_authentication() {
  local auth_db="${WORK_DIR}/runtime/data/local-auth.sqlite3"
  python3.14 - "$auth_db" <<'PY'
import os
import sqlite3
import sys

path = sys.argv[1]
os.makedirs(os.path.dirname(path), exist_ok=True)
with sqlite3.connect(path) as connection:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS local_auth_settings(
            id INTEGER PRIMARY KEY CHECK(id=1),
            auth_mode TEXT NOT NULL DEFAULT 'local',
            updated_at REAL NOT NULL DEFAULT 0,
            updated_by TEXT NOT NULL DEFAULT ''
        )
        """
    )
    connection.execute(
        "INSERT OR REPLACE INTO local_auth_settings(id,auth_mode,updated_at,updated_by) VALUES(1,'system',0,'portable-installer')"
    )
os.chmod(path, 0o600)
PY
  ok "Portable authentication mode set to System/PAM"
}

health_check() {
  local attempt
  for attempt in $(seq 1 40); do
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
      wait "$BACKEND_PID" || true
      fail "Portable WebNAS process exited before becoming healthy"
    fi
    if WEBNAS_HEALTH_PORT="$PORT" python3.14 - <<'PY' >/dev/null 2>&1
import os
import urllib.request

port = int(os.environ["WEBNAS_HEALTH_PORT"])
with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.4) as response:
    raise SystemExit(0 if 200 <= response.status < 300 else 1)
PY
    then
      return 0
    fi
    sleep 0.25
  done
  fail "Portable WebNAS did not become healthy on port ${PORT}"
}

run_portable() {
  local display_host="$BIND_HOST"
  if [[ "$display_host" == "0.0.0.0" || "$display_host" == "::" ]]; then
    display_host="$(hostname -I 2>/dev/null | awk '{print $1}')"
    [[ -n "$display_host" ]] || display_host="127.0.0.1"
  fi

  if [[ "${EUID}" -ne 0 ]]; then
    warn "Running without root privileges; system-management features may be unavailable"
  fi
  if [[ "$BIND_HOST" == "0.0.0.0" || "$BIND_HOST" == "::" ]]; then
    warn "Portable WebNAS is exposed over plaintext HTTP on all interfaces"
  fi

  info "Starting portable WebNAS"
  (
    cd "${SOURCE_DIR}/backend"
    WEBNAS_CONFIG="$PORTABLE_CONFIG" \
    WEBNAS_BIND_HOST="$BIND_HOST" \
    WEBNAS_BIND_PORT="$PORT" \
    PYTHONPATH="${SOURCE_DIR}/backend" \
      "${SOURCE_DIR}/backend/.venv/bin/python" -m app.run
  ) &
  BACKEND_PID="$!"

  health_check
  rm -f -- "${WORK_DIR}/runtime/data/initial-local-admin.txt"
  printf '\n[OK] WebNAS portable is running at http://%s:%s\n' "$display_host" "$PORT"
  printf '[INFO] Authentication mode: System/PAM (portable mode does not provision Local POSIX companions).\n'
  printf '[INFO] Runtime directory: %s\n' "$WORK_DIR"
  printf '[INFO] No systemd service, service user, firewall rule or /etc/webnas config was created.\n'
  printf '[INFO] Stop with Ctrl+C. ./portable-run/ will be removed on exit%s.\n\n' "$([[ "$KEEP_WORKDIR" == "yes" ]] && printf ' only if --keep-workdir is not used' || true)"

  wait "$BACKEND_PID"
  BACKEND_PID=""
}

main() {
  parse_args "$@"
  validate_options
  check_prerequisites
  prepare_source
  prepare_runtime
  write_portable_config
  initialize_portable_authentication
  run_portable
}

main "$@"