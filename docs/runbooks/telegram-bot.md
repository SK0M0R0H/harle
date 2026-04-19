---
title: "Harle Telegram Chat Bot Setup Runbook (Stage 1)"
tags: [telegram, bot, runbook, deployment, systemd, docker, stage-1]
context: global
last_updated: 2026-04-19
summary: "Provision the harle-telegram chat bot frontend (Stage 1): create a BotFather token, configure env vars, run locally and as a systemd service alongside harle-server."
---

# Harle Telegram Chat Bot Setup Runbook (Stage 1)

This runbook gets the Stage 1 Telegram **chat** bot running and talking to a Harle orchestrator. For the architecture, scope boundaries, and acceptance criteria, see [`docs/trd/architecture/telegram_bot.md`](../trd/architecture/telegram_bot.md).

> **This is the chat bot, not the alert bot.** The chat bot (`harle-telegram`) is the user-facing assistant frontend. The alert bot covered in [`remote-setup.md` §14a](./remote-setup.md#14a-create-a-telegram-alert-bot) is a separate operational tool that posts health/disk alerts via `scripts/health-monitor.sh`. **Use a different BotFather token for each.**

## Prerequisites

- A working Harle orchestrator (`harle-server`) that the bot can reach over HTTP — local (`http://127.0.0.1:8000`) or remote.
- Python 3.10+ with the Harle package installed (`pip install -e .` from the repo root).
- A Telegram account on any device.
- Your numeric Telegram **user ID** (used for the default `allowlist` access policy). Find it by messaging [@userinfobot](https://t.me/userinfobot).

## 1) Create a BotFather token

1. Open Telegram and start a chat with [@BotFather](https://t.me/BotFather).
2. Send `/newbot` and follow the prompts:
   - **Name:** human-readable, e.g. `Harle Assistant`.
   - **Username:** must end in `bot`, e.g. `my_harle_assistant_bot`.
3. BotFather returns a **bot token** in the form `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`. Copy it — this is `HARLE_TELEGRAM_BOT_TOKEN`.
4. Optional, recommended: send `/setprivacy` to BotFather and choose **Enable** so the bot only sees messages addressed to it. Stage 1 is DM-only, but this future-proofs Stage 3 group support.

If you already have an alert bot from `remote-setup.md` §14a, **do not reuse it**. Create a fresh one so chat traffic and health-alert traffic stay isolated.

## 2) Configure environment variables

Add the following to the `.env` file Harle reads at startup (`./.env` in the project root, or the file pointed to by `HARLE_DOTENV_PATH`):

```bash
# --- Telegram chat bot (Stage 1) ---
HARLE_TELEGRAM_BOT_TOKEN=<paste-the-token-from-step-1>

# Safe default: only listed Telegram user IDs may use the bot.
HARLE_TELEGRAM_ACCESS_POLICY=allowlist
HARLE_TELEGRAM_ALLOWED_USER_IDS=<your-telegram-user-id>

# Where the orchestrator is listening (already used by the CLI / vault-sync).
HARLE_API_URL=http://127.0.0.1:8000

# Set the same value as the server's HARLE_API_TOKEN if the orchestrator requires bearer auth.
# HARLE_API_TOKEN=<same-token-as-the-server>
```

Notes:

- `HARLE_TELEGRAM_ALLOWED_USER_IDS` is comma-separated (e.g. `12345,67890`). Whitespace is ignored.
- `HARLE_TELEGRAM_ACCESS_POLICY=open` allows **any** Telegram user to use the bot. Only set it for development or an intentionally public bot.
- `HARLE_API_TOKEN` is shared with `harle-cli` and `vault-sync`. If your orchestrator does not enforce bearer auth (token unset on the server), leave it unset on the bot too.
- The `context` field on `POST /chat` is **not** a bot config knob — the bot relies on the orchestrator's default and on role-driven routing inside the orchestrator. To change it per role/topic, modify orchestrator routing, not the bot.
- Optional CLI-aligned polling tunables (defaults are fine for most deployments):
  - `HARLE_CHAT_PING_INTERVAL_SECONDS` (default 15)
  - `HARLE_CHAT_GRACE_PERIOD_SECONDS` (default 5)
  - `HARLE_CHAT_MAX_MISSED_PINGS` (default 3)
  - `HARLE_CHAT_MAX_WAIT_SECONDS` (unset = unlimited)

## 3) Install and run locally

From the repo root:

```bash
pip install -e .
harle-telegram
```

Expected log line on startup:

```
INFO harle.telegram.main harle-telegram starting (api=http://127.0.0.1:8000, access_policy=allowlist)
```

Then in Telegram, open your bot (search by the username from BotFather) and send:

1. `/start` — should return the welcome message.
2. `/help` — should list available commands.
3. A normal text question (e.g. `hello, who are you?`) — the bot forwards it to `POST /chat` and replies with the orchestrator's answer.
4. A sticker, photo, or voice note — should reply that only text is supported (and **not** call the orchestrator).

Stop the bot with `Ctrl-C`.

## 4) Verify access policy

With `HARLE_TELEGRAM_ACCESS_POLICY=allowlist` and a non-empty `HARLE_TELEGRAM_ALLOWED_USER_IDS`:

- Listed users get normal replies.
- Unlisted users (ask a friend, or send from a second Telegram account) get the polite refusal: *"You are not authorized to use this bot…"*
- The `harle-telegram` log shows `Access denied for user_id=<id> (allowlist mode)` for rejected attempts.

## 5) Verify long-running and error behavior

The bot mirrors the CLI's `/processing` liveness contract.

- **Server-side timeout (504 from `/chat`)** — temporarily set `HARLE_RUN_TIMEOUT_SECONDS=1` on the **server**, restart it, and ask a question that exceeds the timeout. The bot replies with the *"took too long … timeout"* message. **Reset** the value afterwards.
- **Orchestrator unreachable** — stop `harle-server`, then send a message. After up to `HARLE_CHAT_PING_INTERVAL_SECONDS × HARLE_CHAT_MAX_MISSED_PINGS` seconds, the bot replies with the *"couldn't reach the Harle server"* message. Restart the orchestrator and try again.
- **Long replies** — ask for something whose answer exceeds 4096 characters; the bot splits the reply into multiple sequential Telegram messages.

## 6) Run as a systemd service (remote server)

Use this when the orchestrator runs as a long-lived service (typically on the same host).

1. Create a unit file at `/etc/systemd/system/harle-telegram.service`:

   ```ini
   [Unit]
   Description=Harle Telegram Chat Bot (Stage 1)
   After=network-online.target
   Wants=network-online.target
   # Uncomment if harle-server runs as a systemd service on the same host:
   # After=harle-server.service
   # Wants=harle-server.service

   [Service]
   Type=simple
   User=harle
   WorkingDirectory=/home/harle/harle
   EnvironmentFile=/home/harle/harle/.env
   ExecStart=/home/harle/.venv/bin/harle-telegram
   Restart=on-failure
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```

   Adjust `User`, `WorkingDirectory`, `EnvironmentFile`, and `ExecStart` to match the deployment (e.g. the venv path or a system Python install).

2. Enable and start:

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now harle-telegram.service
   ```

3. Check status and logs:

   ```bash
   systemctl status harle-telegram.service
   journalctl -u harle-telegram.service -f
   ```

`Restart=on-failure` keeps the bot up across crashes. Telegram long polling reconnects automatically; no public endpoint or TLS is needed.

## 7) Run inside Docker Compose (optional)

If you already run Harle via Docker Compose (see [`remote-setup.md`](./remote-setup.md)), you can add the bot as a sidecar service. Append to your `docker-compose.yml` (or an override file):

```yaml
  harle-telegram:
    image: ${HARLE_IMAGE:-ghcr.io/<owner>/harle:latest}
    restart: unless-stopped
    depends_on:
      - harle
    env_file:
      - .env
    environment:
      # Talk to the orchestrator over the compose network, not the host port.
      HARLE_API_URL: http://harle:8000
    command: ["harle-telegram"]
```

Then:

```bash
docker compose up -d harle-telegram
docker compose logs -f harle-telegram
```

The image must include the `harle-telegram` entrypoint — rebuild from the current branch if you are pinning an older tag that predates Stage 1.

## 8) Operations

- **Rotate the bot token:** message BotFather, send `/revoke`, pick the bot, paste the new token into `.env`, restart `harle-telegram`.
- **Add or remove allowed users:** edit `HARLE_TELEGRAM_ALLOWED_USER_IDS` in `.env`, restart the service. Changes are not hot-reloaded.
- **Switch to `open` policy temporarily (e.g. demo):** set `HARLE_TELEGRAM_ACCESS_POLICY=open`, restart, and **remember to switch back** to `allowlist` afterwards.

## Troubleshooting

- **Bot starts but never answers in Telegram:** make sure another `harle-telegram` process is not already running with the same token (Telegram delivers each update only once). Check `ps aux | grep harle-telegram` and `journalctl -u harle-telegram.service -n 100`.
- **`HARLE_TELEGRAM_BOT_TOKEN is required` and exit code 2:** the env var is empty. Confirm `.env` location (`HARLE_DOTENV_PATH`) and that the systemd unit's `EnvironmentFile=` points at the right file.
- **Replies say *"couldn't reach the Harle server"* immediately:** verify `HARLE_API_URL` is reachable from the bot host (`curl -fsS "$HARLE_API_URL/health"`). Inside Docker Compose, use the service hostname (`http://harle:8000`), not `127.0.0.1`.
- **Replies say *"Authentication … failed"*:** the orchestrator has a `HARLE_API_TOKEN` set but the bot does not (or they differ). Set the same value in the bot's `.env` and restart.
- **Every reply says *"You are not authorized…"*:** `HARLE_TELEGRAM_ALLOWED_USER_IDS` does not include the user's numeric ID. Ask the user to message [@userinfobot](https://t.me/userinfobot) and add the ID.
- **Replies say *"took too long … timeout"* on every question:** the orchestrator is hitting `HARLE_RUN_TIMEOUT_SECONDS`. Increase it on the server, or shorten the question / disable optional reflection.
- **Bot answers, but with stale conversation context:** Stage 1 sends `conversation_id=null` on every message — there **is** no continuity yet. Conversation memory is Stage 2.
- **Telegram returns *"Conflict: terminated by other getUpdates request"* in the log:** another process is polling with the same token. Stop the other instance, or revoke and replace the token via BotFather.
- **Photos / voice replies say *"can't process this content type yet"*:** expected in Stage 1 — the bot is text-only by design.

## What's next

Stage 1 is intentionally minimal. See [`docs/trd/architecture/telegram_bot.md`](../trd/architecture/telegram_bot.md) for the staged roadmap:

- Stage 2 — DM conversation continuity (`conversation_id` mapping, `/new`, typing indicator, Markdown).
- Stage 3 — forum supergroups for parallel project workspaces, rate limiting.
- Stage 4 — context switching, `/capture`, `/import`.
- Stage 5+ — streaming, inline keyboards, voice transcription.
