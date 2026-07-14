#!/usr/bin/env bash
set -Eeuo pipefail

SERVICE_NAME="webnas"
DEFAULT_INSTALL_DIR="/opt/webnas"
INSTALL_DIR="${WEBNAS_INSTALL_DIR:-$DEFAULT_INSTALL_DIR}"
CONFIG_DIR="/etc/webnas"
DATA_DIR="/var/lib/webnas"
LOG_DIR="/var/log/webnas"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
ASSUME_YES="no"

usage() {
  cat <<EOF
WebNAS uninstaller

Usage:
  sudo ./uninstall.sh [--yes] [--install-dir PATH] [--help]

Options:
  --yes               Accept default removal prompts after the required text confirmation
  --remove-data       Remove config, data, and logs without an interactive prompt
  --install-dir PATH  Installation directory (default: /opt/webnas)
  --help              Show this help
EOF
}

REMOVE_DATA="no"
CONFIRM_TEXT="REMOVE WEBNAS"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes)
      ASSUME_YES="yes"
      shift
      ;;
    --remove-data)
      REMOVE_DATA="yes"
      shift
      ;;
    --install-dir)
      [[ $# -ge 2 ]] || { echo "--install-dir requires a value" >&2; exit 1; }
      INSTALL_DIR="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

confirm() {
  local prompt="$1"
  local default="${2:-no}"
  local suffix="[y/N]"
  [[ "$default" == "yes" ]] && suffix="[Y/n]"
  if [[ "$ASSUME_YES" == "yes" ]]; then
    [[ "$default" == "yes" ]]
    return
  fi
  local answer=""
  read -r -p "${prompt} ${suffix} " answer
  answer="${answer:-$default}"
  [[ "$answer" =~ ^[Yy] ]]
}

assert_safe_path() {
  local path="$1"
  case "$path" in
    /opt/webnas|/etc/webnas|/var/lib/webnas|/var/log/webnas) return 0 ;;
    ""|/|/etc|/var|/opt|/home|/root|/mnt|/mnt/pve|/var/lib/vz|/etc/pve) ;;
  esac
  echo "Refusing unsafe path: ${path}" >&2
  exit 1
}

[[ "${EUID}" -eq 0 ]] || { echo "Run as root, for example: sudo ./uninstall.sh" >&2; exit 1; }

cleanup_managed_mounts() {
  local python_bin="${INSTALL_DIR}/backend/.venv/bin/python"
  [[ -x "$python_bin" && -f "${INSTALL_DIR}/backend/app/network_mounts.py" ]] || {
    echo "WebNAS mount cleanup helper is unavailable; leaving /mnt/webnas/mnt untouched." >&2
    return 0
  }
  echo "Unmounting network resources managed by WebNAS..."
  PYTHONPATH="${INSTALL_DIR}/backend" WEBNAS_CONFIG="${CONFIG_DIR}/config.yaml" "$python_bin" - <<'PY'
from app.network_mounts import actual_mount, connect, execute_mount, remove_systemd_units, row_to_mount

with connect() as connection:
    rows = connection.execute("SELECT * FROM mounts").fetchall()
for row in rows:
    mount = row_to_mount(row, reconcile=False)
    if actual_mount(mount["mount_point"]):
        result = execute_mount(mount, "unmount")
        if result.returncode:
            print(f"WARNING: could not unmount {mount['name']}: {result.stderr or result.stdout}")
            continue
    remove_systemd_units(mount)
PY
}

echo "Stopping WebNAS service..."
systemctl disable --now "${SERVICE_NAME}.service" 2>/dev/null || true
cleanup_managed_mounts
rm -f "$SERVICE_FILE"
systemctl daemon-reload

assert_safe_path "$INSTALL_DIR"
assert_safe_path "$CONFIG_DIR"
assert_safe_path "$DATA_DIR"
assert_safe_path "$LOG_DIR"

read -r -p "Type '${CONFIRM_TEXT}' to uninstall WebNAS: " typed
[[ "$typed" == "$CONFIRM_TEXT" ]] || { echo "Uninstall cancelled."; exit 1; }

if [[ -d "$INSTALL_DIR" ]] && confirm "Remove application files from ${INSTALL_DIR}?" "yes"; then
  rm -rf --one-file-system "$INSTALL_DIR"
  echo "Removed ${INSTALL_DIR}"
fi

if [[ "$REMOVE_DATA" == "yes" ]] || confirm "Remove config, data, and logs from ${CONFIG_DIR}, ${DATA_DIR}, ${LOG_DIR}?" "no"; then
  rm -rf --one-file-system "$CONFIG_DIR" "$DATA_DIR" "$LOG_DIR"
  echo "Removed WebNAS config/data/log directories"
else
  echo "Kept WebNAS config/data/log directories"
fi

if [[ -d /mnt/webnas/mnt ]]; then
  if find /mnt/webnas/mnt -mindepth 1 -print -quit | grep -q .; then
    echo "Kept non-empty mount directory /mnt/webnas/mnt; no local data was deleted."
  elif confirm "Remove empty base directory /mnt/webnas/mnt?" "no"; then
    rmdir /mnt/webnas/mnt 2>/dev/null || true
  fi
fi

echo "WebNAS uninstalled."
