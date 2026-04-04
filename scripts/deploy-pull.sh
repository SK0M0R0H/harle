#!/usr/bin/env bash
# Server-side deploy: pull latest image from GHCR, restart if changed, health-check.
# Intended for systemd user timer; load env via EnvironmentFile in the unit or export manually.
set -euo pipefail

HARLE_REPO_DIR="${HARLE_REPO_DIR:-${HOME}/harle}"
LOG_FILE="${DEPLOY_LOG_FILE:-${HOME}/deploy-pull.log}"
STATE_DIR="${HARLE_STATE_DIR:-/tmp}"
# Touch this file before restarting harle; health-monitor.sh suppresses DOWN alerts until removed.
DEPLOY_LOCK_FILE="${HARLE_DEPLOY_IN_PROGRESS_FILE:-${STATE_DIR}/harle-deploy-in-progress}"
HEALTH_URL="${HARLE_API_URL:-http://127.0.0.1:8000}/health"
COMPOSE_ARGS=(
  -f "${HARLE_REPO_DIR}/docker-compose.yml"
  -f "${HARLE_REPO_DIR}/docker-compose.prod.yml"
)
HEALTH_RETRIES=6
HEALTH_WAIT=10

log_line() {
  printf "[%s] %s\n" "$(date -Iseconds)" "$*" >> "${LOG_FILE}"
}

die() {
  log_line "ERROR: $*"
  echo "deploy-pull: $*" >&2
  exit 1
}

if [[ ! -f "${HARLE_REPO_DIR}/docker-compose.yml" ]]; then
  die "docker-compose.yml not found in ${HARLE_REPO_DIR}"
fi
if [[ ! -f "${HARLE_REPO_DIR}/docker-compose.prod.yml" ]]; then
  die "docker-compose.prod.yml not found in ${HARLE_REPO_DIR}"
fi
if ! mkdir -p "${STATE_DIR}" 2>>"${LOG_FILE}"; then
  die "cannot create state directory ${STATE_DIR}"
fi

cd "${HARLE_REPO_DIR}" || die "cannot cd to ${HARLE_REPO_DIR}"

running_container_id="$(docker compose "${COMPOSE_ARGS[@]}" ps -q harle 2>/dev/null || true)"
running_image_id=""
if [[ -n "${running_container_id}" ]]; then
  running_image_id="$(docker inspect --format '{{.Image}}' "${running_container_id}" 2>/dev/null || true)"
fi

log_line "Pulling harle image (tag: ${HARLE_IMAGE_TAG:-latest})..."
if ! docker compose "${COMPOSE_ARGS[@]}" pull harle 2>>"${LOG_FILE}"; then
  die "docker compose pull failed"
fi

target_image_id="$(docker compose "${COMPOSE_ARGS[@]}" images -q harle 2>/dev/null || true)"
if [[ -z "${target_image_id}" ]]; then
  die "failed to resolve target image ID for harle service"
fi

if [[ -n "${running_image_id}" && "${running_image_id}" == "${target_image_id}" ]]; then
  log_line "Running container already uses target image; nothing to do"
  exit 0
fi

from_id="${running_image_id:-none}"
log_line "Image update detected (${from_id:0:12} -> ${target_image_id:0:12}); restarting harle..."
touch "${DEPLOY_LOCK_FILE}"
trap 'rm -f "${DEPLOY_LOCK_FILE}"' EXIT
log_line "Deploy lock active (${DEPLOY_LOCK_FILE}); health monitor will suppress DOWN alerts until deploy finishes"
if ! docker compose "${COMPOSE_ARGS[@]}" up -d harle 2>>"${LOG_FILE}"; then
  die "docker compose up -d harle failed"
fi

log_line "Waiting for health check..."
for attempt in $(seq 1 "${HEALTH_RETRIES}"); do
  sleep "${HEALTH_WAIT}"
  if curl -fsS --connect-timeout 5 --max-time 10 "${HEALTH_URL}" >/dev/null 2>&1; then
    log_line "Health check passed (attempt ${attempt}/${HEALTH_RETRIES})"
    log_line "Deploy complete"
    exit 0
  fi
  log_line "Health check attempt ${attempt}/${HEALTH_RETRIES} failed"
done

log_line "ERROR: Health check failed after ${HEALTH_RETRIES} attempts. Server may be unhealthy."
log_line "Manual intervention needed. To rollback: set HARLE_IMAGE_TAG=sha-<known-good> in .env, then re-run this script."
exit 1
