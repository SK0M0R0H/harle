#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SKIP_SYSTEM_DEPS="${HARLE_SETUP_SKIP_SYSTEM_DEPS:-0}"
VENV_DIR="${HARLE_SETUP_VENV_DIR:-.venv}"
DATASET_PATH="${HARLE_DATASET_PATH:-$HOME/harle-vault}"
DB_CONTAINER="${HARLE_DB_CONTAINER:-harle-db}"
DB_USER="${HARLE_DB_USER:-harle}"
DB_PASSWORD="${HARLE_DB_PASSWORD:-harle}"
DB_NAME="${HARLE_DB_NAME:-harle}"
DB_PORT="${HARLE_DB_PORT:-5432}"
DB_HOST="${HARLE_DB_HOST:-localhost}"
DB_PROVISION_MODE="${HARLE_DB_PROVISION_MODE:-docker}"

log() { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
warn() { printf '\n[WARN] %s\n' "$*"; }

has_cmd() { command -v "$1" >/dev/null 2>&1; }

usage() {
  cat <<USAGE
Usage: ./scripts/setup.sh [options]

Options:
  --db-provision-mode <docker|external|skip>  How PostgreSQL is prepared.
      docker   = create/start container from this script (default)
      external = assume DB container/service is started outside this script (recommended for WSL2)
      skip     = skip DB provisioning entirely
  --db-host <hostname>                         Database host (default: localhost)
  --db-port <port>                             Database port (default: 5432)
  -h, --help                                   Show this help

Examples:
  ./scripts/setup.sh --db-provision-mode docker
  ./scripts/setup.sh --db-provision-mode external --db-host localhost --db-port 5432
USAGE
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --db-provision-mode)
        DB_PROVISION_MODE="${2:-}"
        shift 2
        ;;
      --db-host)
        DB_HOST="${2:-}"
        shift 2
        ;;
      --db-port)
        DB_PORT="${2:-}"
        shift 2
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        echo "Unknown argument: $1" >&2
        usage
        exit 1
        ;;
    esac
  done

  case "$DB_PROVISION_MODE" in
    docker|external|skip) ;;
    *)
      echo "Invalid --db-provision-mode: '$DB_PROVISION_MODE' (expected: docker|external|skip)" >&2
      exit 1
      ;;
  esac
}

install_system_deps() {
  if [[ "$SKIP_SYSTEM_DEPS" == "1" ]]; then
    warn "Skipping system dependency installation (HARLE_SETUP_SKIP_SYSTEM_DEPS=1)."
    return 0
  fi

  if has_cmd apt-get; then
    if has_cmd sudo; then
      log "Installing system packages via apt-get (python3, venv, pip, golang, docker)."
      sudo apt-get update
      sudo apt-get install -y python3 python3-venv python3-pip golang-go docker.io
    else
      warn "apt-get detected, but sudo is unavailable. Install python3/go/docker manually if missing."
    fi
  elif has_cmd brew; then
    log "Installing system packages via Homebrew (python, go, docker)."
    brew install python go docker
  else
    warn "No supported package manager detected. Ensure python3, go, and docker are installed."
  fi
}

configure_database_url() {
  local db_url="postgresql+psycopg2://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}"

  if [[ -n "${DATABASE_URL:-}" ]]; then
    log "Using existing DATABASE_URL from environment."
  else
    export DATABASE_URL="$db_url"
    log "Set DATABASE_URL for setup flow (${DB_HOST}:${DB_PORT}/${DB_NAME})."
  fi
}

start_postgres_container_if_needed() {
  if [[ "$DB_PROVISION_MODE" == "skip" ]]; then
    warn "Skipping PostgreSQL provisioning by request (--db-provision-mode skip)."
    return 0
  fi

  if [[ "$DB_PROVISION_MODE" == "external" ]]; then
    log "Using externally managed PostgreSQL (--db-provision-mode external)."
    return 0
  fi

  if ! has_cmd docker; then
    warn "Docker is not installed. Cannot auto-provision PostgreSQL in docker mode."
    return 0
  fi

  if ! docker info >/dev/null 2>&1; then
    warn "Docker daemon is not running or inaccessible. Cannot auto-provision PostgreSQL in docker mode."
    return 0
  fi

  if docker ps --format '{{.Names}}' | grep -Fxq "$DB_CONTAINER"; then
    log "PostgreSQL container '$DB_CONTAINER' is already running."
  elif docker ps -a --format '{{.Names}}' | grep -Fxq "$DB_CONTAINER"; then
    log "Starting existing PostgreSQL container '$DB_CONTAINER'."
    docker start "$DB_CONTAINER" >/dev/null
  else
    log "Creating PostgreSQL container '$DB_CONTAINER' on port ${DB_PORT}."
    docker run -d --name "$DB_CONTAINER" \
      -e POSTGRES_USER="$DB_USER" \
      -e POSTGRES_PASSWORD="$DB_PASSWORD" \
      -e POSTGRES_DB="$DB_NAME" \
      -p "${DB_PORT}:5432" \
      postgres:16 >/dev/null
  fi
}

write_config() {
  if [[ ! -f config.yaml ]]; then
    log "Creating config.yaml from config.example.yaml."
    cp config.example.yaml config.yaml
  else
    log "config.yaml already exists; preserving existing values and filling missing keys."
  fi

  python3 - <<'PY'
from pathlib import Path
import os
import yaml

config_path = Path('config.yaml')
raw = yaml.safe_load(config_path.read_text(encoding='utf-8'))
if not isinstance(raw, dict):
    raw = {}

if 'HARLE_DATASET_PATH' not in raw or not raw['HARLE_DATASET_PATH']:
    raw['HARLE_DATASET_PATH'] = os.environ['HARLE_DATASET_PATH']

if 'DATABASE_URL' not in raw or not raw['DATABASE_URL']:
    db_url = os.environ.get('DATABASE_URL')
    if db_url:
        raw['DATABASE_URL'] = db_url

config_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding='utf-8')
PY
}

main() {
  parse_args "$@"

  log "Starting Harle setup from zero to ready-to-launch."
  log "Database provisioning mode: ${DB_PROVISION_MODE}"

  install_system_deps

  if ! has_cmd python3; then
    echo "python3 is required but was not found." >&2
    exit 1
  fi

  if ! has_cmd go; then
    warn "Go not found. CLI build step will fail until Go 1.22+ is installed."
  fi

  export HARLE_DATASET_PATH="$DATASET_PATH"
  mkdir -p "$HARLE_DATASET_PATH"
  log "Using dataset path: $HARLE_DATASET_PATH"

  configure_database_url
  start_postgres_container_if_needed

  log "Setting up Python virtual environment in $VENV_DIR"
  python3 -m venv "$VENV_DIR"
  # shellcheck disable=SC1090
  source "$VENV_DIR/bin/activate"

  log "Upgrading pip and installing Harle package."
  python3 -m pip install --upgrade pip
  python3 -m pip install -e .

  write_config

  if has_cmd go; then
    log "Building Harle CLI binary."
    mkdir -p harle-cli/bin
    (cd harle-cli && go build -o bin/harle ./cmd/harle)
  fi

  log "Running bootstrap initialization (creates tables, seeds vault, indexes files)."
  if ! harle-init; then
    warn "harle-init failed. Check DATABASE_URL and PostgreSQL availability."
  fi

  cat <<DONE

Harle setup complete.

Next steps:
1) Activate env:   source ${VENV_DIR}/bin/activate
2) Start server:   harle-server
3) In a new shell: cd harle-cli && ./bin/harle --context work

Optional env vars:
- OPENAI_API_KEY=...   (required for OpenAI provider)
- TAVILY_API_KEY=...   (enables web search tools)
DONE
}

main "$@"
