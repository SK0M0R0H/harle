---
title: "Harle Remote Setup Runbook"
tags: [deployment, remote, runbook, vps, docker, tailscale, github-ssh]
context: global
last_updated: 2026-03-24
summary: "Step-by-step guide to provision a VPS and run Harle remotely with Docker, Tailscale, and private GitHub repo access."
---

# Harle Remote Setup Runbook

This runbook provisions a fresh Ubuntu 24.04 VPS and gets Harle running as a Docker Compose stack reachable from Tailscale-connected devices.

## Prerequisites

- A VPS with Ubuntu 24.04 and SSH key login enabled.
- A private GitHub repository containing Harle code.
- A Tailscale account with access to your tailnet.
- Local CLI installed on your laptop/device.

## 1) Create and access the server

1. Create a VPS (Ubuntu 24.04 LTS).
2. Disable password authentication in the provider panel if available.
3. SSH in as root or a sudo-enabled user:

```bash
ssh root@<server-ip>
```

## 2) Run one-time server initialization

From the repository root on the server:

```bash
sudo ./scripts/server-init.sh
```

This script does the following:

- Hardens SSH (`PermitRootLogin no`, `PasswordAuthentication no`).
- Configures UFW to allow only `tailscale0` inbound traffic.
- Installs unattended security upgrades.
- Installs Docker CE and Docker Compose plugin.
- Installs Tailscale and runs `tailscale up --ssh`.
- Generates `~/.ssh/harle_deploy` for private GitHub repo access.

## 3) Add GitHub deploy key (private repo access)

`server-init.sh` prints the public key. Add it to your repo:

1. Open GitHub repository settings.
2. Go to **Deploy keys**.
3. Click **Add deploy key**.
4. Paste the key and keep **Allow write access** disabled.

Verify server-side SSH auth:

```bash
sudo -u harle ssh -T git@github.com
```

## 4) Clone Harle on the server

```bash
sudo -u harle -H bash -lc 'cd ~ && git clone git@github.com:<owner>/harle.git'
cd /home/harle/harle
```

## 5) Configure environment

Create `.env` from template and edit values:

```bash
cp .env.example .env
```

Set at minimum:

- `OPENAI_API_KEY`
- `POSTGRES_PASSWORD` (strong value)
- `DATABASE_URL` using the same password (`db` host)
- `HARLE_DATASET_PATH=/data/vault`
- `HARLE_HOST=0.0.0.0`

## 6) Start Compose stack

```bash
mkdir -p ./vault
docker compose build
docker compose up -d
docker compose ps
```

## 7) Initialize DB and index

Run `harle-init` inside the running `harle` container:

```bash
docker compose exec harle harle-init
```

## 8) Configure local CLI for remote server

On your local machine, create:

`~/.config/harle/cli.yaml`

```yaml
server_url: "http://<tailscale-hostname-or-ip>:8000"
```

You can still override ad hoc via:

```bash
harle --server "http://<tailscale-hostname-or-ip>:8000" exec "hello"
```

## 9) Verify health and first request

From a Tailscale-connected device:

```bash
curl -fsS "http://<tailscale-hostname-or-ip>:8000/health"
harle exec "hello"
```

Expected:

- `/health` returns `{"status":"ok"}`.
- CLI receives a normal assistant response.

## 10) Verify restart behavior

```bash
docker compose kill harle
docker compose ps
docker compose logs --tail=50 harle
```

Expected:

- `harle` container restarts automatically (`restart: unless-stopped`).
- `/health` returns 200 again after restart.

## Troubleshooting

- **Cannot clone private repo:** re-check deploy key in GitHub and `~/.ssh/config`.
- **Server unreachable from laptop:** verify both devices are in the same tailnet and `tailscale status` is healthy.
- **Harle cannot connect to DB:** ensure `DATABASE_URL` host is `db` and password matches `POSTGRES_PASSWORD`.
- **Health endpoint fails:** inspect logs via `docker compose logs -f harle db`.
