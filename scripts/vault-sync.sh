#!/usr/bin/env bash
# Server-side vault sync: git pull (fast-forward), optional reindex, push server logs.
# Intended for systemd user timer; load env via EnvironmentFile in the unit or export manually.
set -euo pipefail

: "${HARLE_VAULT_PATH:?Set HARLE_VAULT_PATH to the host vault git checkout (see .env.example).}"

HARLE_API_URL="${HARLE_API_URL:-http://127.0.0.1:8000}"
LOG_FILE="${VAULT_SYNC_LOG_FILE:-${HOME}/vault-sync.log}"
VAULT_SYNC_BRANCH="${VAULT_SYNC_BRANCH:-main}"
VAULT_SYNC_REMOTE="${VAULT_SYNC_REMOTE:-origin}"

log_line() {
  printf "[%s] %s\n" "$(date -Iseconds)" "$*" >> "${LOG_FILE}"
}

die() {
  log_line "ERROR: $*"
  echo "vault-sync: $*" >&2
  exit 1
}

if [[ ! -d "${HARLE_VAULT_PATH}" ]]; then
  die "HARLE_VAULT_PATH is not a directory: ${HARLE_VAULT_PATH}"
fi

cd "${HARLE_VAULT_PATH}" || die "cannot cd to ${HARLE_VAULT_PATH}"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  die "not a git repository: ${HARLE_VAULT_PATH}"
fi

before_sha="$(git rev-parse HEAD)"

if ! git fetch "${VAULT_SYNC_REMOTE}"; then
  die "git fetch ${VAULT_SYNC_REMOTE} failed"
fi

merge_ref="${VAULT_SYNC_REMOTE}/${VAULT_SYNC_BRANCH}"
if ! git rev-parse --verify "${merge_ref}" >/dev/null 2>&1; then
  die "missing ref ${merge_ref} (fetch succeeded? branch name correct?)"
fi

if ! git merge --ff-only "${merge_ref}"; then
  log_line "ERROR: fast-forward merge failed for ${merge_ref}; resolve manually on server"
  echo "vault-sync: fast-forward failed, manual merge needed" >&2
  exit 1
fi

after_sha="$(git rev-parse HEAD)"
if [[ "${before_sha}" != "${after_sha}" ]]; then
  log_line "Pulled new commits ${before_sha:0:7}..${after_sha:0:7}; triggering reindex"
  reindex_url="${HARLE_API_URL%/}/reindex"
  _body="$(mktemp)"
  curl_args=(-sS -o "${_body}" -w "%{http_code}" -X POST "${reindex_url}")
  if [[ -n "${HARLE_API_TOKEN:-}" ]]; then
    curl_args+=(-H "Authorization: Bearer ${HARLE_API_TOKEN}")
  fi
  set +e
  http_code="$(curl "${curl_args[@]}" 2>>"${LOG_FILE}" || echo "000")"
  _curl_rc=$?
  set -e
  rm -f "${_body}"
  if [[ "${_curl_rc}" -ne 0 ]]; then
    log_line "WARN: reindex curl failed (rc=${_curl_rc}) for ${reindex_url}"
  elif [[ "${http_code}" != "200" ]]; then
    log_line "WARN: reindex POST ${reindex_url} returned HTTP ${http_code} (Harle down or misconfigured?)"
  else
    log_line "Reindex completed (HTTP ${http_code})"
  fi
else
  log_line "No new commits on ${merge_ref}"
fi

# Stage server-written run logs under vault (bind-mounted dataset path)
if [[ -d logs ]]; then
  git add logs/ || true
fi

if git diff --cached --quiet; then
  log_line "No local vault changes to push"
  exit 0
fi

if ! git commit -m "vault-sync: server logs"; then
  log_line "ERROR: git commit failed — set user.name and user.email in ${HARLE_VAULT_PATH}"
  die "git commit failed (configure git identity in the vault repo)"
fi

if ! git push "${VAULT_SYNC_REMOTE}" "${VAULT_SYNC_BRANCH}"; then
  log_line "ERROR: git push ${VAULT_SYNC_REMOTE} ${VAULT_SYNC_BRANCH} failed"
  exit 1
fi

log_line "Pushed server vault changes to ${VAULT_SYNC_REMOTE}/${VAULT_SYNC_BRANCH}"
exit 0
