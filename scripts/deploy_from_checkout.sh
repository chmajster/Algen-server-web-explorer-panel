#!/usr/bin/env bash
set -Eeuo pipefail

SOURCE_DIR="${1:?source checkout path is required}"
SOURCE_SHA="${2:?source commit SHA is required}"
FRONTEND_DIST="${3:?tested frontend artifact directory is required}"
WEBNAS_ROOT="${WEBNAS_ROOT:-/opt/webnas}"
WEBNAS_CONFIG="${WEBNAS_CONFIG:-/etc/webnas/config.yaml}"
SERVICE_USER="${WEBNAS_SERVICE_USER:-webnas}"
STATE_FILE="${WEBNAS_STATE_FILE:-/var/lib/webnas/settings/deployment.json}"

[[ "${EUID}" -eq 0 ]] || { echo "Deployment must run as root" >&2; exit 1; }
[[ "${SOURCE_SHA}" =~ ^[0-9a-f]{40}$ ]] || { echo "Invalid source revision" >&2; exit 1; }
[[ -f "${SOURCE_DIR}/backend/app/main.py" && -f "${SOURCE_DIR}/frontend/package-lock.json" ]] || { echo "Invalid WebNAS checkout" >&2; exit 1; }
[[ -f "${WEBNAS_CONFIG}" ]] || { echo "Missing production config: ${WEBNAS_CONFIG}" >&2; exit 1; }
[[ -f "${FRONTEND_DIST}/index.html" ]] || { echo "Tested frontend artifact is missing index.html" >&2; exit 1; }
[[ -f "${FRONTEND_DIST}/.webnas-assets.json" ]] || { echo "Tested frontend artifact is missing its integrity manifest" >&2; exit 1; }
[[ -f "${FRONTEND_DIST}/.webnas-source-sha" ]] || { echo "Tested frontend artifact is missing source provenance" >&2; exit 1; }
ARTIFACT_SOURCE_SHA="$(tr -d '\r\n' < "${FRONTEND_DIST}/.webnas-source-sha")"
[[ "${ARTIFACT_SOURCE_SHA}" == "${SOURCE_SHA}" ]] || {
  echo "Refusing frontend artifact from ${ARTIFACT_SOURCE_SHA:-unknown}; expected ${SOURCE_SHA}" >&2
  exit 1
}

PUBLIC_PORT="$(awk '
  /^server:[[:space:]]*$/ { section=1; next }
  section && /^[^[:space:]]/ { exit }
  section && /^[[:space:]]+port:[[:space:]]*/ {
    sub(/^[[:space:]]+port:[[:space:]]*/, ""); sub(/[[:space:]#].*$/, ""); gsub(/["\047]/, ""); print; exit
  }
' "${WEBNAS_CONFIG}")"
[[ "${PUBLIC_PORT}" =~ ^[0-9]+$ ]] || { echo "Could not resolve production port" >&2; exit 1; }

RELEASE_DIR="${WEBNAS_ROOT}/releases/github-${SOURCE_SHA}"
[[ "${RELEASE_DIR}" == "${WEBNAS_ROOT}/releases/"* ]] || exit 1
rm -rf --one-file-system "${RELEASE_DIR}"
install -d -m 0755 "${WEBNAS_ROOT}/releases" "${RELEASE_DIR}"

rsync -a --delete \
  --exclude .git \
  --exclude backend/.venv \
  --exclude frontend/node_modules \
  --exclude frontend/dist \
  "${SOURCE_DIR}/" "${RELEASE_DIR}/"
printf '%s\n' "${SOURCE_SHA}" > "${RELEASE_DIR}/.webnas-revision"

install -d -m 0755 "${RELEASE_DIR}/frontend/dist"
rsync -a --delete "${FRONTEND_DIST}/" "${RELEASE_DIR}/frontend/dist/"
FRONTEND_MANIFEST_SHA256="$(sha256sum "${RELEASE_DIR}/frontend/dist/.webnas-assets.json" | awk '{print $1}')"
printf '%s\n' "${FRONTEND_MANIFEST_SHA256}" > "${RELEASE_DIR}/.webnas-frontend-manifest-sha256"

python3.14 -m venv "${RELEASE_DIR}/backend/.venv"
"${RELEASE_DIR}/backend/.venv/bin/pip" install --disable-pip-version-check -r "${RELEASE_DIR}/backend/requirements.txt"
"${RELEASE_DIR}/backend/.venv/bin/python" "${RELEASE_DIR}/scripts/verify_frontend_build.py" "${RELEASE_DIR}/frontend/dist"

if [[ -d "${WEBNAS_ROOT}/current/frontend/dist/assets" ]]; then
  rsync -a --ignore-existing "${WEBNAS_ROOT}/current/frontend/dist/assets/" "${RELEASE_DIR}/frontend/dist/assets/"
fi

"${RELEASE_DIR}/backend/.venv/bin/python" "${RELEASE_DIR}/scripts/webnas_release.py" \
  --root "${WEBNAS_ROOT}" \
  --release "${RELEASE_DIR}" \
  --config "${WEBNAS_CONFIG}" \
  --public-port "${PUBLIC_PORT}" \
  --service-user "${SERVICE_USER}" \
  --state "${STATE_FILE}"

scheme=http
curl_options=(--fail --silent --show-error --max-time 5)
if grep -Eq '^\s*use_https:\s*true\s*$' "${WEBNAS_CONFIG}"; then
  scheme=https
  curl_options+=(--insecure)
fi

smoke() {
  curl "${curl_options[@]}" "${scheme}://127.0.0.1:${PUBLIC_PORT}/api/health/live" >/dev/null
  curl "${curl_options[@]}" "${scheme}://127.0.0.1:${PUBLIC_PORT}/api/health/ready" >/dev/null
  curl "${curl_options[@]}" "${scheme}://127.0.0.1:${PUBLIC_PORT}/" >/dev/null
}

if ! smoke; then
  echo "Post-deploy smoke test failed; restoring previous release" >&2
  "${RELEASE_DIR}/backend/.venv/bin/python" "${RELEASE_DIR}/scripts/rollback_release.py" \
    --root "${WEBNAS_ROOT}" \
    --config "${WEBNAS_CONFIG}" \
    --public-port "${PUBLIC_PORT}" \
    --service-user "${SERVICE_USER}" \
    --state "${STATE_FILE}"
  smoke || { echo "Rollback completed but smoke test still fails" >&2; exit 1; }
  exit 1
fi

echo "Production deployment healthy at ${SOURCE_SHA}; tested frontend manifest ${FRONTEND_MANIFEST_SHA256}"
