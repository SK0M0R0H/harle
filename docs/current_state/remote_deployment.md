---
title: "Harle Remote Deployment — Current State"
tags: [deployment, remote, infrastructure, security, cd, monitoring, current-state, implementation-status, vault-sync, api-auth]
context: global
last_updated: 2026-03-30
summary: "Tracks what the remote deployment infrastructure implements vs the TRD, and what each missing part would unlock."
---

# Harle Remote Deployment — Current State

> This document compares the target design in the Remote Deployment TRD with the codebase. It describes what is implemented, what is partial, and what is missing, and what each missing part would unlock.

Reference TRD: [Harle Remote Deployment — Infrastructure, Security & Operations](../trd/remote_deployment.md).

---

## Overall Status

**Phases 1–4 are implemented.** Harle has a manual remote deployment baseline (Docker, compose, server init, runbook, CLI remote URL), optional Git-based vault synchronization, bearer API authentication with client identification logging, **and** a continuous deployment pipeline (GitHub Actions → GHCR → server pull timer). Phases 5–6 remain pending.

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
| Health monitoring script | Not implemented | No `scripts/health-monitor.sh` |
| Telegram alerting | Not implemented | — |
| DB backup cron | Not implemented | — |
| Telegram bot interface | Not implemented | — |
| Caddy reverse proxy | Not implemented | — |
| `.env.example` (server) | Implemented | Includes `HARLE_VAULT_PATH`, `HARLE_API_URL`, `HARLE_API_TOKEN`, `HARLE_IMAGE_TAG`, `DEPLOY_LOG_FILE` (commented), deployment keys |

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

- **Missing:** Health check script, Telegram alert integration, disk usage monitoring, DB backup cron.
- **Unlocks:** Automatic notification when the server goes down; daily database backups.

### 6. Telegram bot (Phase 6)

- **Missing:** Telegram bot adapter, Docker Compose service, conversation mapping.
- **Unlocks:** Mobile access to Harle via Telegram; first non-CLI interface.

---

## Key Deviations from TRD

- **Compose uses dual-file approach for image source:** `docker-compose.yml` retains `build: .` for local development; `docker-compose.prod.yml` overrides with `image:` from GHCR for production. The TRD's single-file approach is replaced by this compose override pattern, which keeps dev and prod paths cleanly separated.
- **Server init script includes deploy-key bootstrap:** `scripts/server-init.sh` now generates a GitHub deploy key and SSH config to support private repository cloning. This expands convenience beyond the minimal hardening list but supports practical private-repo deployment.
- **Vault sync uses `OnUnitActiveSec=2min`:** interval is ~2 minutes from end of each run (not wall-clock `OnCalendar`), which matches the TRD intent; exact cadence varies slightly with job duration.

---

## Assessment

Remote deployment has a working manual baseline, automated vault Git sync and reindex, bearer API authentication for safe multi-client remote use, and a continuous deployment pipeline (push to `main` -> GHCR -> server auto-pull). Harle can be provisioned on a VPS with documented steps and reached over the **public internet** (SSH and optional port 8000) by default; **optional** Tailscale-only inbound matches the TRD’s hardened network posture. The next highest-value gaps are **monitoring (Phase 5)** and the **Telegram bot (Phase 6)**.
