---
title: "Harle Remote Deployment — Infrastructure, Security & Operations"
tags: [deployment, remote, infrastructure, security, cd, monitoring, vault-sync, multi-client, vps, docker, tailscale]
context: global
last_updated: 2026-03-23
summary: "Describes the remote deployment architecture for Harle: server setup, security hardening, vault synchronization, continuous deployment, monitoring and alerting, and parallel multi-client access."
---

# Harle Remote Deployment — Infrastructure, Security & Operations

> Running Harle locally is good for development. Running it on a remote server makes it a true 24/7 personal assistant — accessible from your desktop CLI, a Telegram bot on your phone, or any future interface, anywhere, at any time.

This document describes everything needed to take Harle from a local development setup to a production-grade remote deployment: how to set up and harden a server, how to keep the vault synchronized between local editing and the remote instance, how to deploy code changes automatically, how to know when something breaks, and how to handle multiple clients connecting simultaneously.

For the overall system architecture, see [architecture/overview.md](./architecture/overview.md).
For the CLI (primary interface), see [architecture/cli.md](./architecture/cli.md).
For the Connections Layer (external service credentials), see [architecture/connections.md](./architecture/connections.md).

---

## Why Remote Deployment

Harle running on a laptop has three limitations:

| Limitation | Impact | Remote deployment solves it |
|---|---|---|
| **Laptop must be open** | Harle is unavailable when you close the lid, commute, or switch machines | Server runs 24/7 — always reachable |
| **Single device** | Only the machine running harle-server can use the CLI | Any device (desktop, phone, tablet) connects to the same server |
| **No mobile access** | CLI requires a terminal on the same machine | Telegram bot, web UI, or SSH from phone — all hit the same API |

The remote deployment architecture must preserve Harle's core property: **data stays under your control**. No managed AI platforms, no third-party hosting of your vault. You run Harle on a machine you own or rent, with your data on its filesystem, accessible only to your devices.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        YOUR DEVICES                                 │
│                                                                     │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐            │
│  │  Desktop CLI  │   │ Telegram Bot │   │  Web UI      │            │
│  │  (Go binary)  │   │  (mobile)    │   │  (future)    │            │
│  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘            │
│         │                  │                   │                     │
└─────────┼──────────────────┼───────────────────┼────────────────────┘
          │                  │                   │
          │         Tailscale (WireGuard mesh)   │
          │                  │                   │
┌─────────┼──────────────────┼───────────────────┼────────────────────┐
│         │          REMOTE SERVER (VPS)         │                     │
│         ▼                  ▼                   ▼                     │
│  ┌──────────────────────────────────────────────────────────┐       │
│  │                    Caddy (reverse proxy)                  │       │
│  │              TLS termination + rate limiting              │       │
│  └──────────────────────────┬───────────────────────────────┘       │
│                             │                                       │
│  ┌──────────────────────────▼───────────────────────────────┐       │
│  │                  Docker Compose stack                     │       │
│  │                                                          │       │
│  │  ┌─────────────────┐  ┌──────────────┐                  │       │
│  │  │  harle-server    │  │  PostgreSQL   │                  │       │
│  │  │  (Python/FastAPI) │  │  (pgvector)   │                  │       │
│  │  │  port 8000       │  │  port 5432    │                  │       │
│  │  └────────┬─────────┘  └──────────────┘                  │       │
│  │           │                                              │       │
│  │  ┌────────▼─────────┐                                    │       │
│  │  │  Vault (volume)   │                                    │       │
│  │  │  ~/harle-vault/   │                                    │       │
│  │  └──────────────────┘                                    │       │
│  └──────────────────────────────────────────────────────────┘       │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────┐       │
│  │  Monitoring: health-check cron + Telegram/email alerts    │       │
│  └──────────────────────────────────────────────────────────┘       │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**Key properties:**

- **Private network only.** The server is not exposed to the public internet — zero public ports. All client connections go through Tailscale (WireGuard-based mesh VPN).
- **Disposable server.** The vault lives in Git, the database is backed up off-site. If the server dies or becomes inaccessible, you provision a new one and restore from backups in under 30 minutes. No data is lost except the gap since the last backup.
- **Docker Compose.** The application stack (harle-server + PostgreSQL) runs in containers with volume-mounted data. Upgrades are container replacements, not in-place mutations.
- **Vault sync.** The vault is synchronized between your local editing environment (Obsidian, VS Code) and the server via Git or Syncthing. You edit locally; the server reads the synced copy.
- **Multi-client.** The HTTP API is stateless per-request (state lives in PostgreSQL). Any number of clients can connect simultaneously — desktop CLI and Telegram bot share the same conversations, memories, and vault.

---

## 1. Server Setup

### Hardware requirements

Harle is lightweight — it proxies requests to external LLM APIs and runs a PostgreSQL instance. The compute-heavy work (model inference) happens at OpenAI, not on your server.

| Resource | Minimum | Recommended | Why |
|---|---|---|---|
| **CPU** | 1 vCPU | 2 vCPU | Python async + PostgreSQL + Whoosh indexing |
| **RAM** | 1 GB | 2 GB | PostgreSQL shared buffers + Python process + search index |
| **Disk** | 10 GB | 20 GB | OS + Docker images + vault + DB data + logs |
| **Network** | Any | 1 Gbps | Low bandwidth usage; latency matters more than throughput |

**Recommended providers** (cheap, reliable, good EU/US locations):

| Provider | Smallest viable plan | Cost/month |
|---|---|---|
| Hetzner Cloud (CX22) | 2 vCPU, 4 GB RAM, 40 GB | ~€4 |
| DigitalOcean (Basic) | 1 vCPU, 1 GB RAM, 25 GB | ~$6 |
| OVH (Starter) | 1 vCPU, 2 GB RAM, 20 GB | ~€3.50 |

A home mini-PC (Intel NUC, Raspberry Pi 5) works too if you have a stable internet connection and don't mind managing hardware.

### OS and base image

**Ubuntu 24.04 LTS** — the most common server OS, best Docker support, long-term security updates (until 2029).

### Initial setup steps

The initial setup is a one-time procedure. It produces a server that is hardened, has Docker installed, is on your Tailscale network, and is ready for the application deployment.

```
1. Create VPS instance (Ubuntu 24.04, SSH key auth, no password auth)
2. Connect via SSH
3. Run initial hardening (see §2 Security Hardening)
4. Install Docker + Docker Compose
5. Install and configure Tailscale
6. Clone the Harle repository
7. Configure environment (.env, config.yaml)
8. Start the Docker Compose stack
9. Run harle-init (inside the container)
10. Verify: health check from a Tailscale-connected device
```

Detailed commands for each step are provided in the deployment runbook (`docs/runbooks/remote-setup.md`, created as part of Phase 1).

---

## 2. Security Hardening

Security follows a layered approach: network isolation, OS hardening, application security, and secret management. The goal is "secure enough for a personal server" — not enterprise compliance, but enough to prevent common attacks.

### Network layer

| Control | What it does | Implementation |
|---|---|---|
| **Tailscale-only access** | Only devices on your Tailscale network can reach the server | Bind harle-server to `127.0.0.1` or Tailscale IP only; firewall drops all other inbound traffic |
| **No public ports** | SSH, HTTP API, PostgreSQL are all internal-only | `ufw` allows only Tailscale interface + fallback SSH |
| **WireGuard encryption** | All traffic between devices is encrypted end-to-end | Provided by Tailscale (WireGuard under the hood) |

**Tailscale setup:**

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --ssh
```

With `--ssh`, Tailscale provides SSH access over the mesh network.

**Firewall rules (ufw):**

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow in on tailscale0
sudo ufw enable
```

This drops all inbound traffic except from the Tailscale network. No public SSH, no public HTTP, no public PostgreSQL — zero public attack surface.

**Disposable server model — why no fallback SSH is needed:**

With off-site backups (see "Data durability" below), the server is disposable. If Tailscale dies, the server is inaccessible — but nothing is lost:

1. **Vault** — lives in Git (local machine + remote). The server copy is a clone.
2. **Database** — daily `pg_dump` pushed off-site. At most one day of conversations lost.
3. **Configuration** — `.env` values stored in a password manager.

Recovery is: provision a new VPS, install Tailscale (or its replacement), restore from backups, start Docker Compose. The entire process is scripted and takes under 30 minutes.

This is a stronger security posture than keeping a fallback SSH port. A public SSH port — even hardened with key-only auth and fail2ban — is still an attack surface. Zero open ports means zero attack surface.

**Tailscale dependency and alternatives:**

Tailscale is a convenience layer on top of WireGuard. It depends on Tailscale Inc.'s coordination server for peer discovery and NAT traversal. If Tailscale as a company shuts down or their service goes offline permanently, the Tailscale client stops working. When that happens, you provision a new server with a different networking solution:

| Alternative | External dependency | NAT traversal | Setup effort | When to consider |
|---|---|---|---|---|
| **Tailscale** (current) | Tailscale coordination server | Automatic | Minimal | Default choice — works until it doesn't |
| **Raw WireGuard** | None — fully self-hosted | Requires a public IP or port forward | Medium | If Tailscale shuts down, or you want zero external dependencies |
| **Headscale** | Self-hosted (your own coordination server) | Automatic (same as Tailscale) | Medium-high | Tailscale-compatible but fully self-hosted |
| **Cloudflare Tunnel** | Cloudflare | Automatic | Low | If you already use Cloudflare; trades one company dependency for another |

**Raw WireGuard** is the zero-dependency option: same encryption protocol, same performance, but you configure peer keys and endpoints manually instead of relying on a coordination server. The VPS has a public IP, so no NAT traversal is needed for the server side; only mobile/laptop clients behind NAT need to initiate connections (which WireGuard handles natively).

**Headscale** is an open-source, self-hosted replacement for Tailscale's coordination server. You run it on your VPS and get the same automatic peer discovery and NAT traversal as Tailscale, with no external dependency.

### OS hardening

With no public ports, the OS attack surface is minimal — an attacker cannot reach any service on the server from the public internet. The hardening below is defense-in-depth for the Tailscale-accessible SSH and for scenarios where the network configuration changes.

| Control | What it protects against | How |
|---|---|---|
| **Key-only SSH** | Brute-force if SSH is ever exposed | `PasswordAuthentication no` in `/etc/ssh/sshd_config` |
| **No root SSH** | Privilege escalation from user to full OS compromise | `PermitRootLogin no` in `/etc/ssh/sshd_config` |
| **Automatic security updates** | Known vulnerabilities exploited before you patch | `unattended-upgrades` package (Ubuntu default, verify enabled) |
| **Non-root Docker** | Container escape leading to host-level root | `USER harle` in Dockerfile; rootless Docker mode (optional, advanced) |

### Application security

| Control | What it does | Implementation |
|---|---|---|
| **API authentication** | Only authorized clients can call the API | Bearer token in `Authorization` header; token set via env var `HARLE_API_TOKEN` |
| **HTTPS (internal)** | Encrypts API traffic even within Tailscale | Caddy reverse proxy with automatic Tailscale HTTPS certificate (`tailscale cert`) |
| **Vault file permissions** | Limit vault writes to the Harle process only | Docker volume mounted read-write, owned by the `harle` container user; host-level permissions restrict access to the deploy user |
| **Secret isolation** | API keys never in config files or Docker images | `.env` file on host, referenced in `docker-compose.yml` via `env_file`; `.env` has `600` permissions |
| **Container isolation** | Application and DB run in separate containers with minimal capabilities | Docker Compose default networking; `no-new-privileges` security opt |

**API token authentication:**

A lightweight middleware checks every request for a valid bearer token. This prevents unauthorized access even if someone gains access to the Tailscale network (defense-in-depth).

```python
# Conceptual — added to FastAPI middleware
async def verify_api_token(request: Request):
    expected = os.environ.get("HARLE_API_TOKEN")
    if not expected:
        return  # no token configured = no auth (dev mode)
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    if token != expected:
        raise HTTPException(status_code=401, detail="Invalid API token")
```

The CLI and Telegram bot include the token in every request. The token is a random string generated once during setup.

### Secret management

| Secret | Where it lives | How it's protected |
|---|---|---|
| `OPENAI_API_KEY` | `.env` on the server | File permissions `600`, owned by deploy user |
| `TAVILY_API_KEY` | `.env` on the server | Same |
| `HARLE_API_TOKEN` | `.env` on the server; also configured in CLI config on each device | Same |
| `DATABASE_URL` | `.env` or `docker-compose.yml` (internal Docker network, no external access) | PostgreSQL only listens on Docker internal network |
| Tailscale auth key | Used once during setup, then revoked | Single-use key from Tailscale admin console |

### 24/7 reliability hardening

| Concern | Solution | Details |
|---|---|---|
| **Process crashes** | Docker restart policy | `restart: unless-stopped` in `docker-compose.yml` |
| **OOM kills** | Memory limits per container | `deploy.resources.limits.memory` in Compose |
| **Disk full** | Log rotation + vault log cleanup | `logrotate` for Docker logs; periodic cleanup of old vault logs |
| **DB corruption** | PostgreSQL WAL + periodic backups | Daily `pg_dump` via cron to local backup directory (and optionally off-site) |
| **OS reboot** | Docker service auto-start | `systemctl enable docker` (default on Ubuntu) |
| **Stale connections** | Connection pool health checks | SQLAlchemy `pool_pre_ping=True` (already set); periodic connection recycling |
| **Runaway requests** | Request timeout | FastAPI middleware or Uvicorn `--timeout-keep-alive`; per-request timeout in orchestrator |

### Data durability — surviving server loss

The worst case is not a crash (Docker restarts it) or a Tailscale outage (fallback SSH). The worst case is **total server loss**: the VPS provider deletes your instance, the disk dies, or you lose access permanently. In that scenario, the only data that survives is data that exists somewhere else.

**What needs to survive and where it already lives:**

| Data | Recreatable? | Copies that already exist | What's needed |
|---|---|---|---|
| **Vault (user-authored files)** | No — years of personal knowledge | Local machine (primary editing copy) + Git remote | Already safe if you use Git with a remote. The server copy is a clone. |
| **Vault (server-written logs)** | Partially — run logs can be regenerated from DB, but not perfectly | Only on the server (until synced back) | Git-based sync (§3) pushes logs to the remote. Sync frequency determines max data loss. |
| **PostgreSQL (conversations, memories, runs, file index)** | `file_index` is recreatable via re-index. Conversations, memories, and run history are not. | Only on the server | **Off-site backups required.** Daily `pg_dump` pushed to a second location. |
| **`.env` (API keys, tokens)** | Yes — you can re-enter them | Should also exist in a password manager | No automated backup needed; keep a copy in your password manager. |
| **Docker images** | Yes — pulled from the container registry | Container registry (ghcr.io) | No backup needed. |

**Off-site database backup:**

Daily `pg_dump` stored only on the same server protects against DB corruption but not against server loss. The backup must be pushed off the server:

```bash
#!/usr/bin/env bash
# scripts/db-backup.sh — run daily via cron
set -euo pipefail

BACKUP_DIR="$HOME/harle-backups"
REMOTE_BUCKET="s3://harle-backups"  # or rclone remote, or scp target
RETENTION_DAYS=30

mkdir -p "$BACKUP_DIR"
FILENAME="harle-db-$(date +%Y%m%d-%H%M%S).sql.gz"

# Dump and compress
docker exec harle-db pg_dump -U harle harle | gzip > "$BACKUP_DIR/$FILENAME"

# Push off-site (pick one)
# Option A: S3-compatible storage (Backblaze B2, Hetzner Object Storage, AWS S3)
# aws s3 cp "$BACKUP_DIR/$FILENAME" "$REMOTE_BUCKET/$FILENAME"
#
# Option B: rclone (supports 40+ cloud storage providers)
# rclone copy "$BACKUP_DIR/$FILENAME" remote:harle-backups/
#
# Option C: scp to another machine (your laptop, a second VPS)
# scp "$BACKUP_DIR/$FILENAME" backup-host:~/harle-backups/

# Clean up old local backups
find "$BACKUP_DIR" -name "harle-db-*.sql.gz" -mtime +$RETENTION_DAYS -delete
```

**Recommended off-site storage options:**

| Option | Cost | Setup effort | Notes |
|---|---|---|---|
| **Backblaze B2** | $0.005/GB/month (first 10 GB free) | Low (S3-compatible API) | Cheapest. A full Harle DB dump is likely <100 MB. |
| **Hetzner Object Storage** | €0.005/GB/month | Low | Same provider as the VPS = simple billing |
| **scp to your laptop** | Free | Minimal | Works if your laptop is on Tailscale; not always-on |
| **Second Git repo** | Free (GitHub private) | Low | Works for small dumps (<100 MB); not ideal for large DBs |

**Recovery from total server loss:**

```
1. Provision a new VPS, run server-init.sh
2. Clone the Harle repo, restore .env from password manager
3. Clone the vault from Git remote (full history preserved)
4. Restore DB from the latest off-site backup:
   gunzip < harle-db-YYYYMMDD.sql.gz | docker exec -i harle-db psql -U harle harle
5. docker compose up -d
6. Verify: /health, /search, test a /chat request
```

Maximum data loss: the period between the last successful backup and the failure. With daily backups, you lose at most one day of conversations and run history. The vault (user-authored content) loses nothing because it's in Git.

---

## 3. Vault Synchronization

The vault is the core dataset — Markdown files that you edit locally (in Obsidian, VS Code, or any editor) and that Harle reads on the server. Keeping these in sync is critical.

### Design constraints

1. **Local editing is primary.** You edit files on your laptop. The server reads them. The sync is one-directional for user-authored content (local → server).
2. **Server writes logs.** The Harle server writes run logs (`logs/YYYY/MM/`) and possibly capture interview output to the vault. These should sync back to your local machine (server → local).
3. **Conflicts are rare but possible.** If you edit a file locally while the server writes a log with a similar path, the sync system must handle it gracefully.
4. **Low latency preferred.** After you save a file locally, it should be available on the server within seconds to minutes — not hours.

### Option A: Git-based sync (recommended for v1)

The vault is already a Git repository (recommended in [overview.md](./architecture/overview.md)). Git-based sync is the natural extension.

```
┌─────────────────┐          ┌─────────────────┐          ┌─────────────────┐
│  Local machine   │          │  Git remote      │          │  Remote server   │
│  (editing)       │          │  (GitHub/Gitea)  │          │  (Harle runs)   │
│                  │   push   │                  │   pull   │                  │
│  ~/harle-vault/  │────────>│  harle-vault.git │────────>│  ~/harle-vault/  │
│                  │          │                  │          │                  │
│  git add/commit  │          │  bare repo       │          │  cron/webhook    │
│  git push        │          │  (private)       │          │  git pull        │
└─────────────────┘          └─────────────────┘          └─────────────────┘
```

**How it works:**

1. **Local:** You edit vault files and commit + push to a private Git remote (GitHub private repo, self-hosted Gitea, or even a bare repo on the same VPS).
2. **Server:** A cron job or systemd timer runs `git pull` every N minutes (e.g., every 2 minutes). Alternatively, a webhook from the Git remote triggers an immediate pull.
3. **Server writes:** Run logs written by Harle are committed and pushed by the server (via a separate cron job or a post-run hook). Your local machine pulls these on demand or on a timer.

**Advantages:** Simple, uses existing tools, provides full version history, handles conflicts via standard Git merge.

**Disadvantages:** Not real-time (2-minute delay with cron). Requires Git commits for every change (can be automated). Conflicts require manual resolution (rare in practice — user edits knowledge/, server writes logs/).

**Server-side sync script (`scripts/vault-sync.sh`):**

```bash
#!/usr/bin/env bash
cd "$HARLE_VAULT_PATH" || exit 1

git fetch origin
git merge --ff-only origin/main || {
    echo "Vault sync: fast-forward failed, manual merge needed" >&2
    exit 1
}

# Optionally trigger re-index after sync
curl -s -X POST "http://127.0.0.1:8000/reindex" \
     -H "Authorization: Bearer $HARLE_API_TOKEN" || true
```

After a successful pull, the script triggers a re-index so new/changed files are immediately searchable.

### Option B: Syncthing (alternative for real-time sync)

[Syncthing](https://syncthing.net/) provides real-time, bidirectional file sync without a central server.

```
┌─────────────────┐                              ┌─────────────────┐
│  Local machine   │◄───── Syncthing (p2p) ─────►│  Remote server   │
│  ~/harle-vault/  │        encrypted relay       │  ~/harle-vault/  │
└─────────────────┘                              └─────────────────┘
```

**Advantages:** Real-time sync (sub-second). No Git commits needed. Bidirectional (logs sync back automatically). No central repo.

**Disadvantages:** No version history (Syncthing has file versioning, but it's not Git). Conflict resolution is automatic but opaque (keeps both versions with a conflict suffix). One more service to run and maintain.

**When to use Syncthing:** If you want instant sync and don't care about Git history for the vault, or if you want to use Git locally for version history but Syncthing for the transport layer.

### Re-indexing after sync

Regardless of the sync method, the server must re-index the vault after changes arrive. Two approaches:

1. **Filesystem watcher (inotify/watchdog).** A lightweight process watches the vault directory for changes and triggers `/reindex` when files are modified. Fast, event-driven.
2. **Periodic cron.** Simpler: run `/reindex` every N minutes. Acceptable for Git-based sync where changes arrive in batches.

The re-index operation uses hash-based change detection (already implemented in `src/harle/indexing/indexer.py`), so re-indexing unchanged files is a no-op.

---

## 4. Continuous Deployment (CD)

CD automates the process of deploying code changes from the Git repository to the running server. The goal: merge to `main`, and the server updates itself within minutes.

### Deployment pipeline

```
┌──────────┐     ┌──────────────┐     ┌──────────────────┐     ┌──────────────┐
│  Git push │────>│  GitHub       │────>│  Server pulls     │────>│  Docker      │
│  to main  │     │  Actions CI   │     │  new image/code   │     │  restart     │
└──────────┘     │  (test+build) │     │                   │     │  (zero-down) │
                  └──────────────┘     └──────────────────┘     └──────────────┘
```

### Strategy: pull-based deployment (recommended)

The server periodically checks for updates and applies them. This avoids the need for inbound webhooks or a CI runner on the server.

**How it works:**

1. **CI (GitHub Actions):** On push to `main`, run tests. If tests pass, build a Docker image and push it to a container registry (GitHub Container Registry `ghcr.io`, or Docker Hub).
2. **Server:** A cron job or systemd timer runs every N minutes (e.g., every 5 minutes):
   - Pulls the latest image from the registry.
   - If the image digest changed, runs `docker compose up -d` (which recreates only the changed containers).
   - Logs the deployment event.

**Server-side deployment script (`scripts/deploy-pull.sh`):**

```bash
#!/usr/bin/env bash
set -euo pipefail

COMPOSE_DIR="$HOME/harle"
LOG_FILE="$HOME/harle-deploy.log"

cd "$COMPOSE_DIR"

# Pull latest images
docker compose pull --quiet 2>/dev/null

# Check if anything changed
CURRENT=$(docker compose images -q | sort | md5sum)
docker compose up -d --remove-orphans 2>/dev/null
UPDATED=$(docker compose images -q | sort | md5sum)

if [ "$CURRENT" != "$UPDATED" ]; then
    echo "$(date -Iseconds) Deployed new version" >> "$LOG_FILE"
    # Run post-deploy health check
    sleep 10
    curl -sf "http://127.0.0.1:8000/health" >> /dev/null || {
        echo "$(date -Iseconds) WARN: health check failed after deploy" >> "$LOG_FILE"
    }
fi
```

### Alternative: webhook-based deployment

If you want instant deployment (not polling), use a lightweight webhook receiver on the server:

1. GitHub Actions sends a webhook (or `curl`) to a deploy endpoint on the server after a successful build.
2. The server receives the webhook, pulls the new image, and restarts.

This requires the webhook endpoint to be reachable — either via Tailscale (GitHub Actions connects through a Tailscale exit node or a Tailscale GitHub Action) or via a small public endpoint that only accepts signed payloads.

For simplicity, the pull-based approach is recommended for Phase 1.

### CI pipeline (GitHub Actions)

```yaml
# .github/workflows/deploy.yml (conceptual)
name: Build and Deploy
on:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[test]"
      - run: python -m pytest tests/unit tests/integration

  build-and-push:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v5
        with:
          push: true
          tags: ghcr.io/${{ github.repository }}/harle-server:latest
```

### Dockerfile

The Dockerfile packages the Python orchestrator into a container image:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["harle-server"]
```

The Go CLI is built separately (or distributed as a binary) — it runs on client devices, not on the server.

### Docker Compose (production)

```yaml
services:
  harle:
    image: ghcr.io/<owner>/harle/harle-server:latest
    restart: unless-stopped
    env_file: .env
    ports:
      - "127.0.0.1:8000:8000"
    volumes:
      - ${HARLE_VAULT_PATH:-./vault}:/data/vault
      - harle-logs:/data/logs
    depends_on:
      db:
        condition: service_healthy
    deploy:
      resources:
        limits:
          memory: 1G

  db:
    image: pgvector/pgvector:pg16
    restart: unless-stopped
    environment:
      POSTGRES_USER: harle
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
      POSTGRES_DB: harle
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U harle"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          memory: 512M

volumes:
  pgdata:
  harle-logs:
```

### Rollback

If a deployment breaks the server:

1. **Automatic:** The health-check-based monitoring (§5) detects the failure and alerts.
2. **Manual rollback:** `docker compose pull ghcr.io/.../harle-server:previous-tag && docker compose up -d`. Tag `latest` plus at least one previous version are retained.
3. **Image pinning:** For critical stability, pin the image tag in `docker-compose.yml` to a specific version instead of `:latest`.

---

## 5. Monitoring and Alerting

The server must notify you if it stops working, without you having to check manually.

### What to monitor

| Check | What it detects | Frequency |
|---|---|---|
| **HTTP health check** (`/health`) | Server process crashed, hung, or unreachable | Every 1–2 minutes |
| **Database health** (`/health/connections` or `pg_isready`) | PostgreSQL down, connection pool exhausted | Every 2–5 minutes |
| **Disk usage** | Vault logs or DB WAL filling the disk | Every 15 minutes |
| **Container status** | Docker container exited, restarting in a loop | Every 1–2 minutes |
| **API response time** | Performance degradation (slow LLM responses are expected, slow /health is not) | Every 2–5 minutes |
| **SSL certificate expiry** | HTTPS cert nearing expiration (if using Caddy, auto-renewed) | Daily |

### Alerting channels

| Channel | Use case | Setup complexity |
|---|---|---|
| **Telegram bot notification** | Primary — you always have your phone | Low (HTTP POST to Telegram Bot API) |
| **Email** | Backup if Telegram fails | Medium (needs SMTP or a transactional email service) |
| **Uptime monitoring service** | External perspective (confirms server is reachable from outside Tailscale) | Low (free tiers: UptimeRobot, Healthchecks.io) |

### Implementation: health check script with Telegram alerts

A minimal monitoring script runs on the server (via cron or systemd timer) and sends a Telegram message when the health check fails:

```bash
#!/usr/bin/env bash
# scripts/health-monitor.sh

HEALTH_URL="http://127.0.0.1:8000/health"
TELEGRAM_BOT_TOKEN="${HARLE_TELEGRAM_ALERT_BOT_TOKEN}"
TELEGRAM_CHAT_ID="${HARLE_TELEGRAM_ALERT_CHAT_ID}"
STATE_FILE="/tmp/harle-health-state"

check_health() {
    local http_code
    http_code=$(curl -sf -o /dev/null -w "%{http_code}" \
        --max-time 10 "$HEALTH_URL" 2>/dev/null)
    [ "$http_code" = "200" ]
}

send_telegram() {
    local message="$1"
    curl -sf -X POST \
        "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d chat_id="$TELEGRAM_CHAT_ID" \
        -d text="$message" \
        -d parse_mode="Markdown" > /dev/null 2>&1
}

if check_health; then
    if [ -f "$STATE_FILE" ]; then
        rm "$STATE_FILE"
        send_telegram "✅ *Harle is back online* ($(date '+%H:%M %Z'))"
    fi
else
    if [ ! -f "$STATE_FILE" ]; then
        touch "$STATE_FILE"
        send_telegram "🔴 *Harle is DOWN* — health check failed ($(date '+%H:%M %Z'))"
    fi
fi
```

The state file prevents alert flooding — you get one "down" notification and one "recovered" notification, not one per minute.

**Cron entry:**

```
* * * * * /home/harle/harle/scripts/health-monitor.sh
```

### External uptime monitoring

For an external perspective (confirming the server is reachable, not just self-reporting health), use a free service:

- **[Healthchecks.io](https://healthchecks.io/):** The server pings a unique URL on successful health check (a "dead man's switch"). If the ping stops, Healthchecks.io alerts you. Free tier supports 20 checks.
- **[UptimeRobot](https://uptimerobot.com/):** Monitors an HTTP endpoint from outside. Requires the endpoint to be reachable from the internet — use Tailscale Funnel or a minimal public health endpoint (returns 200, no sensitive data).

For Phase 1, the self-hosted Telegram monitoring script is sufficient. External monitoring can be added when the server is stable.

### Log aggregation

Docker logs are the primary source of operational information:

```bash
# View recent logs
docker compose logs --tail=100 harle

# Follow logs in real-time
docker compose logs -f harle

# View only errors
docker compose logs harle 2>&1 | grep -i error
```

For a more structured approach (Phase 3+), consider [Loki](https://grafana.com/oss/loki/) + [Grafana](https://grafana.com/) on the same server for log search and dashboards. This is optional — Docker logs + Telegram alerts cover the essential needs.

---

## 6. Parallel Multi-Client Connections

Harle must support multiple clients connecting simultaneously: a desktop CLI session, a Telegram bot on your phone, and potentially a web UI — all sharing the same state.

### Why this works without special effort

The Harle architecture already supports this because:

1. **Stateless HTTP API.** The FastAPI server is stateless per-request. All state (conversations, memories, run history) is in PostgreSQL. Any number of HTTP clients can hit the same API concurrently.
2. **Conversation model.** Each conversation has a unique `conversation_id`. The CLI creates a new conversation per session; the Telegram bot creates one per Telegram chat (or per thread). They don't interfere because they use different conversation IDs.
3. **No server-side sessions.** There is no "logged in" state on the server. Each request carries all needed context (message, context tag, conversation_id, API token).

### What needs to be built

| Concern | Current state | What to add |
|---|---|---|
| **API authentication** | None (localhost-only) | Bearer token middleware (§2) |
| **Client identification** | Not tracked | Optional `X-Harle-Client` header for logging (e.g., "cli-desktop", "telegram-bot") |
| **Concurrent writes** | PostgreSQL handles it | No change needed — DB transactions serialize writes |
| **Vault write conflicts** | Both user and Harle edit vault files (knowledge, logs, capture output) | Git sync handles merges. Server auto-commits before pull. True conflicts (same file edited on both sides between syncs) are resolved by Git merge; unresolvable conflicts are flagged for manual resolution. Shorter sync intervals reduce the window. |
| **Rate limiting per client** | None | Optional: per-token or per-client rate limiting in the API (prevents a runaway bot from monopolizing the server) |
| **Shared vs. separate conversations** | conversation_id-based | Each client manages its own conversations. A CLI session and a Telegram chat are separate conversations by default. Sharing is possible by passing the same `conversation_id`. |

### Client architecture patterns

**Desktop CLI (existing):**

```
CLI ──HTTP──> Tailscale ──> harle-server:8000
              (Bearer token in Authorization header)
```

The CLI already supports connecting to a remote server. Add the API token to the CLI's config:

```yaml
# ~/.config/harle/cli.yaml
server_url: "http://harle-server:8000"  # or Tailscale IP/hostname
api_token: "your-secret-token"
```

**Telegram bot (new interface):**

```
User ──Telegram──> Telegram API ──> Bot process ──HTTP──> harle-server:8000
                                    (runs on same server or separately)
```

The Telegram bot is a thin adapter:

1. Receives messages from the Telegram Bot API (via polling or webhook).
2. Maps each Telegram chat to a Harle `conversation_id` (stored in a small SQLite or in-memory map).
3. Forwards the message to `/chat` with the conversation_id and API token.
4. Sends the response back to Telegram.

The bot runs as a separate container in the Docker Compose stack (or as a standalone script). It is a consumer of the Harle API — it has no special access or dependencies.

### Concurrency considerations

| Scenario | Behavior |
|---|---|
| Two clients send messages at the same time | Both requests are processed concurrently by FastAPI (async). Each gets its own DB transaction. No conflict. |
| Two clients use the same conversation_id | Both messages are added to the same conversation. Order is determined by arrival time. Works correctly but may cause confusing interleaving (discouraged). |
| One client sends a long-running request, another sends a quick one | Both are handled by separate async tasks. The quick one finishes first. No blocking. |
| Server is processing a request when a new deploy happens | Docker Compose's default stop timeout (10s) allows in-flight requests to complete. For long-running requests, increase `stop_grace_period`. |

---

## Implementation Plan

The system is implemented in phases. Each phase produces a usable result — you can stop at any phase and have a working deployment at that level.

### Phase 1: Basic remote deployment

**Goal:** Harle runs on a remote server, accessible from any Tailscale-connected device via the CLI. Manual deployment (SSH + git pull + docker compose up).

**What is built:**

| Deliverable | Contents |
|---|---|
| `Dockerfile` | Multi-stage build for the Python orchestrator |
| `docker-compose.yml` | harle-server + PostgreSQL with volume mounts, restart policies, health checks |
| `.env.example` | Template for server-side environment variables |
| `docs/runbooks/remote-setup.md` | Step-by-step server setup guide (VPS provisioning → Tailscale → Docker → first start) |
| Server hardening script | `scripts/server-init.sh` — ufw, fail2ban, unattended-upgrades, SSH hardening |
| CLI remote config | CLI supports `server_url` config for connecting to a remote server |

**Verification:**
- Provision a VPS, run the setup guide, start Docker Compose.
- From a laptop on the same Tailscale network, run `harle exec "hello"` against the remote server.
- Verify `/health` returns 200.
- Verify restart after container kill (`docker kill harle`).

**Dependencies:** None.

**Estimated effort:** 2–3 days.

**Result:** Harle is running 24/7 on a server. You can use it from any device on your Tailscale network. Deployment is manual (SSH in, pull, restart).

---

### Phase 2: Vault synchronization

**Goal:** Vault changes made locally appear on the server automatically. Server-generated logs sync back to local.

**What is built:**

| Deliverable | Contents |
|---|---|
| `scripts/vault-sync.sh` | Server-side script: git pull + trigger re-index |
| Systemd timer | Runs vault-sync every 2 minutes |
| Vault Git setup guide | Added to the runbook: how to set up the vault as a private Git repo, configure deploy keys |
| Auto-reindex hook | Vault sync triggers `/reindex` after successful pull |

**Verification:**
- Edit a file in the local vault, commit and push.
- Within 2 minutes, verify the file is updated on the server (`curl /search?q=<new content>`).
- Verify server-written logs appear in the local vault after pull.

**Dependencies:** Phase 1.

**Estimated effort:** 1–2 days.

**Result:** You edit vault files locally (Obsidian, VS Code), and they're available to Harle on the server within minutes. Run logs sync back.

---

### Phase 3: API security and multi-client support

**Goal:** The API is protected by token authentication. Multiple clients (CLI from different devices, future Telegram bot) can connect safely.

**What is built:**

| Deliverable | Contents |
|---|---|
| API token middleware | FastAPI middleware checking `Authorization: Bearer <token>` |
| CLI auth config | CLI reads `api_token` from config and includes it in all requests |
| Client identification | Optional `X-Harle-Client` header logged for each request |
| `.env` update | `HARLE_API_TOKEN` added to `.env.example` and runbook |

**Verification:**
- Without a valid token, API returns 401.
- With a valid token from the CLI, API works normally.
- Two CLI instances (different devices) can connect simultaneously with the same token.
- Requests from different clients are logged with their client identifier.

**Dependencies:** Phase 1.

**Estimated effort:** 1 day.

**Result:** The API is authenticated. You can safely connect from multiple devices without worrying about unauthorized access.

---

### Phase 4: Continuous deployment

**Goal:** Pushing to `main` automatically deploys the new version to the server after tests pass.

**What is built:**

| Deliverable | Contents |
|---|---|
| GitHub Actions workflow | `.github/workflows/deploy.yml` — test → build Docker image → push to GHCR |
| Server-side deploy script | `scripts/deploy-pull.sh` — pulls latest image, restarts if changed |
| Systemd timer for deploy | Runs deploy-pull every 5 minutes |
| Rollback procedure | Documented in runbook: how to pin a previous image tag |

**Verification:**
- Push a code change to `main`.
- CI builds and pushes the image.
- Within 5 minutes, the server is running the new version (verify via `/health` or a version endpoint).
- Intentionally push a broken change, verify rollback procedure works.

**Dependencies:** Phase 1, Phase 3 (API token needed for deploy health check).

**Estimated effort:** 2–3 days.

**Result:** Code changes reach the server automatically. No SSH needed for routine deployments.

---

### Phase 5: Monitoring and alerting

**Goal:** You are notified (via Telegram) if the server goes down. Basic operational metrics are available.

**What is built:**

| Deliverable | Contents |
|---|---|
| `scripts/health-monitor.sh` | Health check script with Telegram alerts (down + recovery notifications) |
| Systemd timer | Runs health-monitor every 1 minute |
| Disk usage check | Added to health-monitor: alert when disk usage exceeds 85% |
| DB backup cron | Daily `pg_dump` to a backup directory with 7-day retention |
| Monitoring setup guide | Added to runbook: creating a Telegram alert bot, configuring chat ID |

**Verification:**
- Stop harle-server container. Verify Telegram notification within 2 minutes.
- Start harle-server container. Verify recovery notification.
- Verify daily DB backup runs and produces a valid dump.
- Fill disk to 85% (in a test environment). Verify disk alert fires.

**Dependencies:** Phase 1.

**Estimated effort:** 1–2 days.

**Result:** You know when Harle is down within minutes. Database is backed up daily. Disk usage is monitored.

---

### Phase 6: Telegram bot (first alternative interface)

**Goal:** Interact with Harle from your phone via Telegram. This is the first non-CLI interface and proves the multi-client architecture.

**What is built:**

| Deliverable | Contents |
|---|---|
| Telegram bot adapter | Python script/service: Telegram Bot API → Harle `/chat` API |
| Docker Compose service | `telegram-bot` service added to `docker-compose.yml` |
| Conversation mapping | Telegram chat ID → Harle `conversation_id` persistence |
| Basic commands | `/start`, `/new` (new conversation), `/context` (switch context), text messages → `/chat` |

**Verification:**
- Send a message to the Telegram bot from your phone.
- Verify the response comes from Harle (via the real orchestrator, not echo).
- Start a conversation on CLI, continue it on Telegram (by sharing `conversation_id`).
- Verify two simultaneous sessions (CLI + Telegram) work without interference.

**Dependencies:** Phase 3 (API authentication).

**Estimated effort:** 2–3 days.

**Result:** Harle is accessible from your phone. You can ask questions, get vault-based answers, and trigger tool calls — all from Telegram.

---

### Phase dependency diagram

```
            Phase 1
       Basic Remote Deployment
      (Docker, VPS, Tailscale)
                │
    ┌───────────┼───────────┬───────────┐
    │           │           │           │
    ▼           ▼           ▼           │
Phase 2     Phase 3     Phase 5        │
Vault Sync  API Auth    Monitoring     │
            & Multi-                   │
            Client                     │
    │           │           │           │
    │           ├───────────┘           │
    │           │                       │
    │           ▼                       │
    │       Phase 6                     │
    │       Telegram Bot                │
    │                                   │
    └───────────────────┬───────────────┘
                        │
                        ▼
                    Phase 4
                    CD Pipeline
```

Phase 4 (CD) is placed last because manual deployment is acceptable while the system stabilizes. Once the deployment is reliable and patterns are established, automating it provides the most value.

### Effort estimates

| Phase | Estimated effort | Can parallelize with |
|---|---|---|
| **1. Basic remote deployment** | 2–3 days | — |
| **2. Vault sync** | 1–2 days | Phase 3, Phase 5 |
| **3. API auth + multi-client** | 1 day | Phase 2, Phase 5 |
| **4. CD pipeline** | 2–3 days | — |
| **5. Monitoring** | 1–2 days | Phase 2, Phase 3 |
| **6. Telegram bot** | 2–3 days | — |
| **Total (sequential)** | ~10–14 days | |
| **Total (with parallelism)** | ~7–10 days | Phases 2+3+5 in parallel |

Estimates assume a single developer working part-time. The critical path is: Phase 1 → Phase 3 → Phase 6. Phases 2, 4, and 5 can be done alongside other work.

---

## Technology Choices Summary

| Decision | Choice | Key reason |
|---|---|---|
| **Containerization** | Docker + Docker Compose | Single-command start, reproducible, industry standard; mentioned in [overview.md](./architecture/overview.md) |
| **Private networking** | Tailscale (WireGuard mesh); raw WireGuard or Headscale as fallback | Zero-config, free personal tier, no public ports; already chosen in [overview.md](./architecture/overview.md). Fallback SSH + documented migration path if Tailscale dies |
| **Reverse proxy** | Caddy | Automatic HTTPS, minimal config, works with Tailscale certs |
| **Vault sync** | Git (cron pull) for v1; Syncthing as alternative | Git is already used for vault versioning; no new dependencies |
| **CD strategy** | Pull-based (server polls registry) | No inbound webhook needed, works behind Tailscale, simple |
| **Container registry** | GitHub Container Registry (ghcr.io) | Free for public repos, integrated with GitHub Actions |
| **Monitoring** | Custom health-check script + Telegram alerts | Lightweight, no additional services, you already have Telegram |
| **External uptime** | Healthchecks.io (dead man's switch) | Free tier, external perspective, no public endpoint needed |
| **OS** | Ubuntu 24.04 LTS | Best Docker support, long-term security updates |
| **API authentication** | Bearer token (static) | Simplest viable auth for a single-user system |
| **Multi-client** | Shared API + per-client conversation IDs | Already supported by the existing architecture |
| **DB backup (off-site)** | Daily `pg_dump` to S3-compatible storage (Backblaze B2 / Hetzner Object Storage) | Protects against total server loss; vault is already safe in Git |

---

## What This Does Not Cover

| Topic | Why excluded | Where it goes |
|---|---|---|
| **Web UI** | Separate frontend project, distinct from infrastructure | Future TRD: `web_ui.md` |
| **Multi-user deployment** | Harle is currently single-user; multi-tenant adds authentication, isolation, and billing concerns | Future TRD if multi-user becomes a goal |
| **Self-hosted LLM** | Running models on the server changes hardware requirements fundamentally | Covered by model migration path in [overview.md](./architecture/overview.md) |
| **Kubernetes** | Overkill for a personal single-server deployment | Consider only if scaling beyond one server |
| **Database replication** | Single PostgreSQL instance is sufficient for personal use; off-site `pg_dump` covers durability | Consider only if RPO (recovery point objective) needs to be near-zero |
