#!/usr/bin/env bash
set -euo pipefail

die() { printf '%s\n' "Hosts Manager agent installation failed: $1" >&2; exit 1; }
[[ "${EUID}" -eq 0 ]] || die "run as root"

SERVER_URL="${HOSTS_MANAGER_URL:-}"
ENROLLMENT_TOKEN="${HOSTS_MANAGER_TOKEN:-}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --server-url) SERVER_URL="${2:-}"; shift 2 ;;
    --token) ENROLLMENT_TOKEN="${2:-}"; shift 2 ;;
    *) die "unknown argument: $1" ;;
  esac
done

case "$SERVER_URL" in
  http://*) CURL_TRANSPORT=(--proto '=http') ;;
  https://*) CURL_TRANSPORT=(--proto '=https' --tlsv1.2) ;;
  *) die "--server-url must use HTTP or HTTPS" ;;
esac
[[ -n "$ENROLLMENT_TOKEN" ]] || die "--token is required"
command -v curl >/dev/null 2>&1 || die "curl is required"
command -v python3 >/dev/null 2>&1 || die "python3 is required"

HEADER="Authorization: Bearer $ENROLLMENT_TOKEN"
curl --fail --silent --show-error "${CURL_TRANSPORT[@]}" \
  -H "$HEADER" "$SERVER_URL/api/modules/hosts-manager/enrollment-script" | bash
