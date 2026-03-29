---
title: "Harle Remote Setup Runbook"
tags: [deployment, remote, runbook, vps, docker, ufw, github-ssh, tailscale-optional, vault-sync]
context: global
last_updated: 2026-03-29
summary: "Provision a VPS and run Harle with Docker Compose over the public network; optional Tailscale hardening; optional Git-based vault sync with systemd timer."
---

# Harle Remote Setup Runbook

This runbook provisions a fresh Ubuntu 24.04 VPS and runs Harle as a Docker Compose stack. **Baseline path:** SSH and the HTTP API use the server’s **public IP** (no Tailscale required). **Optional phase 11:** lock inbound traffic to **Tailscale only** for extra hardening.

> Harle’s API is not yet authenticated for remote access. Exposing port **8000** on the public internet is convenient for a first deploy but increases risk; use phase 11 or an **SSH tunnel** (see step 5) if that matters for you.

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

Optional: set a login password for **`harle`** (`passwd harle`) if you want **`sudo`** to work in later SSH sessions (the deploy user has no password by default).

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
- **`HARLE_PUBLISH_HOST=0.0.0.0`** if you opened port 8000 in UFW (default init) and want to reach the API from your laptop using **`http://<server-public-ip>:8000`**. Use **`127.0.0.1`** if you did **not** open 8000 and will use an SSH tunnel:

```bash
ssh -N -L 8000:127.0.0.1:8000 harle@<server-public-ip>
```

Then on the laptop, `server_url` / `curl` can use `http://127.0.0.1:8000`.

After edits: `docker compose up -d --force-recreate harle` and check `docker compose port harle 8000`.

## 6) Start Compose stack

```bash
mkdir -p ./vault
docker compose build
docker compose up -d
docker compose ps
```

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
EOF
```

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
4. From laptop or server: `curl -fsS "http://<server>:8000/search?q=<unique-snippet>"` (use the same base URL you use for `/health`).

To confirm **log push-back**: run a chat on the server, wait for a run log under `logs/` in the vault, then after the next sync run `git pull` on the laptop inside the vault repo and confirm new commits.

## Troubleshooting

- **`git fetch` / `git pull` → `Permission denied (publickey)`:** Run Git as **`harle`**, not root (see step 4). Check `sudo -u harle ssh -T git@github.com` and `chown -R harle:harle /home/harle/harle` if needed.
- **Cannot clone private repo:** Deploy key on the correct repo; SSH config under `/home/harle/.ssh`.
- **`Connection refused` to `:8000` from laptop:** On server, `docker compose port harle 8000`. If **`127.0.0.1:8000`**, set `HARLE_PUBLISH_HOST=0.0.0.0` in `.env` and recreate `harle`, **or** use an SSH tunnel and `127.0.0.1` on the laptop. If the bind is `0.0.0.0:8000`, check UFW (`sudo ufw status`) includes `8000/tcp` unless you use Tailscale-only phase 11.
- **After phase 11, cannot SSH on public IP:** Expected; use Tailscale or console.
- **Harle cannot connect to DB:** `DATABASE_URL` host must be `db`; password matches `POSTGRES_PASSWORD`.
- **Health fails:** `docker compose logs -f harle db`.
- **Vault sync: fast-forward failed:** Local and server histories diverged. On the server, `cd "$HARLE_VAULT_PATH"` and resolve with `git status` / manual merge, or reset to remote only if you accept losing server-only commits (dangerous).
- **Vault sync: `git push` failed:** Confirm vault deploy key has **write** access and `git@github-vault:...` (or your remote URL) uses the correct key.
- **Vault sync: reindex WARN in log:** Harle not listening on loopback, wrong `HARLE_API_URL`, or API returned non-200. Check `curl -fsS http://127.0.0.1:8000/health` on the server and `.env` `HARLE_PUBLISH_HOST`.
- **Vault sync: git commit failed:** Set `user.name` and `user.email` in the vault repo (step 12d).
