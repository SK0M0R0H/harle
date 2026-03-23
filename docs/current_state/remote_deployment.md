---
title: "Harle Remote Deployment — Current State"
tags: [deployment, remote, infrastructure, security, cd, monitoring, current-state, implementation-status]
context: global
last_updated: 2026-03-23
summary: "Tracks what the remote deployment infrastructure implements vs the TRD, and what each missing part would unlock."
---

# Harle Remote Deployment — Current State

> This document compares the target design in the Remote Deployment TRD with the codebase. It describes what is implemented, what is partial, and what is missing, and what each missing part would unlock.

Reference TRD: [Harle Remote Deployment — Infrastructure, Security & Operations](../trd/remote_deployment.md).

---

## Overall Status

**Nothing is implemented yet.** The TRD is newly created. Harle currently runs only as a local development setup: `harle-server` on localhost, PostgreSQL via Docker, vault on the local filesystem. There is no Dockerfile, no `docker-compose.yml` for production, no remote server setup, no CI/CD pipeline, no monitoring, and no multi-client authentication.

---

## Implementation Snapshot

| TRD area | Current status | Notes |
|----------|----------------|-------|
| Dockerfile | Not implemented | No Dockerfile exists in the repository |
| docker-compose.yml (production) | Not implemented | No Compose file exists; README shows a `docker run` command for PostgreSQL only |
| Server hardening script | Not implemented | No `scripts/server-init.sh` |
| Deployment runbook | Not implemented | No `docs/runbooks/remote-setup.md` |
| Tailscale setup | Not implemented | Mentioned in overview.md as the networking plan |
| Vault sync (Git-based) | Not implemented | No `scripts/vault-sync.sh` |
| Vault sync (Syncthing) | Not implemented | — |
| Auto-reindex after sync | Partially available | `/reindex` API endpoint exists; no filesystem watcher or sync trigger |
| API token authentication | Not implemented | No auth middleware; server binds to `127.0.0.1` (localhost only) |
| CLI remote server config | Not implemented | CLI hardcodes `http://127.0.0.1:8000` or reads from config without auth |
| Client identification header | Not implemented | — |
| CD pipeline (GitHub Actions) | Not implemented | No `.github/workflows/deploy.yml` |
| Deploy pull script | Not implemented | No `scripts/deploy-pull.sh` |
| Health monitoring script | Not implemented | No `scripts/health-monitor.sh` |
| Telegram alerting | Not implemented | — |
| DB backup cron | Not implemented | — |
| Telegram bot interface | Not implemented | — |
| Caddy reverse proxy | Not implemented | — |
| `.env.example` (server) | Not implemented | Existing `.env` pattern is for local development |

---

## What Is Implemented

Nothing specific to remote deployment is implemented. The following existing components are prerequisites that already work:

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

- **Missing:** Dockerfile, production docker-compose.yml, server hardening script, deployment runbook, Tailscale setup documentation.
- **Unlocks:** Harle running 24/7 on a remote server, accessible from any Tailscale-connected device.

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

None — the TRD is newly created with no implementation yet.

---

## Assessment

The existing architecture (stateless API, conversation model, health endpoints, re-index endpoint) provides a solid foundation for remote deployment. The primary work is infrastructure: containerization, networking, synchronization, and operational tooling. No changes to the core orchestrator or data layer are required for Phase 1.
