---
title: "Harle Remote Setup Runbook"
tags: [deployment, remote, runbook, vps, docker, ufw, github-ssh, tailscale-optional, vault-sync, cd, ghcr, monitoring, telegram-alerts, db-backup, s3]
context: global
last_updated: 2026-04-04
summary: "Provision a VPS and run Harle with Docker Compose over the public network; optional Tailscale hardening; optional Git-based vault sync with systemd timer."
---

# Harle Remote Setup Runbook

This runbook provisions a fresh Ubuntu 24.04 VPS and runs Harle as a Docker Compose stack. **Baseline path:** SSH and the HTTP API use the server’s **public IP** (no Tailscale required). **Optional phase 11:** lock inbound traffic to **Tailscale only** for extra hardening.

> **API authentication (Phase 3):** Set **`HARLE_API_TOKEN`** in the server **`.env`** (see [§8b](#8b-api-bearer-token-recommended-for-remote)) so only clients that send **`Authorization: Bearer <token>`** can call non-health endpoints. Without a token, the API behaves as in local development (no bearer required). Exposing port **8000** on the public internet still warrants **UFW**, an **SSH tunnel** (step 5), and/or **Tailscale** (phase 11) according to your threat model.

## Prerequisites

- A VPS with Ubuntu 24.04 and SSH key login enabled.
- A private GitHub repository containing Harle code.
- Local Harle CLI on your laptop/device (for steps 9+).

## 1) Create and access the server

**VPS requirements** (Docker Compose: Harle app + PostgreSQL + search index):

| | Minimum | Comfortable |
|---|---------|-------------|
| **OS** | Ubuntu 24.04 LTS | Same |
| **vCPU** | 1 | 2 |
| **RAM** | 1 GB | 2 GB |
| **Disk** | 10 GB SSD | 20 GB |
| **Network** | Public IPv4 or reachable IPv6 for SSH and (by default) API port 8000 | Same |

Example SKUs and monitoring: [Remote deployment TRD](../trd/remote_deployment.md).

1. Create a VPS that meets the table above (Ubuntu 24.04 LTS).
2. Disable password authentication in the provider panel if available.
3. SSH in as root or a sudo-enabled user:

```bash
ssh root@<server-public-ip>
```

## 2) Run one-time server initialization (baseline)

The server does not have the Harle repository yet (clone is step 4). Copy **only** `scripts/server-init.sh` from your local clone, then run it on the server as root:

**On your laptop** (paths relative to the repo root):

```bash
scp scripts/server-init.sh root@<server-public-ip>:/root/server-init.sh
```

**On the server:**

```bash
sudo bash /root/server-init.sh
```

This script:

- Creates the **`harle`** deploy user (sudo-capable) and hardens SSH (`PermitRootLogin no`, `PasswordAuthentication no`).
- Configures **UFW**: allow **OpenSSH** and, by default, **TCP 8000** (Harle API) on the public interface. To **omit** the public API rule and rely on an SSH tunnel instead, run: `HARLE_UFW_OPEN_API=0 bash /root/server-init.sh`.
- Installs unattended security upgrades and **Docker CE** + Compose plugin.
- Generates **`harle`’s** GitHub deploy key and prints the public half.

**Before you disconnect this SSH session:** copy your admin SSH public key from root to **`harle`** so you can log in as `harle` next (root login is disabled after the script):

```bash
install -d -m 700 -o harle -g harle /home/harle/.ssh
cp /root/.ssh/authorized_keys /home/harle/.ssh/
chown harle:harle /home/harle/.ssh/authorized_keys
chmod 600 /home/harle/.ssh/authorized_keys
```

**Optional — password for `sudo` as `harle`:** The deploy user has **no password** by default, so `sudo` in a later SSH session as **`harle`** will fail unless you set one (or you configure passwordless sudo separately).

While still logged in as **root** in this step-2 session (before switching to `harle` for daily use), run:

```bash
passwd harle
```

Enter the new password twice when prompted. Root may set any user’s password without knowing the old one.

From any other account that can run commands as root (for example a rescue console or a second admin user), the same effect is:

```bash
sudo passwd harle
```

After a password is set, when you run `sudo` as **`harle`**, the shell will ask for **`harle`’s** login password (not root’s).

Later SSH (baseline):

```bash
ssh harle@<server-public-ip>
```

## 3) Add GitHub deploy key

Add the printed key at GitHub → repo **Settings** → **Deploy keys** (read-only, no write access).

Verify on the server:

```bash
sudo -u harle ssh -T git@github.com
```

## 4) Clone Harle on the server

Repository root: `/home/harle/harle` (contains `docker-compose.yml`, `.env.example`, etc.).

```bash
sudo -u harle -H bash -lc 'cd ~ && git clone git@github.com:<owner>/harle.git'
cd /home/harle/harle
```

**Git remotes must run as `harle`, not root** (deploy key lives under `/home/harle/.ssh`):

```bash
sudo -u harle -H bash -lc 'cd /home/harle/harle && git fetch origin'
```

If `.git` is not writable by `harle`, fix ownership: `chown -R harle:harle /home/harle/harle`.

For steps **5–10**, SSH as **`harle`** and run commands from **`~/harle`** (root login is disabled after step 2).

## 5) Configure environment

```bash
cp .env.example .env
```

Set at minimum:

- `OPENAI_API_KEY`
- `POSTGRES_PASSWORD` (strong value)
- `DATABASE_URL` with the same password (`db` host)
- `HARLE_DATASET_PATH=/data/vault`
- `HARLE_HOST=0.0.0.0`
- **`HARLE_API_TOKEN`** (recommended when the API is reachable beyond localhost): generate a random secret, e.g. `python -c "import secrets; print(secrets.token_urlsafe(32))"`, and set the same value on clients (CLI **`api_token`** in `~/.config/harle/cli.yaml`, optional **`HARLE_API_TOKEN`** for vault-sync — see **§8b**). When unset or empty, Harle does **not** enforce bearer auth.
- **`HARLE_PUBLISH_HOST=0.0.0.0`** if you opened port 8000 in UFW (default init) and want to reach the API from your laptop using **`http://<server-public-ip>:8000`**. Use **`127.0.0.1`** if you did **not** open 8000 and will use an SSH tunnel:

```bash
ssh -N -L 8000:127.0.0.1:8000 harle@<server-public-ip>
```

Then on the laptop, `server_url` / `curl` can use `http://127.0.0.1:8000`.

Do **not** run Compose yet: step 6 creates **`./vault`**, builds images, and starts **db** and **harle** together. If you already have the stack running and you change **`HARLE_PUBLISH_HOST`** (or other compose-time settings), recreate the app container and recheck the bind:

```bash
docker compose up -d --force-recreate harle
docker compose port harle 8000
```

## 6) Start Compose stack

The **`harle`** image runs the app as **UID 1000**. The host directory bind-mounted as the vault (**`HARLE_VAULT_PATH`**, default **`./vault`**) must be writable by that UID, or startup seeding fails with **`Permission denied: '/data/vault/...'`** and the container restarts in a loop.

```bash
mkdir -p ./vault
sudo chown -R 1000:1000 ./vault
docker compose build
docker compose up -d
docker compose ps
docker compose port harle 8000
```

If **`HARLE_VAULT_PATH`** is an absolute path (e.g. **`/home/harle/harle-vault`**), run **`chown -R 1000:1000`** on that path instead of **`./vault`**.

The **`port`** line confirms how **`8000`** is published on the host (**`127.0.0.1`** vs **`0.0.0.0`**) after the first successful **`up`**.

## 7) Initialize DB and index

```bash
docker compose exec harle harle-init
```

## 8) Configure local CLI (baseline — public IP or tunnel)

Replace the host with your server’s **public IP**, or `127.0.0.1` if you use a local SSH tunnel:

```bash
mkdir -p ~/.config/harle
cat > ~/.config/harle/cli.yaml <<'EOF'
server_url: "http://<server-public-ip>:8000"
api_token: "<same value as HARLE_API_TOKEN on the server>"
EOF
```

If you are **not** using API auth yet, omit **`api_token`** (or leave it empty).

## 8b) API bearer token (recommended for remote)

When **`HARLE_API_TOKEN`** is set in **`~/harle/.env`** on the server (non-empty after trim), Harle requires **`Authorization: Bearer <token>`** on every route except **`/health`**, **`/health/connections`**, **`/health/tools`**, and **`/health/all`**. Health checks stay unauthenticated for monitoring and scripts.

1. **Generate a token** (on your laptop or the server):

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

2. **Server:** add to **`~/harle/.env`**:

   ```bash
   HARLE_API_TOKEN='<paste-generated-token>'
   ```

   Recreate the app container so the process picks it up:

   ```bash
   cd ~/harle
   docker compose up -d --force-recreate harle
   ```

3. **CLI (laptop):** set the same value under **`api_token`** in **`~/.config/harle/cli.yaml`** (see step 8), or export **`HARLE_API_TOKEN`** for the shell session, or pass **`harle --token '<paste>' ...`** (highest precedence).

4. **Vault sync (server):** the systemd service’s **`EnvironmentFile`** (`~/harle/.env`) should already include **`HARLE_API_TOKEN`** so **`scripts/vault-sync.sh`** can call **`POST /reindex`** with **`Authorization`** (see §12e).

**Verify**

- `curl -fsS http://127.0.0.1:8000/health` → **200** (no header).
- `curl -sS -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:8000/reindex` → **401** without **`Authorization`**.
- `curl -fsS -X POST http://127.0.0.1:8000/reindex -H "Authorization: Bearer $HARLE_API_TOKEN"` → **200** (when DB and dataset are configured).
- **`harle exec "hello"`** from a machine with **`api_token`** set → normal reply.

Optional header **`X-Harle-Client`** (e.g. **`harle-cli`**, **`vault-sync`**) is logged for operations; it is not required for authentication.

## 9) Verify health and first request

On the server:

```bash
curl -fsS "http://127.0.0.1:8000/health"
```

From your laptop (same URL as in `cli.yaml`):

```bash
curl -fsS "http://<server-public-ip>:8000/health"
harle exec "hello"
```

Expected: `{"status":"ok"}` and a normal assistant reply.

## 10) Verify restart behavior

```bash
docker compose kill harle
docker compose ps
docker compose logs --tail=50 harle
```

Expect the `harle` service to come back (`restart: unless-stopped`) and `/health` to return 200 again.

## 11) Optional — extra hardening with Tailscale

Use this **after** baseline works. You will **drop inbound SSH and HTTP on the public interface** and allow traffic only on **`tailscale0`**. Install the **Tailscale app** on your laptop and join the **same tailnet** before pressing Enter in the script. You need **`sudo`**: either set **`harle`’s** password while root in step 2 (`passwd harle`), run the script from the provider’s **serial/web console as root**, or use another sudo-capable path your host provides.

**On your laptop** (use **`harle`**, not `root`—root SSH is disabled after step 2):

```bash
scp scripts/server-hardening-tailscale.sh harle@<server-public-ip>:/tmp/server-hardening-tailscale.sh
```

**On the server:**

```bash
sudo bash /tmp/server-hardening-tailscale.sh
```

The script installs Tailscale, runs `tailscale up --ssh`, waits for you to confirm Tailscale SSH works from another machine, then resets UFW to **allow inbound only on `tailscale0`**.

Then:

1. Use **`ssh harle@<tailscale-ip-or-magicdns>`** for administration.
2. Point **`HARLE_PUBLISH_HOST=0.0.0.0`** (or keep as-is) and ensure `docker compose port harle 8000` shows a bind that accepts traffic on the tailnet (see troubleshooting).
3. Update **`~/.config/harle/cli.yaml`** to `http://<tailscale-hostname-or-ip>:8000`.

If you are locked out, use the provider **web/serial console** to repair UFW or Tailscale.

## 12) Optional — vault Git sync (Phase 2)

Use this when you want **local vault edits** (commit + push) to appear on the server within minutes, and **server-written run logs** under `logs/` pushed back to the same Git remote so your laptop can `git pull`.

This is **separate** from the Harle **code** repo in step 4: the vault should be its own **private** Git repository.

### 12a) Create the vault remote and local clone

1. Create a **private** repository (e.g. `harle-vault`) on GitHub (or Gitea, etc.).
2. On your laptop, if the vault is not already a Git repo:

   ```bash
   cd ~/harle-vault   # or your vault directory
   git init
   git remote add origin git@github.com:<owner>/harle-vault.git
   git add .
   git commit -m "Initial vault"
   git push -u origin main
   ```

   Use branch **`main`** unless you set `VAULT_SYNC_BRANCH` (see below).

### 12b) Deploy key with **write** access (vault repo only)

The deploy key from step 3 is for the **Harle code** repo and is typically **read-only**. The vault repo needs a key that can **push** (server log sync).

1. On the server as **`harle`**, generate a second key used only for the vault:

   ```bash
   sudo -u harle -H bash -lc 'ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_vault -N ""'
   cat ~/.ssh/id_ed25519_vault.pub
   ```

2. In GitHub → **vault** repo → **Settings** → **Deploy keys** → **Add deploy key**: paste the public key, enable **Allow write access**.

3. Add an SSH host alias so Git uses this key for the vault remote (example for GitHub):

   ```bash
   sudo -u harle -H bash -lc 'cat >> ~/.ssh/config <<EOF

   Host github-vault
     HostName github.com
     User git
     IdentityFile ~/.ssh/id_ed25519_vault
     IdentitiesOnly yes
   EOF'
   ```

4. Clone the vault using that host (adjust owner/repo):

   ```bash
   sudo -u harle -H bash -lc 'git clone git@github-vault:<owner>/harle-vault.git ~/harle-vault'
   ```

### 12c) Point Compose at the vault checkout

In **`~/harle/.env`**, set an **absolute** host path (not `./vault`):

```bash
HARLE_VAULT_PATH=/home/harle/harle-vault
```

Keep `HARLE_DATASET_PATH=/data/vault` as in [`.env.example`](../../.env.example). Recreate the app container:

```bash
cd ~/harle
docker compose up -d --force-recreate harle
```

### 12d) Git identity for server commits

`scripts/vault-sync.sh` commits pushed run logs with message `vault-sync: server logs`. Configure identity **inside the vault repo**:

```bash
cd ~/harle-vault
git config user.email "harle-vault-sync@users.noreply.github.com"
git config user.name "Harle server"
```

Use values you are comfortable seeing on commits.

### 12e) Install user systemd timer

Paths below assume the Harle repo lives at **`~/harle`**. If yours differs, edit **`WorkingDirectory=`**, **`EnvironmentFile=`**, and **`ExecStart=`** in the unit file after copying. **`WorkingDirectory`** makes **`HARLE_VAULT_PATH=./vault`** in `.env` resolve to `<repo>/vault`.

```bash
mkdir -p ~/.config/systemd/user
cp ~/harle/scripts/systemd/harle-vault-sync.service ~/.config/systemd/user/
cp ~/harle/scripts/systemd/harle-vault-sync.timer ~/.config/systemd/user/
# If Harle is not at ~/harle, edit both files and replace %h/harle with your clone path.
nano ~/.config/systemd/user/harle-vault-sync.service
systemctl --user daemon-reload
loginctl enable-linger "$USER"
systemctl --user enable --now harle-vault-sync.timer
systemctl --user list-timers harle-vault-sync.timer
```

The service loads **`~/harle/.env`**, which must define **`HARLE_VAULT_PATH`**. Optional:

| Variable | Purpose |
|----------|---------|
| `HARLE_API_URL` | Base URL for the API (default `http://127.0.0.1:8000`). |
| `HARLE_API_TOKEN` | Bearer token for `POST /reindex` when API auth is enabled (Phase 3). |
| `VAULT_SYNC_BRANCH` | Remote branch to merge (default `main`). |
| `VAULT_SYNC_LOG_FILE` | Log path (default `~/vault-sync.log`). |

### 12f) Verify

1. On the laptop, add a unique snippet to a vault note, commit, and push to `main`.
2. Wait up to ~2 minutes (timer interval).
3. On the server: `tail -20 ~/vault-sync.log` — expect a pull line and reindex if HEAD moved.
4. From laptop or server: if **`HARLE_API_TOKEN`** is set, add **`-H "Authorization: Bearer $HARLE_API_TOKEN"`** to authenticated routes, e.g. `curl -fsS -H "Authorization: Bearer $HARLE_API_TOKEN" "http://<server>:8000/search?q=<unique-snippet>"` (use the same base URL you use for `/health`).

To confirm **log push-back**: run a chat on the server, wait for a run log under `logs/` in the vault, then after the next sync run `git pull` on the laptop inside the vault repo and confirm new commits.

## 13) Continuous deployment from GHCR (Phase 4)

Use this **after** baseline (steps 1–10) and vault sync (step 12) work. Pushes to `main` trigger a GitHub Actions workflow that builds a Docker image and pushes it to **GitHub Container Registry** (`ghcr.io`). A systemd timer on the server polls GHCR every 5 minutes, pulls the new image if the digest changed, restarts the `harle` service, and verifies health.

### 13a) GitHub secrets

In the GitHub repository **Settings** → **Secrets and variables** → **Actions**, add:

| Secret | Value | Purpose |
|--------|-------|---------|
| `DEPLOY_HOST` | Server's public IP (e.g. `203.0.113.42`) | Post-deploy health check from GitHub Actions (main branch only) |

`DEPLOY_HOST` is required for `main` deploys: the `verify-deploy` job fails if this secret is missing.

`GITHUB_TOKEN` (automatic) handles GHCR authentication in the workflow — no extra secret needed for the CI side.

### 13b) GHCR authentication on the server

The server needs to pull images from the **private** `ghcr.io` registry. Create a GitHub **Personal Access Token (classic)** with the **`read:packages`** scope:

1. Go to **GitHub** → **Settings** → **Developer settings** → **Personal access tokens** → **Tokens (classic)** → **Generate new token**.
2. Select scope **`read:packages`** only. Set a descriptive name (e.g. `harle-server-ghcr-pull`) and a long expiration.
3. Copy the token.

On the server as **`harle`**:

```bash
echo "<paste-token>" | docker login ghcr.io -u <github-username> --password-stdin
```

Docker stores credentials in `~/.docker/config.json`. Verify:

```bash
docker pull ghcr.io/sk0m0r0h/harle:latest
```

If the image hasn't been pushed yet (first-time setup), this will fail — that's expected; it will succeed after the first workflow run on `main`.

### 13c) Switch Compose to use GHCR image

The repo already includes `docker-compose.prod.yml` (override that replaces `build:` with `image:` from GHCR). From now on, use the production override for all Compose commands on the server:

```bash
cd ~/harle
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull harle
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

To simplify, add a shell alias to `~/.bashrc`:

```bash
alias dcp='docker compose -f docker-compose.yml -f docker-compose.prod.yml'
```

Then: `dcp pull harle && dcp up -d`.

### 13d) Install deploy-pull systemd timer

```bash
mkdir -p ~/.config/systemd/user
cp ~/harle/scripts/systemd/harle-deploy-pull.service ~/.config/systemd/user/
cp ~/harle/scripts/systemd/harle-deploy-pull.timer ~/.config/systemd/user/
# If Harle is not at ~/harle, edit both files and replace %h/harle with your clone path.
systemctl --user daemon-reload
loginctl enable-linger "$USER"
systemctl --user enable --now harle-deploy-pull.timer
systemctl --user list-timers harle-deploy-pull.timer
```

The timer runs `scripts/deploy-pull.sh` every 5 minutes. Logs go to `DEPLOY_LOG_FILE` (default `~/deploy-pull.log`).

Optional variables in `~/harle/.env`:

| Variable | Purpose |
|----------|---------|
| `HARLE_IMAGE_TAG` | Image tag to pull (default `latest`). Set to `sha-<commit>` for rollback. |
| `DEPLOY_LOG_FILE` | Log path (default `~/deploy-pull.log`). |
| `HARLE_API_URL` | Base URL for health check (default `http://127.0.0.1:8000`). |

### 13e) Rollback

Every image pushed by CI is tagged with its commit SHA (e.g. `sha-a1b2c3d`). To roll back to a known-good version:

1. Find the good commit SHA (from `git log`, GitHub commits page, or `~/deploy-pull.log`).
2. Set the tag in `.env`:

   ```bash
   cd ~/harle
   # Replace with the actual short SHA of the known-good commit.
   echo 'HARLE_IMAGE_TAG=sha-a1b2c3d' >> .env
   ```

   Or edit `.env` directly to change the existing `HARLE_IMAGE_TAG` line.

3. Pull and restart:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml pull harle
   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d harle
   ```

4. Verify: `curl -fsS http://127.0.0.1:8000/health`

5. After fixing `main`, remove or reset `HARLE_IMAGE_TAG` in `.env` (or set it back to `latest`) so the deploy timer picks up new images again.

### 13f) Verify

1. Push a code change to `main` on GitHub.
2. Check **GitHub Actions** → **Deploy** workflow: lint, test, build-and-push should all pass.
3. On the server, wait up to ~5 minutes, then check: `tail -20 ~/deploy-pull.log` — expect "New image detected" and "Deploy complete".
4. Verify: `curl -fsS http://127.0.0.1:8000/health` → `{"status":"ok"}`.
5. On GitHub, the `verify-deploy` job should show a green check (if `DEPLOY_HOST` secret is configured).

## 14) Monitoring and alerting

### 14a) Create a Telegram alert bot

1. Open Telegram, search for **@BotFather**, and send `/newbot`.
2. Follow the prompts: give the bot a name (e.g. "Harle Alerts") and a username (e.g. `harle_alerts_bot`).
3. BotFather returns a **bot token** — a string like `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`. Copy it.
4. To find your **chat ID**, start a conversation with the bot (send `/start`), then open:

   ```
   https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates
   ```

   Look for `"chat":{"id":<number>}` — that number is your chat ID.

### 14b) Configure monitoring environment

Add to `.env` on the server:

```bash
cd ~/harle
cat >> .env <<'EOF'

# --- Monitoring (Phase 5) ---
HARLE_TELEGRAM_ALERT_BOT_TOKEN=<your-bot-token>
HARLE_TELEGRAM_ALERT_CHAT_ID=<your-chat-id>
# HARLE_DISK_WARN_PCT=85
EOF
```

### 14c) Install health monitor timer

```bash
mkdir -p ~/.config/systemd/user
cp ~/harle/scripts/systemd/harle-health-monitor.service ~/.config/systemd/user/
cp ~/harle/scripts/systemd/harle-health-monitor.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now harle-health-monitor.timer
```

Verify the timer is active:

```bash
systemctl --user list-timers | grep health
```

**Deploy vs health monitor:** `deploy-pull.sh` creates a short-lived lock file (`${HARLE_STATE_DIR:-/tmp}/harle-deploy-in-progress` by default) before `docker compose up -d harle` and removes it when the script exits (success or failure). While that file exists, `health-monitor.sh` does **not** treat failed `/health` as a DOWN event and does not send Telegram DOWN/RECOVERED for that window — so routine image deploys do not spam alerts. If a deploy is killed abnormally (`kill -9`), the lock may linger; after `HARLE_DEPLOY_LOCK_MAX_AGE_SEC` (default 900s) the health monitor removes a stale lock and resumes normal alerting.

### 14d) Set up S3-compatible storage for backups

The backup script uploads compressed database dumps to any S3-compatible storage. Example with **Backblaze B2**:

1. Create a B2 bucket (e.g. `harle-backups-<your-name>`).
2. Create an application key with read/write access to that bucket.
3. Install the AWS CLI on the server:

   ```bash
   sudo apt install -y awscli
   ```

4. Configure credentials:

   ```bash
   aws configure
   # Access Key ID: your B2 keyID
   # Secret Access Key: your B2 applicationKey
   # Default region: us-west-004 (or your B2 region)
   # Default output format: json
   ```

5. Add to `.env`:

   ```bash
   cat >> ~/harle/.env <<'EOF'
   HARLE_BACKUP_S3_BUCKET=harle-backups-<your-name>
   HARLE_BACKUP_S3_ENDPOINT=https://s3.<region>.backblazeb2.com
   # HARLE_BACKUP_RETENTION_DAYS=7
   EOF
   ```

6. Test manually:

   ```bash
   ~/harle/scripts/db-backup.sh
   tail -20 ~/db-backup.log
   aws --endpoint-url https://s3.<region>.backblazeb2.com s3 ls s3://harle-backups-<your-name>/harle-db/
   ```

### 14e) Install database backup timer

```bash
cp ~/harle/scripts/systemd/harle-db-backup.service ~/.config/systemd/user/
cp ~/harle/scripts/systemd/harle-db-backup.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now harle-db-backup.timer
```

Verify:

```bash
systemctl --user list-timers | grep backup
```

### 14f) Verify monitoring

1. **Health alerts:** Stop the harle container and wait up to 2 minutes:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml stop harle
   # Wait ~1-2 minutes, check Telegram for the DOWN alert.
   docker compose -f docker-compose.yml -f docker-compose.prod.yml start harle
   # Wait ~1-2 minutes, check Telegram for the RECOVERED alert.
   ```

2. **Disk alerts:** Temporarily lower the threshold to test:

   ```bash
   HARLE_DISK_WARN_PCT=1 ~/harle/scripts/health-monitor.sh
   # Should fire a disk warning since any usage > 1%.
   ```

3. **Database backup:** Trigger manually and verify:

   ```bash
   ~/harle/scripts/db-backup.sh
   tail -20 ~/db-backup.log
   ls -la ~/harle-backups/
   ```

4. **Restore from backup** (test on a non-production database):

   ```bash
   # Download from S3:
   aws --endpoint-url "$HARLE_BACKUP_S3_ENDPOINT" s3 cp \
     s3://$HARLE_BACKUP_S3_BUCKET/harle-db/harle-2026-04-04.sql.gz ./restore.sql.gz
   # Restore:
   gunzip -c restore.sql.gz | docker compose exec -T db psql -U harle harle
   ```

## Troubleshooting

- **`git fetch` / `git pull` → `Permission denied (publickey)`:** Run Git as **`harle`**, not root (see step 4). Check `sudo -u harle ssh -T git@github.com` and `chown -R harle:harle /home/harle/harle` if needed.
- **Cannot clone private repo:** Deploy key on the correct repo; SSH config under `/home/harle/.ssh`.
- **`Connection refused` to `:8000` from laptop:** On server, `docker compose port harle 8000`. If **`127.0.0.1:8000`**, set `HARLE_PUBLISH_HOST=0.0.0.0` in `.env` and recreate `harle`, **or** use an SSH tunnel and `127.0.0.1` on the laptop. If the bind is `0.0.0.0:8000`, check UFW (`sudo ufw status`) includes `8000/tcp` unless you use Tailscale-only phase 11.
- **After phase 11, cannot SSH on public IP:** Expected; use Tailscale or console.
- **Harle cannot connect to DB:** `DATABASE_URL` host must be `db`; password matches `POSTGRES_PASSWORD`.
- **`Permission denied: '/data/vault/...'` / `harle` stuck Restarting:** The vault bind mount on the host is not writable by container UID **1000**. **`chown -R 1000:1000`** the host path from **`HARLE_VAULT_PATH`** in **`.env`** (default **`./vault`** under the repo), then **`docker compose up -d --force-recreate harle`**.
- **Health fails:** `docker compose logs -f harle db`.
- **Vault sync: fast-forward failed:** Local and server histories diverged. On the server, `cd "$HARLE_VAULT_PATH"` and resolve with `git status` / manual merge, or reset to remote only if you accept losing server-only commits (dangerous).
- **Vault sync: `git push` failed:** Confirm vault deploy key has **write** access and `git@github-vault:...` (or your remote URL) uses the correct key.
- **`Could not resolve hostname github-vault`:** Not a key problem — **`github-vault`** is an **SSH config alias**, not DNS. Add the **`Host github-vault`** block to **`/home/harle/.ssh/config`** (step **12b**), then retry clone. Without it, SSH never reaches GitHub.
- **Vault sync: reindex WARN in log:** Harle not listening on loopback, wrong `HARLE_API_URL`, or API returned non-200. Check `curl -fsS http://127.0.0.1:8000/health` on the server and `.env` `HARLE_PUBLISH_HOST`.
- **Vault sync: git commit failed:** Set `user.name` and `user.email` in the vault repo (step 12d).
- **Deploy pull: `docker compose pull` → authentication required:** Run `docker login ghcr.io` as `harle` (step 13b). Token may have expired — regenerate if needed.
- **Deploy pull: image unchanged but code was pushed:** Check that the Deploy workflow passed on GitHub Actions. If it failed at test or build, no image was pushed.
- **Deploy pull: health check fails after restart:** Check `docker compose logs -f harle` for startup errors. To rollback: set `HARLE_IMAGE_TAG=sha-<known-good>` in `.env` and re-run `deploy-pull.sh` (step 13e).
- **Deploy pull: `verify-deploy` job fails on GitHub:** Server may be down or unreachable. SSH in and check `docker compose ps` and `~/deploy-pull.log`. Verify `DEPLOY_HOST` secret matches the server's public IP.
- **Health monitor: no Telegram alerts:** Check `HARLE_TELEGRAM_ALERT_BOT_TOKEN` and `HARLE_TELEGRAM_ALERT_CHAT_ID` in `.env`. Run `~/harle/scripts/health-monitor.sh` manually and check `~/health-monitor.log` for `TELEGRAM_SKIP` (vars unset) or `Telegram send failed`. Verify the bot is not blocked — send it a message on Telegram first.
- **Health monitor: constant DOWN alerts:** The health check URL defaults to `http://127.0.0.1:8000/health`. If `HARLE_PUBLISH_HOST` is not `127.0.0.1`, set `HARLE_API_URL` in `.env` to match. Also check `docker compose ps` — the `harle` container may be restarting.
- **DB backup: pg_dump failed:** Run `docker compose exec db pg_isready -U harle` to confirm the database is reachable. Check `~/db-backup.log` for details.
- **DB backup: S3 upload failed:** Run `aws --endpoint-url "$HARLE_BACKUP_S3_ENDPOINT" s3 ls s3://$HARLE_BACKUP_S3_BUCKET/` to test credentials. Check that `aws` is installed and `~/.aws/credentials` (or env vars) are configured.
- **DB backup: local files accumulating:** If `HARLE_BACKUP_S3_BUCKET` is unset, backups stay local only. Set the bucket to enable off-site upload and automatic local cleanup.
