#!/usr/bin/env bash
set -euo pipefail

APP_NAME="webnas"
APP_DIR="/opt/webnas"
CONFIG_DIR="/etc/webnas"
DATA_DIR="/var/lib/webnas"
LOG_DIR="/var/log/webnas"
PORT="5000"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo ./scripts/install.sh"
  exit 1
fi

if ! grep -qiE "debian|ubuntu" /etc/os-release; then
  echo "This installer supports Ubuntu/Debian."
  exit 1
fi

if ss -ltn "( sport = :${PORT} )" | tail -n +2 | grep -q .; then
  echo "Port ${PORT} is already in use."
  read -r -p "Continue anyway and overwrite the default config/service port? [y/N] " answer
  if [[ ! "${answer}" =~ ^[Yy]$ ]]; then
    echo "Installation cancelled. Free port ${PORT} or edit the installer/config."
    exit 1
  fi
fi

echo "Installing dependencies..."
apt-get update
apt-get install -y python3 python3-venv python3-dev build-essential libpam0g-dev rsync ca-certificates curl gnupg

echo "Checking PAM and local account tools..."
if [[ ! -d /etc/pam.d ]] || ! ldconfig -p 2>/dev/null | grep -q "libpam.so"; then
  echo "PAM support is required but was not detected. Install PAM development/runtime packages and retry."
  exit 1
fi
required_tools=(useradd usermod userdel groupadd groupmod groupdel passwd chage chpasswd gpasswd chown chmod systemctl)
missing_tools=()
for tool in "${required_tools[@]}"; do
  if ! command -v "${tool}" >/dev/null 2>&1; then
    missing_tools+=("${tool}")
  fi
done
if (( ${#missing_tools[@]} )); then
  echo "Missing required system tools: ${missing_tools[*]}"
  echo "Install the account-management packages for this distribution and retry."
  exit 1
fi
if ! command -v node >/dev/null 2>&1 || ! node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 22 ? 0 : 1)'; then
  install -d -m 0755 /etc/apt/keyrings
  curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --batch --yes --dearmor -o /etc/apt/keyrings/nodesource.gpg
  echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" > /etc/apt/sources.list.d/nodesource.list
  apt-get update
  apt-get install -y nodejs
fi

echo "Creating directories..."
mkdir -p "${APP_DIR}" "${CONFIG_DIR}" "${DATA_DIR}/tmp" "${LOG_DIR}"
chmod 1777 "${DATA_DIR}/tmp"
chmod 755 "${DATA_DIR}" "${LOG_DIR}"

echo "Copying application..."
rsync -a --delete --exclude ".git" --exclude "frontend/node_modules" --exclude "frontend/dist" "${SRC_DIR}/" "${APP_DIR}/"
if [[ ! -f "${APP_DIR}/frontend/src/locales/pl-PL.json" || ! -f "${APP_DIR}/frontend/src/locales/en-US.json" ]]; then
  echo "Default translation files pl-PL and en-US are missing."
  exit 1
fi

echo "Creating Python virtualenv..."
python3 -m venv "${APP_DIR}/backend/.venv"
"${APP_DIR}/backend/.venv/bin/pip" install --upgrade pip wheel
"${APP_DIR}/backend/.venv/bin/pip" install -r "${APP_DIR}/backend/requirements.txt"

echo "Building frontend..."
cd "${APP_DIR}/frontend"
npm install
npm run build

if [[ ! -f "${CONFIG_DIR}/config.yaml" ]]; then
  secret="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)"
  sed "s/change-this-secret-during-install/${secret}/" "${APP_DIR}/config.example.yaml" > "${CONFIG_DIR}/config.yaml"
fi

echo "Installing systemd service..."
cp "${APP_DIR}/packaging/webnas.service" /etc/systemd/system/webnas.service
systemctl daemon-reload
systemctl enable --now webnas.service

ip_addr="$(hostname -I | awk '{print $1}')"
echo
systemctl --no-pager status webnas.service || true
echo
echo "WebNAS is available at: http://${ip_addr:-IP_SERWERA}:${PORT}"
