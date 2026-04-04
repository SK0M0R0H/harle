#!/usr/bin/env bash
# Database backup: pg_dump via docker compose, compress, upload to S3-compatible storage.
# Intended for systemd user timer (daily); load env via EnvironmentFile in the unit.
set -euo pipefail

HARLE_REPO_DIR="${HARLE_REPO_DIR:-${HOME}/harle}"
BACKUP_DIR="${HARLE_BACKUP_DIR:-${HOME}/harle-backups}"
LOG_FILE="${DB_BACKUP_LOG_FILE:-${HOME}/db-backup.log}"
S3_BUCKET="${HARLE_BACKUP_S3_BUCKET:-}"
S3_ENDPOINT="${HARLE_BACKUP_S3_ENDPOINT:-}"
RETENTION_DAYS="${HARLE_BACKUP_RETENTION_DAYS:-7}"
LOCAL_KEEP_DAYS=2

COMPOSE_ARGS=(
  -f "${HARLE_REPO_DIR}/docker-compose.yml"
  -f "${HARLE_REPO_DIR}/docker-compose.prod.yml"
)

DATE_STAMP="$(date +%Y-%m-%d-%H%M%S)"
DUMP_FILENAME="harle-${DATE_STAMP}.sql.gz"
DUMP_PATH="${BACKUP_DIR}/${DUMP_FILENAME}"
S3_PREFIX="harle-db"

log_line() {
  printf "[%s] %s\n" "$(date -Iseconds)" "$*" >> "${LOG_FILE}"
}

die() {
  log_line "ERROR: $*"
  echo "db-backup: $*" >&2
  exit 1
}

aws_cmd() {
  if [[ -n "${S3_ENDPOINT}" ]]; then
    aws --endpoint-url "${S3_ENDPOINT}" "$@"
  else
    aws "$@"
  fi
}

# --- Validate prerequisites ---

if [[ ! -f "${HARLE_REPO_DIR}/docker-compose.yml" ]]; then
  die "docker-compose.yml not found in ${HARLE_REPO_DIR}"
fi

mkdir -p "${BACKUP_DIR}" || die "cannot create backup directory ${BACKUP_DIR}"
cd "${HARLE_REPO_DIR}" || die "cannot cd to ${HARLE_REPO_DIR}"

# --- Dump database ---

# Use POSTGRES_USER / POSTGRES_DB from inside the db container (same as compose/.env),
# not hardcoded defaults, so custom credentials still backup correctly.
log_line "Starting pg_dump..."
if ! docker compose "${COMPOSE_ARGS[@]}" exec -T db \
    sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' 2>>"${LOG_FILE}" | gzip > "${DUMP_PATH}"; then
  rm -f "${DUMP_PATH}"
  die "pg_dump failed"
fi

dump_size=$(stat --printf='%s' "${DUMP_PATH}" 2>/dev/null || echo 0)
if [[ "${dump_size}" -lt 100 ]]; then
  rm -f "${DUMP_PATH}"
  die "pg_dump produced an empty or suspiciously small file (${dump_size} bytes)"
fi

log_line "Dump complete: ${DUMP_PATH} (${dump_size} bytes)"

# --- Upload to S3 ---

s3_upload_ok=false

if [[ -z "${S3_BUCKET}" ]]; then
  log_line "WARN: HARLE_BACKUP_S3_BUCKET not set — backup is local only"
else
  if ! command -v aws &>/dev/null; then
    log_line "WARN: aws CLI not found — skipping S3 upload"
  else
    s3_dest="s3://${S3_BUCKET}/${S3_PREFIX}/${DUMP_FILENAME}"
    log_line "Uploading to ${s3_dest}..."
    if aws_cmd s3 cp "${DUMP_PATH}" "${s3_dest}" 2>>"${LOG_FILE}"; then
      log_line "Upload complete: ${s3_dest}"
      s3_upload_ok=true
    else
      log_line "ERROR: S3 upload failed — keeping local backup"
    fi
  fi
fi

# --- S3 retention: delete remote objects older than RETENTION_DAYS ---

if [[ "${s3_upload_ok}" == "true" ]]; then
  log_line "Checking S3 retention (keeping ${RETENTION_DAYS} days)..."
  cutoff_epoch=$(date -d "-${RETENTION_DAYS} days" +%s 2>/dev/null || date -v-"${RETENTION_DAYS}"d +%s 2>/dev/null || echo 0)

  if [[ "${cutoff_epoch}" -gt 0 ]]; then
    if s3_objects_listing="$(
      aws_cmd s3api list-objects-v2 \
        --bucket "${S3_BUCKET}" \
        --prefix "${S3_PREFIX}/" \
        --query "Contents[].{Key: Key, LastModified: LastModified}" \
        --output text 2>>"${LOG_FILE}"
    )"; then
      while IFS=$'\t' read -r key last_modified; do
        [[ -z "${key}" || "${key}" == "None" ]] && continue
        obj_epoch=$(date -d "${last_modified}" +%s 2>/dev/null || echo 0)
        if [[ "${obj_epoch}" -gt 0 && "${obj_epoch}" -lt "${cutoff_epoch}" ]]; then
          log_line "Deleting expired backup: s3://${S3_BUCKET}/${key}"
          aws_cmd s3 rm "s3://${S3_BUCKET}/${key}" 2>>"${LOG_FILE}" || \
            log_line "WARN: failed to delete s3://${S3_BUCKET}/${key}"
        fi
      done <<< "${s3_objects_listing}"
    else
      log_line "WARN: unable to list S3 objects for retention; skipping remote cleanup"
    fi
  fi
fi

# --- Local retention: keep staging files for LOCAL_KEEP_DAYS (or longer if S3 failed) ---

if [[ "${s3_upload_ok}" == "true" ]]; then
  deleted_count=0
  for f in "${BACKUP_DIR}"/harle-*.sql.gz; do
    [[ -f "${f}" ]] || continue
    file_age_days=$(( ( $(date +%s) - $(stat --printf='%Y' "${f}" 2>/dev/null || echo 0) ) / 86400 ))
    if [[ "${file_age_days}" -ge "${LOCAL_KEEP_DAYS}" ]]; then
      rm -f "${f}"
      deleted_count=$((deleted_count + 1))
    fi
  done
  if [[ "${deleted_count}" -gt 0 ]]; then
    log_line "Cleaned ${deleted_count} local staging file(s) older than ${LOCAL_KEEP_DAYS} days"
  fi
else
  log_line "S3 upload did not succeed — keeping all local backups"
fi

log_line "Backup run complete"
