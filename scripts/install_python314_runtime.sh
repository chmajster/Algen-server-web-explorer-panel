#!/usr/bin/env bash
# Debian/Ubuntu Python 3.14 runtime support for the standard WebNAS installer.
# This file is sourced only after the repository source has been resolved.

PYTHON_REQUIRED_MAJOR_MINOR="3.14"
PYTHON_SOURCE_VERSION="3.14.7"
PYTHON_SOURCE_SHA256="3b48dac8fb59f62eaa67ac83c1eb12bda1b7a08406dd286e252c11a66be27f81"
PYTHON_SOURCE_URL="https://www.python.org/ftp/python/${PYTHON_SOURCE_VERSION}/Python-${PYTHON_SOURCE_VERSION}.tar.xz"
WEBNAS_APPLICATION_ROOT="${INSTALL_DIR%/}"
PYTHON_RUNTIME_ROOT="${WEBNAS_APPLICATION_ROOT}/runtime/python"
PYTHON_RUNTIME_DIR="${PYTHON_RUNTIME_ROOT}/${PYTHON_REQUIRED_MAJOR_MINOR}"
PYTHON_RUNTIME_BIN="${PYTHON_RUNTIME_DIR}/bin/python3.14"
INSTALLER_DISTRO_ID=""
INSTALLER_DISTRO_VERSION_ID=""
INSTALLER_DISTRO_CODENAME=""
DEBIAN_SYSTEM_PYTHON_TARGET_BEFORE=""
DEBIAN_SYSTEM_PYTHON_VERSION_BEFORE=""
PYTHON314_BUILD_DIR=""
PYTHON314_RUNTIME_INSTALL_STARTED="no"

verify_python314() {
  local candidate="$1"
  [[ -n "$candidate" && -x "$candidate" ]] || return 1
  "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 14) else 1)' >/dev/null 2>&1
}

verify_python314_runtime_modules() {
  local candidate="$1"
  "$candidate" - <<'PY'
import bz2
import ctypes
import lzma
import readline
import sqlite3
import ssl
import venv
import zlib
import sys

assert sys.version_info[:2] == (3, 14)
PY
}

detect_installer_distribution() {
  INSTALLER_DISTRO_ID="$(os_release_value ID || true)"
  INSTALLER_DISTRO_VERSION_ID="$(os_release_value VERSION_ID || true)"
  INSTALLER_DISTRO_CODENAME="$(os_release_value VERSION_CODENAME || true)"

  case "$INSTALLER_DISTRO_ID" in
    debian)
      info "Debian ${INSTALLER_DISTRO_VERSION_ID:-unknown}${INSTALLER_DISTRO_CODENAME:+ (${INSTALLER_DISTRO_CODENAME})} detected"
      ;;
    ubuntu)
      info "Ubuntu ${INSTALLER_DISTRO_VERSION_ID:-unknown}${INSTALLER_DISTRO_CODENAME:+ (${INSTALLER_DISTRO_CODENAME})} detected"
      ;;
    *)
      info "Distribution detected: ${INSTALLER_DISTRO_ID:-unknown} ${INSTALLER_DISTRO_VERSION_ID:-unknown}"
      ;;
  esac
}

is_debian_trixie() {
  [[ "$INSTALLER_DISTRO_ID" == "debian" && "$INSTALLER_DISTRO_VERSION_ID" == "13" && "$INSTALLER_DISTRO_CODENAME" == "trixie" ]]
}

detect_python314() {
  local candidate=""

  if verify_python314 "$PYTHON_RUNTIME_BIN"; then
    PYTHON_BIN="$PYTHON_RUNTIME_BIN"
    ok "Reusing WebNAS Python runtime: ${PYTHON_BIN}"
    return 0
  fi

  candidate="$(command -v python3.14 2>/dev/null || true)"
  if verify_python314 "$candidate"; then
    PYTHON_BIN="$candidate"
    ok "Using existing Python 3.14 runtime: ${PYTHON_BIN}"
    return 0
  fi

  PYTHON_BIN=""
  return 1
}

capture_debian_system_python_state() {
  [[ -x /usr/bin/python3 ]] || fail "Debian system Python is missing: /usr/bin/python3"
  DEBIAN_SYSTEM_PYTHON_TARGET_BEFORE="$(readlink -f /usr/bin/python3)"
  DEBIAN_SYSTEM_PYTHON_VERSION_BEFORE="$(/usr/bin/python3 --version 2>&1)"
  [[ -n "$DEBIAN_SYSTEM_PYTHON_TARGET_BEFORE" && -n "$DEBIAN_SYSTEM_PYTHON_VERSION_BEFORE" ]] || \
    fail "Could not capture the Debian system Python state"
}

verify_debian_system_integrity() {
  local target_after=""
  local version_after=""
  local dpkg_audit=""

  target_after="$(readlink -f /usr/bin/python3)"
  version_after="$(/usr/bin/python3 --version 2>&1)"

  [[ "$target_after" == "$DEBIAN_SYSTEM_PYTHON_TARGET_BEFORE" ]] || \
    fail "Debian system Python target changed from ${DEBIAN_SYSTEM_PYTHON_TARGET_BEFORE} to ${target_after}"
  [[ "$version_after" == "$DEBIAN_SYSTEM_PYTHON_VERSION_BEFORE" ]] || \
    fail "Debian system Python version changed from ${DEBIAN_SYSTEM_PYTHON_VERSION_BEFORE} to ${version_after}"

  apt-get --version >/dev/null 2>&1 || fail "apt-get is not functional after Python runtime preparation"
  dpkg_audit="$(dpkg --audit 2>&1)" || fail "dpkg --audit failed after Python runtime preparation"
  [[ -z "${dpkg_audit//[[:space:]]/}" ]] || {
    printf '%s\n' "$dpkg_audit" >&2
    fail "dpkg reports an inconsistent package state after Python runtime preparation"
  }

  ok "System Python unchanged: /usr/bin/python3 -> ${target_after} (${version_after})"
  ok "APT and dpkg remain healthy"
}

python314_source_build_dependencies() {
  info "Installing Debian Trixie build dependencies from configured Debian repositories only"
  DEBIAN_FRONTEND=noninteractive apt_get install -y \
    build-essential \
    pkg-config \
    ca-certificates \
    curl \
    xz-utils \
    libssl-dev \
    zlib1g-dev \
    libbz2-dev \
    libreadline-dev \
    libsqlite3-dev \
    libffi-dev \
    liblzma-dev \
    libncurses-dev \
    libgdbm-dev \
    libgdbm-compat-dev \
    libexpat1-dev \
    uuid-dev
}

validate_python314_source_architecture() {
  local architecture=""
  architecture="$(uname -m)"
  case "$architecture" in
    x86_64|aarch64)
      return 0
      ;;
    *)
      fail "Debian Trixie source installation of Python 3.14 is unsupported on architecture: ${architecture}"
      ;;
  esac
}

safe_remove_python314_path() {
  local path="$1"
  [[ -n "$path" ]] || return 0

  case "$path" in
    /tmp/webnas-python314.*|/var/tmp/webnas-python314.*|"$PYTHON_RUNTIME_DIR") ;;
    *)
      printf '[ERROR] Refusing unsafe Python runtime cleanup path: %s\n' "$path" >&2
      return 1
      ;;
  esac

  case "$path" in
    /|/usr|/usr/*|/opt|/etc|/var|"")
      printf '[ERROR] Refusing unsafe Python runtime cleanup path: %s\n' "$path" >&2
      return 1
      ;;
  esac

  rm -rf --one-file-system -- "$path"
}

cleanup_python314_build_trap() {
  local status="$1"
  trap - EXIT

  if [[ -n "$PYTHON314_BUILD_DIR" && -d "$PYTHON314_BUILD_DIR" ]]; then
    safe_remove_python314_path "$PYTHON314_BUILD_DIR" || true
  fi

  if [[ "$status" -ne 0 && "$PYTHON314_RUNTIME_INSTALL_STARTED" == "yes" ]]; then
    if ! verify_python314 "$PYTHON_RUNTIME_BIN"; then
      warn "Removing incomplete WebNAS Python runtime after failed build"
      safe_remove_python314_path "$PYTHON_RUNTIME_DIR" || true
    fi
  fi

  exit "$status"
}

build_python314_debian_source() (
  set -Eeuo pipefail

  local archive=""
  local source_dir=""
  local jobs="1"

  PYTHON314_BUILD_DIR="$(mktemp -d -t webnas-python314.XXXXXX)"
  PYTHON314_RUNTIME_INSTALL_STARTED="no"
  trap 'cleanup_python314_build_trap "$?"' EXIT

  archive="${PYTHON314_BUILD_DIR}/Python-${PYTHON_SOURCE_VERSION}.tar.xz"
  info "Downloading official Python ${PYTHON_SOURCE_VERSION} source from python.org"
  curl \
    --fail \
    --location \
    --proto '=https' \
    --tlsv1.2 \
    --output "$archive" \
    "$PYTHON_SOURCE_URL"

  info "Verifying Python source SHA-256"
  if ! printf '%s  %s\n' "$PYTHON_SOURCE_SHA256" "$archive" | sha256sum --check --status -; then
    rm -f -- "$archive"
    fail "Python ${PYTHON_SOURCE_VERSION} source SHA-256 verification failed"
  fi

  tar -xJf "$archive" -C "$PYTHON314_BUILD_DIR"
  source_dir="${PYTHON314_BUILD_DIR}/Python-${PYTHON_SOURCE_VERSION}"
  [[ -x "${source_dir}/configure" ]] || fail "Python source archive did not contain the expected configure script"

  install -d -o root -g root -m 0755 "$PYTHON_RUNTIME_ROOT"
  if [[ -e "$PYTHON_RUNTIME_DIR" ]]; then
    warn "Removing invalid private WebNAS Python runtime before rebuilding"
    safe_remove_python314_path "$PYTHON_RUNTIME_DIR"
  fi

  info "Configuring Python ${PYTHON_SOURCE_VERSION} for isolated prefix ${PYTHON_RUNTIME_DIR}"
  (
    cd "$source_dir"
    ./configure \
      --prefix="$PYTHON_RUNTIME_DIR" \
      --with-ensurepip=install
  )

  if command -v nproc >/dev/null 2>&1; then
    jobs="$(nproc)"
  fi
  [[ "$jobs" =~ ^[1-9][0-9]*$ ]] || jobs="1"
  (( jobs > 4 )) && jobs="4"

  info "Building Python ${PYTHON_SOURCE_VERSION} with ${jobs} parallel job(s)"
  make -C "$source_dir" -j "$jobs"

  PYTHON314_RUNTIME_INSTALL_STARTED="yes"
  info "Installing isolated WebNAS Python ${PYTHON_SOURCE_VERSION} runtime"
  make -C "$source_dir" altinstall

  verify_python314 "$PYTHON_RUNTIME_BIN" || fail "Installed WebNAS Python runtime does not provide Python 3.14"
  verify_python314_runtime_modules "$PYTHON_RUNTIME_BIN" || \
    fail "Installed WebNAS Python runtime is missing required standard-library modules"

  trap - EXIT
  safe_remove_python314_path "$PYTHON314_BUILD_DIR"
  PYTHON314_BUILD_DIR=""
  PYTHON314_RUNTIME_INSTALL_STARTED="no"
)

install_python314_debian_source() {
  validate_python314_source_architecture
  python314_source_build_dependencies

  info "Installing isolated WebNAS Python ${PYTHON_SOURCE_VERSION} runtime"
  info "System Python will not be modified"
  if ! build_python314_debian_source; then
    fail "Could not build the isolated WebNAS Python ${PYTHON_SOURCE_VERSION} runtime"
  fi

  verify_python314 "$PYTHON_RUNTIME_BIN" || fail "Private WebNAS Python runtime validation failed"
  PYTHON_BIN="$PYTHON_RUNTIME_BIN"
  ok "WebNAS Python runtime: ${PYTHON_BIN}"
}

ensure_python314() {
  if detect_python314; then
    return 0
  fi

  if is_debian_trixie; then
    info "Python 3.14 is not available from Debian Trixie APT repositories"
    install_python314_debian_source
    return 0
  fi

  case "$INSTALLER_DISTRO_ID" in
    ubuntu)
      ensure_python314_apt_repository
      DEBIAN_FRONTEND=noninteractive apt_get install -y \
        python3.14 python3.14-venv python3.14-dev || \
        fail "Python 3.14 packages were found, but python3.14, python3.14-venv, or python3.14-dev could not be installed. Inspect the APT error above and retry."
      PYTHON_BIN="$(command -v python3.14 || true)"
      ;;
    debian)
      fail "Python 3.14 is unavailable for Debian ${INSTALLER_DISTRO_VERSION_ID:-unknown} ${INSTALLER_DISTRO_CODENAME:-unknown}; the isolated source runtime is currently supported for Debian 13 Trixie"
      ;;
    *)
      ensure_python314_apt_repository
      DEBIAN_FRONTEND=noninteractive apt_get install -y \
        python3.14 python3.14-venv python3.14-dev || \
        fail "Python 3.14 packages could not be installed for ${INSTALLER_DISTRO_ID:-this distribution}"
      PYTHON_BIN="$(command -v python3.14 || true)"
      ;;
  esac

  verify_python314 "$PYTHON_BIN" || fail "Python 3.14 is required, but a valid interpreter was not found after dependency installation"
}

install_dependencies() {
  section "Installing dependencies"
  detect_installer_distribution

  case "$PKG_MANAGER" in
    apt)
      refresh_apt_metadata_for_installation
      if is_debian_trixie; then
        capture_debian_system_python_state
      fi

      ensure_python314

      DEBIAN_FRONTEND=noninteractive apt_get install -y \
        build-essential \
        libpam0g-dev rsync sudo curl wget ca-certificates tar gzip \
        passwd procps iproute2 ethtool traceroute screen quota util-linux udev nginx cifs-utils
      DEBIAN_FRONTEND=noninteractive apt_get install -y exfatprogs || warn "Optional exFAT tools could not be installed"

      if is_debian_trixie; then
        verify_debian_system_integrity
      fi
      ;;
    dnf)
      if ! detect_python314; then
        dnf install -y python3.14 python3.14-devel || \
          fail "Python 3.14 packages are unavailable. Enable a repository providing python3.14 and python3.14-devel, then retry."
        PYTHON_BIN="$(command -v python3.14 || true)"
      fi
      dnf install -y \
        gcc gcc-c++ make \
        pam-devel rsync sudo curl wget ca-certificates tar gzip \
        shadow-utils procps-ng iproute ethtool traceroute screen quota util-linux systemd-udev nginx cifs-utils
      dnf install -y ntfs-3g exfatprogs || warn "Optional NTFS/exFAT tools could not be installed"
      ;;
    yum)
      if ! detect_python314; then
        yum install -y python3.14 python3.14-devel || \
          fail "Python 3.14 packages are unavailable. Enable a repository providing python3.14 and python3.14-devel, then retry."
        PYTHON_BIN="$(command -v python3.14 || true)"
      fi
      yum install -y \
        gcc gcc-c++ make \
        pam-devel rsync sudo curl wget ca-certificates tar gzip \
        shadow-utils procps-ng iproute ethtool traceroute screen quota util-linux systemd-udev nginx cifs-utils
      yum install -y ntfs-3g exfatprogs || warn "Optional NTFS/exFAT tools could not be installed"
      ;;
  esac

  command -v mount.cifs >/dev/null 2>&1 || fail "cifs-utils was installed, but mount.cifs is unavailable; SMB/CIFS mounts cannot work"
  ok "SMB/CIFS runtime is ready (cifs-utils)"
  verify_python314 "$PYTHON_BIN" || fail "Python 3.14 is required, but the selected interpreter is invalid"
  ok "Dependencies installed"
}

setup_python() {
  update_step install_backend_dependencies started
  section "Installing Python packages"

  verify_python314 "$PYTHON_BIN" || fail "WebNAS requires an exact Python 3.14 base interpreter"
  "$PYTHON_BIN" -m venv "${INSTALL_DIR}/backend/.venv" || \
    fail "Could not create a Python 3.14 virtualenv with ${PYTHON_BIN}"

  local venv_python="${INSTALL_DIR}/backend/.venv/bin/python"
  verify_python314 "$venv_python" || fail "WebNAS virtualenv does not use Python 3.14"

  "$venv_python" -m pip install --upgrade pip wheel
  "$venv_python" -m pip install -r "${INSTALL_DIR}/backend/requirements.txt"
  ok "Python virtualenv ready: ${venv_python}"
  update_step install_backend_dependencies completed
}

# Prefer a previously installed persistent runtime before the installer summary
# is rendered. No PATH or system interpreter changes are made.
if verify_python314 "$PYTHON_RUNTIME_BIN"; then
  PYTHON_BIN="$PYTHON_RUNTIME_BIN"
fi
