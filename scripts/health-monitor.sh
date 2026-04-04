#!/usr/bin/env bash
# Health monitor: check Harle API, disk usage, and container status.
# Sends Telegram alerts on state transitions (down/recovered, disk warning/cleared).
# Intended for systemd user timer (every 1 minute); load env via EnvironmentFile.
set -euo pipefail

HEALTH_URL="${HARLE_API_URL:-http://127.0.0.1:8000}/health"
LOG_FILE="${HEALTH_MONITOR_LOG_FILE:-${HOME}/health-monitor.log}"
STATE_DIR="${HARLE_STATE_DIR:-/tmp}"
DISK_WARN_PCT="${HARLE_DISK_WARN_PCT:-85}"

HARLE_REPO_DIR="${HARLE_REPO_DIR:-${HOME}/harle}"
COMPOSE_ARGS=(
  -f "${HARLE_REPO_DIR}/docker-compose.yml"
  -f "${HARLE_REPO_DIR}/docker-compose.prod.yml"
)

HEALTH_STATE_FILE="${STATE_DIR}/harle-health-state"
DISK_STATE_FILE="${STATE_DIR}/harle-disk-state"
# When present (written by deploy-pull.sh during image restart), suppress DOWN/RECOVERED alerts.
DEPLOY_LOCK_FILE="${HARLE_DEPLOY_IN_PROGRESS_FILE:-${STATE_DIR}/harle-deploy-in-progress}"
# Ignore lock files older than this (seconds) so a crashed deploy cannot silence alerts forever.
DEPLOY_LOCK_MAX_AGE_SEC="${HARLE_DEPLOY_LOCK_MAX_AGE_SEC:-900}"

TELEGRAM_BOT_TOKEN="${HARLE_TELEGRAM_ALERT_BOT_TOKEN:-}"
TELEGRAM_CHAT_ID="${HARLE_TELEGRAM_ALERT_CHAT_ID:-}"

log_line() {
  printf "[%s] %s\n" "$(date -Iseconds)" "$*" >> "${LOG_FILE}"
}

send_telegram() {
  local message="$1"
  if [[ -z "${TELEGRAM_BOT_TOKEN}" || -z "${TELEGRAM_CHAT_ID}" ]]; then
    log_line "TELEGRAM_SKIP: ${message}"
    return 0
  fi
  curl -sf -X POST \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d chat_id="${TELEGRAM_CHAT_ID}" \
    -d text="${message}" \
    -d parse_mode="Markdown" > /dev/null 2>&1 || \
    log_line "WARN: Telegram send failed"
}

if ! mkdir -p "${STATE_DIR}" 2>>"${LOG_FILE}"; then
  log_line "ERROR: cannot create state directory ${STATE_DIR}"
  exit 1
fi

# --- Health check ---

check_health() {
  local http_code
  http_code=$(curl -sf -o /dev/null -w "%{http_code}" \
    --connect-timeout 5 --max-time 10 "${HEALTH_URL}" 2>/dev/null) || true
  [[ "${http_code}" == "200" ]]
}

deploy_restart_in_progress() {
  [[ -f "${DEPLOY_LOCK_FILE}" ]] || return 1
  local lock_mtime age
  lock_mtime=$(stat --printf='%Y' "${DEPLOY_LOCK_FILE}" 2>/dev/null) || return 1
  age=$(( $(date +%s) - lock_mtime ))
  if [[ "${age}" -gt "${DEPLOY_LOCK_MAX_AGE_SEC}" ]]; then
    log_line "WARN: stale deploy lock (${age}s > ${DEPLOY_LOCK_MAX_AGE_SEC}s), removing ${DEPLOY_LOCK_FILE}"
    rm -f "${DEPLOY_LOCK_FILE}"
    return 1
  fi
  return 0
}

health_ok=true
if deploy_restart_in_progress; then
  health_ok=false
  log_line "SKIP health alert: deploy/restart in progress (${DEPLOY_LOCK_FILE})"
elif check_health; then
  if [[ -f "${HEALTH_STATE_FILE}" ]]; then
    rm -f "${HEALTH_STATE_FILE}"
    log_line "RECOVERED: health check passing again"
    send_telegram "✅ *Harle is back online* ($(date '+%H:%M %Z'))"
  fi
else
  health_ok=false
  if [[ ! -f "${HEALTH_STATE_FILE}" ]]; then
    touch "${HEALTH_STATE_FILE}"

    container_status="unknown"
    if [[ -f "${HARLE_REPO_DIR}/docker-compose.yml" ]]; then
      container_status="$(docker compose "${COMPOSE_ARGS[@]}" ps --format '{{.Service}}: {{.State}}' 2>/dev/null || echo 'docker query failed')"
    fi

    log_line "DOWN: health check failed. Container status: ${container_status}"
    send_telegram "🔴 *Harle is DOWN* — health check failed ($(date '+%H:%M %Z'))
Container status: \`${container_status}\`"
  fi
fi

# --- Disk usage check ---

root_usage=$(df / --output=pcent | tail -1 | tr -d ' %')

if [[ "${root_usage}" -ge "${DISK_WARN_PCT}" ]]; then
  if [[ ! -f "${DISK_STATE_FILE}" ]]; then
    touch "${DISK_STATE_FILE}"
    log_line "DISK_WARN: root partition at ${root_usage}% (threshold: ${DISK_WARN_PCT}%)"
    send_telegram "⚠️ *Disk usage warning* — root partition at *${root_usage}%* (threshold: ${DISK_WARN_PCT}%) ($(date '+%H:%M %Z'))"
  fi
else
  if [[ -f "${DISK_STATE_FILE}" ]]; then
    rm -f "${DISK_STATE_FILE}"
    log_line "DISK_CLEARED: root partition at ${root_usage}% (below ${DISK_WARN_PCT}%)"
    send_telegram "✅ *Disk usage cleared* — root partition at *${root_usage}%* ($(date '+%H:%M %Z'))"
  fi
fi

if [[ "${health_ok}" == "true" ]]; then
  log_line "OK: health=pass disk=${root_usage}%"
fi
