---
title: "Harle Remote Deployment — Current State"
tags: [deployment, remote, infrastructure, security, cd, monitoring, current-state, implementation-status, vault-sync, api-auth]
context: global
last_updated: 2026-04-04
summary: "Tracks what the remote deployment infrastructure implements vs the TRD, and what each missing part would unlock."
---

# Harle Remote Deployment — Current State

> This document compares the target design in the Remote Deployment TRD with the codebase. It describes what is implemented, what is partial, and what is missing, and what each missing part would unlock.

Reference TRD: [Harle Remote Deployment — Infrastructure, Security & Operations](../trd/remote_deployment.md).

---

## Overall Status

**Phases 1–5 are implemented.** Harle has a manual remote deployment baseline (Docker, compose, server init, runbook, CLI remote URL), optional Git-based vault synchronization, bearer API authentication with client identification logging, a continuous deployment pipeline (GitHub Actions → GHCR → server pull timer), **and** monitoring with Telegram alerts, disk usage checks, daily database backups to S3-compatible storage, and usage tracking infrastructure (dummy — token population pending). Phase 6 (Telegram bot) remains pending.

---

## Implementation Snapshot

| TRD area | Current status | Notes |
|----------|----------------|-------|
| Dockerfile | Implemented | `Dockerfile` added; runs `harle-server` as non-root user |
| docker-compose.yml (production) | Implemented | `docker-compose.yml` added with `harle` + `db`, health checks, restart policies, and localhost bind |
| Server bootstrap script | Implemented | `scripts/server-init.sh` — SSH hardening, UFW (OpenSSH + optional public `:8000`), unattended-upgrades, Docker, GitHub deploy key (no Tailscale) |
| Optional Tailscale hardening | Implemented | `scripts/server-hardening-tailscale.sh` + runbook phase 11 |
| Deployment runbook | Implemented | `docs/runbooks/remote-setup.md` — baseline public path, optional Tailscale-only UFW, optional vault sync §12, API token §8b |
| Vault sync (Git-based) | Implemented | `scripts/vault-sync.sh` — `git fetch` / fast-forward merge, conditional `POST /reindex`, commit+push `logs/` |
| Vault sync (Syncthing) | Not implemented | — |
| Auto-reindex after sync | Implemented | Triggered from `vault-sync.sh` when `HEAD` advances after merge; `/reindex` endpoint unchanged |
| Systemd vault-sync timer | Implemented | `scripts/systemd/harle-vault-sync.service` + `harle-vault-sync.timer` (~2 min); user installs under `~/.config/systemd/user/` |
| API token authentication | Implemented | `BearerAuthMiddleware` in `src/harle/api/auth.py` when `HARLE_API_TOKEN` is set (non-empty); `/health*` exempt; timing-safe compare |
| CLI remote server config | Implemented | CLI resolves server URL via `--server`, `HARLE_SERVER_URL`, or `~/.config/harle/cli.yaml` |
| CLI API token | Implemented | `--token`, `HARLE_API_TOKEN`, or `api_token` in `cli.yaml`; sends `Authorization` + `X-Harle-Client: harle-cli` |
| Client identification header | Implemented | Optional `X-Harle-Client` logged on `/chat`, `/init`, `/reindex`, `/import`, capture interview routes; `vault-sync.sh` sends `vault-sync` |
| CD pipeline (GitHub Actions) | Implemented | `.github/workflows/deploy.yml` — lint, test, build+push to GHCR, post-deploy health check |
| Production compose override | Implemented | `docker-compose.prod.yml` — replaces `build:` with `image:` from GHCR |
| Deploy pull script | Implemented | `scripts/deploy-pull.sh` — pulls image, compares digest, restarts if changed, health check |
| Deploy pull systemd timer | Implemented | `scripts/systemd/harle-deploy-pull.service` + `.timer` (5 min interval) |
| Health monitoring script | Implemented | `scripts/health-monitor.sh` — API health check, disk usage, container status, Telegram alerts with state-file flood prevention |
| Telegram alerting | Implemented | Down/recovered + disk warning/cleared alerts via Telegram Bot API; graceful skip when vars unset |
| Health monitoring systemd timer | Implemented | `scripts/systemd/harle-health-monitor.service` + `.timer` (1 min interval) |
| Disk usage monitoring | Implemented | Integrated into `health-monitor.sh`; threshold via `HARLE_DISK_WARN_PCT` (default 85%) |
| DB backup (off-site) | Implemented | `scripts/db-backup.sh` — `pg_dump` via compose, gzip, upload to S3-compatible storage, remote retention |
| DB backup systemd timer | Implemented | `scripts/systemd/harle-db-backup.service` + `.timer` (daily at 03:00, `Persistent=true`) |
| Usage metrics API | Partially implemented | `GET /metrics/usage` endpoint; DB query infrastructure ready; token columns not yet populated by orchestrator |
| Usage report script | Partially implemented | `scripts/usage-report.sh` — fetches `/metrics/usage`, formats Telegram message; returns zeros until token tracking is wired |
| Telegram bot interface | Not implemented | — |
| Caddy reverse proxy | Not implemented | — |
| `.env.example` (server) | Implemented | Includes deployment, CD, monitoring (Telegram, disk, S3 backup), and API key variables |

---

## What Is Implemented

### Phase 1 deliverables

- **Docker image build** — `Dockerfile` and `.dockerignore` added for a lean Python service image.
- **Compose deployment stack** — `docker-compose.yml` added with:
  - `harle` container (`restart: unless-stopped`, published port bind configurable via `HARLE_PUBLISH_HOST`, default `127.0.0.1`).
  - `db` container (`pgvector/pgvector:pg16`, persistent `pgdata`, healthcheck).
  - basic hardening defaults (`no-new-privileges`, memory limits).
- **Server bootstrap script** — `scripts/server-init.sh` for baseline VPS setup (UFW SSH + optional API port, Docker, deploy key); Tailscale is **not** part of baseline.
- **Optional Tailscale hardening** — `scripts/server-hardening-tailscale.sh` switches UFW to inbound only on `tailscale0` after interactive confirmation.
- **Remote setup runbook** — `docs/runbooks/remote-setup.md` documents public-IP (or SSH tunnel) first, then optional phase 11 for Tailscale.
- **CLI remote server persistence** — Go CLI supports `~/.config/harle/cli.yaml` (`server_url`) with precedence:
  1. `--server`
  2. `HARLE_SERVER_URL`
  3. `~/.config/harle/cli.yaml`
  4. default localhost URL.
- **Server environment template** — `.env.example` includes deployment-ready variables including `HARLE_VAULT_PATH`, `HARLE_API_URL`, and documented `HARLE_API_TOKEN` for compose and vault-sync.

### Phase 2 deliverables

- **`scripts/vault-sync.sh`** — On the host: requires `HARLE_VAULT_PATH` (git checkout); fast-forward merge from `origin/main` (override via `VAULT_SYNC_BRANCH` / `VAULT_SYNC_REMOTE`); calls `POST ${HARLE_API_URL}/reindex` only when `HEAD` changes; optional `Authorization: Bearer` when `HARLE_API_TOKEN` is set; **`X-Harle-Client: vault-sync`** on reindex; stages `logs/`, commits `vault-sync: server logs`, pushes to the vault remote; logs to `VAULT_SYNC_LOG_FILE` or `~/vault-sync.log`.
- **Systemd user units** — `scripts/systemd/harle-vault-sync.service` (oneshot, `EnvironmentFile` `~/harle/.env`) and `harle-vault-sync.timer` (`OnUnitActiveSec=2min`); runbook documents `loginctl enable-linger` and enablement.
- **Runbook vault Git guide** — `docs/runbooks/remote-setup.md` §12: private vault repo, **write** deploy key (separate from code repo), clone layout, `HARLE_VAULT_PATH`, git identity for server commits, timer install, verification, troubleshooting.

### Phase 3 deliverables

- **`HARLE_API_TOKEN` in settings** — `src/harle/config.py` `Settings`; empty/unset disables auth (local dev default).
- **Bearer middleware** — `src/harle/api/auth.py` registered from `src/harle/main.py` when token is non-empty after trim; public **`/health*`** only.
- **CLI** — Go client sends bearer + `X-Harle-Client: harle-cli` on all API calls; token resolution documented in runbook §8b.
- **Docs** — `.env.example`, runbook §5/§8/§8b/§12; E2E tests run server with a fixed test token.

### Phase 4 deliverables

- `.github/workflows/deploy.yml` — on push to `main`: lint → unit tests → Docker build → push to GHCR (`latest` + `sha-<commit>` tags). Includes `workflow_dispatch` for branch testing. Post-deploy `verify-deploy` job curls server `/health` after ~8 minutes (requires `DEPLOY_HOST` secret).
- `docker-compose.prod.yml` — production override that replaces `build:` with `image: ghcr.io/sk0m0r0h/harle:${HARLE_IMAGE_TAG:-latest}`.
- `scripts/deploy-pull.sh` — pulls image via compose, compares digest with running container, restarts `harle` if changed, retries health check up to 6 times.
- `scripts/systemd/harle-deploy-pull.service` + `.timer` — user systemd units; polls every 5 minutes.
- Runbook §13 — GHCR auth, prod compose, timer install, rollback procedure, verification, troubleshooting.

### Phase 5 deliverables

- **`scripts/health-monitor.sh`** — Checks API health (`/health`), root disk usage (configurable threshold via `HARLE_DISK_WARN_PCT`, default 85%), and container status. Uses state files to prevent alert flooding — sends one "down" and one "recovered" notification per incident. Gracefully skips Telegram when bot token/chat ID are unset (logs locally instead).
- **`scripts/systemd/harle-health-monitor.service` + `.timer`** — User systemd units running every 1 minute (`OnUnitActiveSec=1min`).
- **`scripts/db-backup.sh`** — Dumps PostgreSQL via `docker compose exec -T db pg_dump`, compresses with gzip, uploads to S3-compatible storage (`HARLE_BACKUP_S3_BUCKET` + optional `HARLE_BACKUP_S3_ENDPOINT` for non-AWS providers). Remote retention deletes S3 objects older than `HARLE_BACKUP_RETENTION_DAYS` (default 7). Local staging files cleaned after 2 days; kept if S3 upload fails. Gracefully degrades to local-only if S3 bucket is not configured.
- **`scripts/systemd/harle-db-backup.service` + `.timer`** — User systemd units running daily at 03:00 (`OnCalendar`, `Persistent=true`).
- **`scripts/usage-report.sh`** — Skeleton script that fetches `GET /metrics/usage?days=7`, formats a Telegram summary with run count, token usage, estimated cost, and per-model breakdown. Returns zeros until token tracking is wired into the orchestrator.
- **`src/harle/db/usage.py`** — Aggregation queries over the `runs` table: `get_usage_summary()` (totals + per-model breakdown) and `get_usage_by_day()` (daily breakdown). Coalesces NULL token columns to zero.
- **`GET /metrics/usage`** endpoint — Authenticated endpoint returning `UsageResponse` with token/cost aggregates, per-model and per-day breakdowns. Query parameter `days` (1–90, default 7).
- **`.env.example`** — Added monitoring section with `HARLE_TELEGRAM_ALERT_BOT_TOKEN`, `HARLE_TELEGRAM_ALERT_CHAT_ID`, `HARLE_DISK_WARN_PCT`, `HARLE_BACKUP_S3_BUCKET`, `HARLE_BACKUP_S3_ENDPOINT`, `HARLE_BACKUP_RETENTION_DAYS`, and log file paths.
- **Runbook §14** — Monitoring and alerting guide: Telegram bot setup, health-monitor and db-backup timer installation, S3 backup configuration (Backblaze B2 example), verification steps, restore procedure, troubleshooting.

### Existing prerequisites still in place

- **`/health` endpoint** — returns server status (usable for monitoring checks).
- **`/health/connections` endpoint** — checks external service connections.
- **`/reindex` endpoint** — triggers vault re-indexing after vault sync when `HEAD` advances.
- **PostgreSQL via Docker** — README documents `docker run` for a local PostgreSQL container.
- **Hash-based indexing** — `src/harle/indexing/indexer.py` detects file changes by content hash (efficient re-indexing after sync).
- **Conversation model with `conversation_id`** — supports multi-client by design (each client uses its own conversation ID).
- **Stateless HTTP API** — all state in PostgreSQL; any number of clients can connect.

---

## What Is Not Implemented Yet

### 1. Basic remote deployment (Phase 1)

- **Status:** Implemented.
- **Delivered:** Dockerization, compose stack, server setup script, runbook, and CLI remote config persistence.
- **TRD follow-up (optional hardening):** The TRD now recommends post-deployment hardening checks (for example `stop_grace_period` tuning and memory/restart observation). These are operational tuning steps and are not yet codified in compose defaults.

### 2. Vault synchronization (Phase 2)

- **Status:** Implemented (Git-based path). Syncthing alternative not implemented.
- **Delivered:** `vault-sync.sh`, systemd timer templates, runbook §12, conditional reindex + log push-back.
- **Operational note:** Server run logs live under the vault bind mount (`logs/`); container-only paths (e.g. separate log volumes) are not synced by this script.

### 3. API security and multi-client (Phase 3)

- **Status:** Implemented.
- **Delivered:** Bearer auth when `HARLE_API_TOKEN` is set; CLI and vault-sync integration; `X-Harle-Client` logging on selected routes.

### 4. Continuous deployment (Phase 4)

- **Status:** Implemented.
- **Delivered:**
  - `.github/workflows/deploy.yml` — on push to `main`: lint → unit tests → Docker build → push to GHCR (`latest` + `sha-<commit>` tags). Includes `workflow_dispatch` for branch testing. Post-deploy `verify-deploy` job curls server `/health` after ~8 minutes (requires `DEPLOY_HOST` secret).
  - `docker-compose.prod.yml` — production override that replaces `build:` with `image: ghcr.io/sk0m0r0h/harle:${HARLE_IMAGE_TAG:-latest}`.
  - `scripts/deploy-pull.sh` — pulls image via compose, compares digest with running container, restarts `harle` if changed, retries health check up to 6 times.
  - `scripts/systemd/harle-deploy-pull.service` + `.timer` — user systemd units; polls every 5 minutes.
  - Runbook §13 — GHCR auth, prod compose, timer install, rollback procedure, verification, troubleshooting.
  - `.env.example` — `HARLE_IMAGE_TAG` and `DEPLOY_LOG_FILE` added.

### 5. Monitoring and alerting (Phase 5)

- **Status:** Implemented (core monitoring). Usage tracking partially implemented (infrastructure ready, token population pending).
- **Delivered:** Health monitor script with Telegram alerts, disk usage monitoring, daily DB backup to S3-compatible storage, usage metrics API endpoint, usage report script.
- **Remaining gap:** The orchestrator does not yet populate `tokens_input` / `tokens_output` / `estimated_cost` on run rows (see `TODO(phase5-usage)` in `src/harle/orchestrator/finalize.py`). Once wired, `/metrics/usage` and `usage-report.sh` will report real data.

### 6. Telegram bot (Phase 6)

- **Missing:** Telegram bot adapter, Docker Compose service, conversation mapping.
- **Unlocks:** Mobile access to Harle via Telegram; first non-CLI interface.

---

## Key Deviations from TRD

- **Compose uses dual-file approach for image source:** `docker-compose.yml` retains `build: .` for local development; `docker-compose.prod.yml` overrides with `image:` from GHCR for production. The TRD's single-file approach is replaced by this compose override pattern, which keeps dev and prod paths cleanly separated.
- **Server init script includes deploy-key bootstrap:** `scripts/server-init.sh` now generates a GitHub deploy key and SSH config to support private repository cloning. This expands convenience beyond the minimal hardening list but supports practical private-repo deployment.
- **Vault sync uses `OnUnitActiveSec=2min`:** interval is ~2 minutes from end of each run (not wall-clock `OnCalendar`), which matches the TRD intent; exact cadence varies slightly with job duration.
- **DB backup uses S3 off-site storage:** The TRD Phase 5 table describes "Daily `pg_dump` to a backup directory with 7-day retention". The implementation uploads to S3-compatible storage (as recommended in the TRD Technology Choices table) with remote retention, since local-only backups do not protect against server loss. Local copies are staging only (2-day retention).
- **Usage tracking is infrastructure-only (dummy):** The `/metrics/usage` endpoint and `usage-report.sh` exist but return zeros because the orchestrator does not yet populate token columns on run rows. This is intentional — the query, API, and reporting infrastructure is in place for when token tracking is wired.

---

## Assessment

Remote deployment has a working manual baseline, automated vault Git sync and reindex, bearer API authentication for safe multi-client remote use, a continuous deployment pipeline (push to `main` -> GHCR -> server auto-pull), and operational monitoring with Telegram alerts, disk usage checks, and daily off-site database backups. Harle can be provisioned on a VPS with documented steps and reached over the **public internet** (SSH and optional port 8000) by default; **optional** Tailscale-only inbound matches the TRD’s hardened network posture. Usage tracking infrastructure (`/metrics/usage`, aggregation queries, report script) is in place but returns zeros until the orchestrator populates token columns. The next highest-value gap is the **Telegram bot (Phase 6)**.
