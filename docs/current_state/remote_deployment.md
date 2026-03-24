---
title: "Harle Remote Deployment — Current State"
tags: [deployment, remote, infrastructure, security, cd, monitoring, current-state, implementation-status]
context: global
last_updated: 2026-03-24
summary: "Tracks what the remote deployment infrastructure implements vs the TRD, and what each missing part would unlock."
---

# Harle Remote Deployment — Current State

> This document compares the target design in the Remote Deployment TRD with the codebase. It describes what is implemented, what is partial, and what is missing, and what each missing part would unlock.

Reference TRD: [Harle Remote Deployment — Infrastructure, Security & Operations](../trd/remote_deployment.md).

---

## Overall Status

**Phase 1 is implemented.** Harle now has the core artifacts for a manual remote deployment: containerization, production compose stack, server initialization/hardening script, private-repo setup path, and CLI config support for persistent remote server URLs. Deployment is still manual (SSH + pull + restart), and later phases remain pending.

---

## Implementation Snapshot

| TRD area | Current status | Notes |
|----------|----------------|-------|
| Dockerfile | Implemented | `Dockerfile` added; runs `harle-server` as non-root user |
| docker-compose.yml (production) | Implemented | `docker-compose.yml` added with `harle` + `db`, health checks, restart policies, and localhost bind |
| Server hardening script | Implemented | `scripts/server-init.sh` added (SSH hardening, UFW, unattended-upgrades, Docker, Tailscale) |
| Deployment runbook | Implemented | `docs/runbooks/remote-setup.md` added |
| Tailscale setup | Implemented | Included in `scripts/server-init.sh` and runbook |
| Vault sync (Git-based) | Not implemented | No `scripts/vault-sync.sh` |
| Vault sync (Syncthing) | Not implemented | — |
| Auto-reindex after sync | Partially available | `/reindex` API endpoint exists; no filesystem watcher or sync trigger |
| API token authentication | Not implemented | No auth middleware; server binds to `127.0.0.1` (localhost only) |
| CLI remote server config | Implemented | CLI now resolves server URL via `--server`, `HARLE_SERVER_URL`, or `~/.config/harle/cli.yaml` |
| Client identification header | Not implemented | — |
| CD pipeline (GitHub Actions) | Not implemented | No `.github/workflows/deploy.yml` |
| Deploy pull script | Not implemented | No `scripts/deploy-pull.sh` |
| Health monitoring script | Not implemented | No `scripts/health-monitor.sh` |
| Telegram alerting | Not implemented | — |
| DB backup cron | Not implemented | — |
| Telegram bot interface | Not implemented | — |
| Caddy reverse proxy | Not implemented | — |
| `.env.example` (server) | Implemented | `.env.example` now includes deployment keys (`DATABASE_URL`, `HARLE_DATASET_PATH`, `HARLE_HOST`, Postgres vars) |

---

## What Is Implemented

### Phase 1 deliverables

- **Docker image build** — `Dockerfile` and `.dockerignore` added for a lean Python service image.
- **Compose deployment stack** — `docker-compose.yml` added with:
  - `harle` container (`restart: unless-stopped`, localhost-only `127.0.0.1:8000` binding).
  - `db` container (`pgvector/pgvector:pg16`, persistent `pgdata`, healthcheck).
  - basic hardening defaults (`no-new-privileges`, memory limits).
- **Server bootstrap/hardening script** — `scripts/server-init.sh` added for one-time host setup, including GitHub deploy key generation for private repo pulls.
- **Remote setup runbook** — `docs/runbooks/remote-setup.md` added with end-to-end provisioning, clone, compose startup, initialization, and verification.
- **CLI remote server persistence** — Go CLI now supports `~/.config/harle/cli.yaml` (`server_url`) with precedence:
  1. `--server`
  2. `HARLE_SERVER_URL`
  3. `~/.config/harle/cli.yaml`
  4. default localhost URL.
- **Server environment template** — `.env.example` now includes deployment-ready variables for compose-based remote setup.

### Existing prerequisites still in place

- **`/health` endpoint** — returns server status (usable for monitoring checks).
- **`/health/connections` endpoint** — checks external service connections.
- **`/reindex` endpoint** — triggers vault re-indexing (usable after vault sync).
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

- **Missing:** Git-based sync script, systemd timer, auto-reindex trigger after sync.
- **Unlocks:** Edit vault files locally, have them available on the server within minutes.

### 3. API security and multi-client (Phase 3)

- **Missing:** Bearer token auth middleware, CLI auth config, client identification header.
- **Unlocks:** Safe remote access; multiple devices can connect simultaneously.

### 4. Continuous deployment (Phase 4)

- **Missing:** GitHub Actions workflow for build+push, server-side deploy-pull script, systemd timer.
- **Unlocks:** Push to main → automatic deployment. No SSH needed for routine updates.

### 5. Monitoring and alerting (Phase 5)

- **Missing:** Health check script, Telegram alert integration, disk usage monitoring, DB backup cron.
- **Unlocks:** Automatic notification when the server goes down; daily database backups.

### 6. Telegram bot (Phase 6)

- **Missing:** Telegram bot adapter, Docker Compose service, conversation mapping.
- **Unlocks:** Mobile access to Harle via Telegram; first non-CLI interface.

---

## Key Deviations from TRD

- **Compose image source differs for Phase 1:** the compose file builds from local source (`build: .`) instead of pulling from `ghcr.io`. This is intentional and aligns with Phase 1 manual deployment; image registry flow is deferred to Phase 4 (CD).
- **Server init script includes deploy-key bootstrap:** `scripts/server-init.sh` now generates a GitHub deploy key and SSH config to support private repository cloning. This expands convenience beyond the minimal hardening list but supports practical private-repo deployment.

---

## Assessment

Remote deployment moved from "not started" to a working manual baseline. Harle can now be provisioned on a VPS with documented steps and deployed as containers on a private Tailscale-accessible endpoint. The next highest-value gaps are API authentication (Phase 3), vault sync automation (Phase 2), and automated deployment/monitoring (Phases 4-5).
