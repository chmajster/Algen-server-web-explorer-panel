#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo ./scripts/uninstall.sh"
  exit 1
fi

systemctl disable --now webnas.service 2>/dev/null || true
rm -f /etc/systemd/system/webnas.service
systemctl daemon-reload

read -r -p "Remove /opt/webnas application files? [y/N] " remove_app
[[ "${remove_app}" =~ ^[Yy]$ ]] && rm -rf /opt/webnas

read -r -p "Remove config, data, and logs from /etc/webnas, /var/lib/webnas, /var/log/webnas? [y/N] " remove_data
if [[ "${remove_data}" =~ ^[Yy]$ ]]; then
  rm -rf /etc/webnas /var/lib/webnas /var/log/webnas
fi

echo "WebNAS removed."
