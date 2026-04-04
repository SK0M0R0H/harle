#!/usr/bin/env bash
# Weekly LLM usage report: fetch /metrics/usage and send a Telegram summary.
# Designed to be run manually or via a weekly cron / systemd timer.
# Reuses the same Telegram bot/chat as health-monitor.sh.
set -euo pipefail

HARLE_API_URL="${HARLE_API_URL:-http://127.0.0.1:8000}"
API_TOKEN="${HARLE_API_TOKEN:-}"
REPORT_DAYS="${HARLE_USAGE_REPORT_DAYS:-7}"
LOG_FILE="${USAGE_REPORT_LOG_FILE:-${HOME}/usage-report.log}"

TELEGRAM_BOT_TOKEN="${HARLE_TELEGRAM_ALERT_BOT_TOKEN:-}"
TELEGRAM_CHAT_ID="${HARLE_TELEGRAM_ALERT_CHAT_ID:-}"

log_line() {
  printf "[%s] %s\n" "$(date -Iseconds)" "$*" >> "${LOG_FILE}"
}

send_telegram() {
  local message="$1"
  if [[ -z "${TELEGRAM_BOT_TOKEN}" || -z "${TELEGRAM_CHAT_ID}" ]]; then
    log_line "TELEGRAM_SKIP: ${message}"
    echo "${message}"
    return 0
  fi
  curl -sf -X POST \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d chat_id="${TELEGRAM_CHAT_ID}" \
    -d text="${message}" \
    -d parse_mode="Markdown" > /dev/null 2>&1 || \
    log_line "WARN: Telegram send failed"
}

# --- Fetch usage data ---

auth_header=()
if [[ -n "${API_TOKEN}" ]]; then
  auth_header=(-H "Authorization: Bearer ${API_TOKEN}")
fi

usage_json=$(curl -fsS --connect-timeout 10 --max-time 30 \
  "${auth_header[@]}" \
  "${HARLE_API_URL}/metrics/usage?days=${REPORT_DAYS}" 2>/dev/null) || {
  log_line "ERROR: failed to fetch /metrics/usage"
  exit 1
}

# --- Parse JSON (requires jq) ---

if ! command -v jq &>/dev/null; then
  log_line "WARN: jq not installed — sending raw JSON"
  send_telegram "📊 *Harle Usage Report* (${REPORT_DAYS}d)
\`\`\`
${usage_json}
\`\`\`"
  exit 0
fi

run_count=$(echo "${usage_json}" | jq -r '.run_count // 0')
tokens_in=$(echo "${usage_json}" | jq -r '.tokens_input // 0')
tokens_out=$(echo "${usage_json}" | jq -r '.tokens_output // 0')
cost=$(echo "${usage_json}" | jq -r '.estimated_cost // 0')
since=$(echo "${usage_json}" | jq -r '.since // "?"' | cut -dT -f1)
until_date=$(echo "${usage_json}" | jq -r '.until // "?"' | cut -dT -f1)

model_lines=$(echo "${usage_json}" | jq -r '
  .by_model[]? |
  "  • \(.model): \(.run_count) runs, \(.tokens_input)+\(.tokens_output) tok"
' 2>/dev/null || echo "  (no model breakdown)")

message="📊 *Harle Usage Report*
Period: ${since} → ${until_date} (${REPORT_DAYS}d)

*Runs:* ${run_count}
*Tokens:* ${tokens_in} in / ${tokens_out} out
*Est. cost:* \$${cost}

*By model:*
${model_lines}"

log_line "Report: runs=${run_count} tokens_in=${tokens_in} tokens_out=${tokens_out} cost=${cost}"
send_telegram "${message}"
