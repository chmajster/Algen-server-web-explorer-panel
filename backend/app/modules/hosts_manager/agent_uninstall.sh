#!/usr/bin/env bash
set -euo pipefail

[[ "${EUID}" -eq 0 ]] || { printf '%s\n' "Run as root." >&2; exit 1; }

if command -v systemctl >/dev/null 2>&1; then
  systemctl disable --now hosts-manager-agent.service 2>/dev/null || true
  rm -f /etc/systemd/system/hosts-manager-agent.service
  systemctl daemon-reload 2>/dev/null || true
fi
if command -v rc-service >/dev/null 2>&1; then
  rc-service hosts-manager-agent stop 2>/dev/null || true
  rc-update del hosts-manager-agent default 2>/dev/null || true
  rm -f /etc/init.d/hosts-manager-agent
fi
pkill -f '/opt/hosts-manager-agent/agent.py run' 2>/dev/null || true
rm -rf /opt/hosts-manager-agent
rm -rf /etc/hosts-manager-agent
rm -rf /var/lib/hosts-manager-agent
rm -rf /var/log/hosts-manager-agent
printf '%s\n' "Hosts Manager agent removed. Revoke or invalidate its identity in Hosts Manager."

