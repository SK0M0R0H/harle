---
title: "Harle Telegram Bot — Architecture & Staged Delivery"
tags: [telegram, bot, frontend, architecture, orchestrator, api-client, security]
context: global
last_updated: 2026-04-05
summary: "Describes the Telegram bot as Harle's primary frontend: how it maps to the orchestrator HTTP API, staged delivery plan, security posture, and configuration."
---

# Harle Telegram Bot — Architecture & Staged Delivery

> The Telegram bot is Harle's primary user interface — a chat-based frontend where you message Harle like you would a human assistant, and it replies with the orchestrator's answer. It replaces the CLI as the default way to interact with Harle for everyday use. The CLI remains available for scripting, automation, and power-user terminal workflows.

This document describes the bot's architecture, how it talks to the existing orchestrator HTTP API, a multi-stage delivery roadmap with explicit scope boundaries per stage, security considerations, and configuration.

For the overall system architecture, see [overview.md](./overview.md).
For the Orchestrator (which the bot talks to), see [orchestrator.md](./orchestrator.md).
For the CLI (the previous primary interface), see [cli.md](./cli.md).
For UX research on parallel conversations, see [telegram_parallel_conversations_ux.md](../telegram_parallel_conversations_ux.md).

---

## Problem Statement & Positioning vs CLI

Harle's interactive surface today is the Go CLI (`harle-cli`): users install a binary, run it in a terminal, and interact via a session-first REPL. This works well for developers at a workstation, but it requires:

- A terminal and local binary installation.
- Familiarity with command-line tools.
- A desktop or laptop — no practical mobile use.

A Telegram bot removes all three barriers. The user opens Telegram (already installed on their phone, tablet, or desktop), finds the bot, and types a message. The experience should feel like messaging a real human assistant — you send a question, you get an answer, the assistant remembers what you discussed.

**The Telegram bot replaces the CLI as the primary interface.** The CLI remains available for power-user, scripting, and automation use cases, but the bot becomes the default way the operator interacts with Harle day-to-day.

| Dimension | Telegram Bot (primary) | CLI (advanced/fallback) |
|---|---|---|
| Access | Any device with Telegram | Terminal on a workstation |
| Setup | Message the bot — zero install | Build/install Go binary |
| Mobile use | Native | Not practical |
| Conversation UX | Chat — like messaging a person | REPL session |
| Parallel conversations | Forum topics (Stage 3+) | One session at a time |
| Scripting / automation | Not a goal | `harle exec` one-shot mode |
| Rich TUI (tables, progress) | Not a goal (plain text + Markdown) | Bubbletea rendering |
| Streaming | Future (Stage 5+) | SSE polling today |

---

## Where the Bot Sits

```
 ANY DEVICE                     REMOTE SERVER
┌──────────────────────┐       ┌──────────────────────────────────────┐
│                      │       │                                      │
│  ┌────────────────┐  │       │  ┌──────────────┐                    │
│  │                │  │       │  │              │                    │
│  │   Telegram     │  │       │  │  Telegram    │   HTTP/JSON        │
│  │   App          │──┼──────>│  │  Bot Process │──────────────┐     │
│  │   (user)       │<─┼──────-│  │  (Python)    │              │     │
│  │                │  │       │  │              │              ▼     │
│  └────────────────┘  │       │  └──────────────┘    ┌──────────────┐│
│                      │       │   X-Harle-Client:    │              ││
│  Phone, tablet,      │       │   telegram           │ Orchestrator ││
│  desktop — anything  │       │                      │ (FastAPI)    ││
│  with Telegram       │       │                      │              ││
└──────────────────────┘       │                      └──────┬───────┘│
                               │                             │        │
                               │                      PostgreSQL,     │
                               │                      LLM, tools,     │
                               │                      search          │
                               └──────────────────────────────────────┘
```

The bot is a **thin HTTP client** — it plays the same role as `harle-cli` but runs as a long-lived process on the server. It has zero knowledge of AI, databases, or search. It only knows how to:

1. Receive messages from Telegram via long polling (or webhook in future).
2. Forward each message as JSON to the orchestrator's `POST /chat` endpoint.
3. Receive the orchestrator's response.
4. Send it back to the user in Telegram.
5. Identify itself via the `X-Harle-Client: telegram` header for observability.

All heavy work — routing, context assembly, LLM calls, tool execution — happens in the orchestrator, unchanged.

---

## Multi-Stage Roadmap

Each stage has explicit in-scope and out-of-scope lists and testable acceptance criteria. Later stages are documented here for planning but are not implemented until their own issue is created.

### Stage 1 — Minimal end-to-end path

The smallest possible slice: Telegram message in → orchestrator → assistant reply back in Telegram.

**In scope:**

- Bot responds to `/start` with a welcome message.
- Any other text message is forwarded to `POST /chat` with `conversation_id=null` (every message is a new conversation — no memory between messages). The bot omits the `context` field so the orchestrator's default (currently `personal`) and role-based routing decide.
- The `result` field from `RunResponse` is sent back as plain Telegram text. If the result exceeds Telegram's per-message limit, the bot splits it into multiple sequential messages.
- Errors (orchestrator 5xx, timeout, network) produce a user-friendly error reply instead of a crash or silence.
- Unsupported content types (photo, voice, audio, video, document, sticker, location, contact, poll, etc.) receive an explicit reply that the bot currently supports text messages and commands only.
- Bot identifies itself via `X-Harle-Client: telegram`.
- Bot authenticates to the orchestrator with `Bearer <HARLE_API_TOKEN>` when configured.
- Access is controlled by `HARLE_TELEGRAM_ACCESS_POLICY`. Stage 1 supports `allowlist` and `open`; default is `allowlist`. When in `allowlist`, unlisted users are rejected with a polite refusal.
- Bot generates `X-Request-ID` for `/chat` requests and follows the same long-running liveness contract as the CLI where feasible: no short per-request timeout for `POST /chat`, distinct handling for server timeout vs unreachable server, and optional `/processing/{request_id}` polling.
- `/help` command lists available commands and basic usage.

**Out of scope (deferred to later stages):**

- Conversation continuity (`conversation_id` mapping).
- Markdown or HTML rendering of replies.
- Typing indicator while orchestrator is working.
- Streaming or edit-in-place partial replies.
- Inline keyboards or callback buttons.
- Rate limiting.
- Group chat or forum topic support.
- Capture interview flow.
- Context switching (`work` / `personal`).

**Acceptance criteria:**

1. `harle-telegram` starts, connects to Telegram via long polling, and logs startup.
2. Sending `/start` to the bot returns a welcome message.
3. Sending a text message returns the orchestrator's assistant reply.
4. Sending a message when the orchestrator is unreachable returns a user-friendly error.
5. With `HARLE_TELEGRAM_ACCESS_POLICY=allowlist`, messages from unlisted users are rejected.
6. Sending an unsupported content type returns an explicit "text only for now" reply.
7. If the orchestrator returns a reply longer than one Telegram message, the bot splits it into multiple messages in order.
8. If the orchestrator returns 504, the bot reports server-side timeout distinctly from network/unreachable errors.

---

### Stage 2 — Conversation continuity and basic UX

The bot becomes a proper assistant you can have an ongoing conversation with.

**In scope:**

- Persistent `conversation_id` mapping: one conversation per DM `chat_id`. The bot stores the `conversation_id` returned by the orchestrator and sends it on subsequent messages.
- `/new` command resets the conversation (sets `conversation_id=null`).
- Typing indicator (`sendChatAction: typing`) while the orchestrator is processing.
- Markdown rendering of assistant replies (Telegram `parse_mode: "MarkdownV2"` via `telegramify-markdown`, with fallback to plain text on parse errors).
- `/id` command shows the current `conversation_id`.
- Single in-flight request per DM `chat_id`; Stage 2 chooses reject-busy behavior with a "please wait" response until the active turn completes.

**Out of scope:** group/topic support, context switching, rate limiting, capture/import.

---

### Stage 3 — Forum groups and parallel conversations

Adds support for forum supergroups as dedicated project workspaces alongside the DM. See [parallel conversations UX research](../telegram_parallel_conversations_ux.md) for the design rationale (Option D).

**In scope:**

- Forum supergroup support: bot joins a private forum supergroup, each topic maps to an independent `conversation_id`.
- Topic-aware routing: bot reads `message_thread_id` from incoming group messages and replies to the correct topic.
- DM continues to work as the primary single-conversation surface.
- Policy-driven access control for organizational use (allowed users, allowed groups, and allowed forum topics via config-driven policy definitions).
- Rate limiting per `user_id` (simple token bucket or fixed-window).
- Structured error messages (categorized: auth, timeout, server error).

**Out of scope:** capture/import, context switching per topic, streaming.

---

### Stage 4 — Feature parity subset

Brings the bot closer to CLI feature parity for common workflows.

**In scope:**

- Context switching: `/context work` and `/context personal` to change the `context` field sent to `/chat`.
- Per-topic context in forum groups (each topic can have its own context).
- Capture interview flow via `/capture` command in DM (mirrors CLI `harle capture interview`).
- Vault import trigger via `/import` command.
- Tool-call result summaries in replies (list of tools used, if any).

**Out of scope:** streaming, inline keyboards, multi-tenant.

---

### Stage 5+ — Future

**In scope (eventual):**

- Streaming replies (chunked `editMessageText` while the orchestrator works — similar to OpenClaw's `partial` streaming mode).
- Inline keyboards for common actions (new conversation, context switch, approve/reject).
- Voice message transcription (Telegram audio → text → orchestrator).
- Health-check integration (reuse or supplement existing Telegram alert bot).
- Observability hooks (structured logging, metrics).
- Full feature parity with the CLI for all common workflows, completing the transition to primary interface.

---

## Stage 1 — Detailed Specification

This section is the contract for the Stage 1 implementation.

### Capability list

| # | Capability | Testable? |
|---|---|---|
| 1 | `/start` returns a welcome message explaining what the bot does | Yes — send `/start`, verify reply |
| 2 | `/help` returns a list of available commands | Yes — send `/help`, verify reply |
| 3 | Any text message → `POST /chat` with `message=<text>`, `conversation_id=null` (no `context` override; orchestrator default applies) | Yes — send message, verify orchestrator receives request |
| 4 | `RunResponse.result` is sent back as Telegram text; oversized replies are split into multiple messages | Yes — verify reply content and chunk ordering |
| 5 | Orchestrator errors (5xx, timeout, unreachable) → user-friendly error reply with distinct timeout vs unreachable messaging | Yes — stop orchestrator or force 504, verify error reply |
| 6 | Unsupported content types receive an explicit "text only for now" reply and do not call the orchestrator | Yes — send photo/sticker, verify reply and no `/chat` request |
| 7 | `X-Harle-Client: telegram` header on every orchestrator request | Yes — inspect orchestrator logs |
| 8 | `X-Request-ID` header on every `/chat` request | Yes — inspect orchestrator logs or capture outgoing request |
| 9 | `Authorization: Bearer <token>` header when `HARLE_API_TOKEN` is set | Yes — set token, verify auth header |
| 10 | Access policy enforcement: reject unlisted users when `HARLE_TELEGRAM_ACCESS_POLICY=allowlist` | Yes — set policy + allowlist, send from unlisted user, verify rejection |

### What Stage 1 does NOT do

- No conversation memory (every message is independent).
- No Markdown formatting (plain text only).
- No typing indicator.
- No group chat support.
- No streaming.
- No rate limiting beyond the access policy gate.

---

## Orchestrator API Mapping

The bot is a thin HTTP client that maps Telegram events to orchestrator HTTP calls.

| Bot trigger | HTTP method | Path | Key fields | Stage |
|---|---|---|---|---|
| User text message | `POST` | `/chat` | `message`, `conversation_id=null` (Stage 1) or stored ID (Stage 2+); `context` left to orchestrator default until Stage 4 `/context` command | 1 |
| Unsupported non-text message | — | — | Local reply only: "I can't process this content type yet. Please send text." | 1 |
| `/start` | — | — | Local reply only, no orchestrator call | 1 |
| `/help` | — | — | Local reply only | 1 |
| `/new` | — | — | Local state: reset `conversation_id` to `null` | 2 |
| `/context work\|personal` | — | — | Local state: set `context` for subsequent `/chat` calls | 4 |
| `/capture` | `POST` | `/capture/interview/start`, `/capture/interview/respond` | Interview flow | 4 |
| `/import` | `POST` | `/import` | Import request | 4 |

### Request shape

The bot sends the same JSON body the CLI sends:

```json
{
  "message": "<user's Telegram message text>",
  "context": "personal",
  "conversation_id": null
}
```

With headers:

```
Content-Type: application/json
X-Harle-Client: telegram
X-Request-ID: <generated request id>
Authorization: Bearer <HARLE_API_TOKEN>   (if configured)
```

### Long-running request handling

The Telegram bot should follow the same `/chat` liveness contract as the CLI instead of inventing a separate timeout model:

- `POST /chat` uses a long-lived HTTP client with no short per-request deadline.
- The bot generates an `X-Request-ID` for each `/chat` turn.
- While `/chat` is in flight, the bot may poll `GET /processing/{request_id}` with a short timeout to distinguish "server is still working" from "server is unreachable".
- `504` from `/chat` is treated as a server-side run timeout and surfaced distinctly to the user.
- Repeated processing ping failures are treated as unreachable server/network failure and surfaced distinctly to the user.
- This liveness algorithm should mirror the CLI behavior as closely as practical. Shared constants, error classification rules, and test vectors should be centralized wherever cross-client reuse is feasible, even though the current CLI is Go and the bot is Python.

### Response handling

The bot reads `RunResponse` and extracts:

- `result` → reply text sent to user. In Stage 1, send as plain text and split across multiple Telegram messages if needed. In Stage 2+, convert Markdown to Telegram `MarkdownV2` and fall back to plain text on parse failure.
- `conversation_id` → stored for Stage 2+ continuity.
- `status` → if `"failed"`, the bot sends `result` as an error message (the orchestrator includes a user-facing error description in `result` on failure).

---

## Conversation Identity Strategy

The conversation identity model follows the decision documented in the [parallel conversations UX research](../telegram_parallel_conversations_ux.md) — Option D (DM as primary assistant surface, forum groups for project workspaces).

### Stage 1 — Stateless

Every message sends `conversation_id=null`. Each message is a new conversation. No state to manage.

### Stage 2 — DM with continuity

The bot maintains a single `conversation_id` per DM user:

- First message: `conversation_id=null`. The orchestrator creates a new conversation and returns the ID in `RunResponse.conversation_id`.
- Subsequent messages: the bot sends the stored `conversation_id`. The orchestrator includes prior messages in context.
- `/new`: resets the stored ID to `null`. Next message starts fresh.

This is the same pattern as the CLI's `session/manager.go`: the bot holds only a mapping `chat_id → conversation_id`; the orchestrator + database own all history.

Storage: SQLite-backed mapping (`HARLE_TELEGRAM_STATE_PATH`, default `telegram_state.sqlite`) so conversation continuity survives bot restarts by default.

### Stage 3+ — Forum topics

Each forum topic gets its own `conversation_id`, keyed by `(group_id, message_thread_id)`. Topics are fully independent of the DM conversation. The DM and forum group operate in parallel — the user can message the bot in DM and use forum topics at the same time.

### Concurrency model

Once continuity exists, the bot must avoid overlapping turns for the same conversation key:

- Stage 2 DM key: `chat_id`
- Stage 3 forum key: `(group_id, message_thread_id)`
- Only one `/chat` request may be active per key at a time.
- If a second message arrives while a turn is active for the same key, the bot either queues it or rejects it with a clear "please wait for the current reply to finish" message. This behavior should be configured once and applied consistently.
- Different keys may run in parallel. For example, a DM and a forum topic can each have one in-flight request at the same time.

---

## Access Policy Strategy

The bot must not rely on ad hoc allowlist behavior forever. Access should be defined as policy so the bot can later serve an organization safely.

### Stage 1 — Minimal policy modes

Stage 1 supports:

- `HARLE_TELEGRAM_ACCESS_POLICY=allowlist` (default): only users in `HARLE_TELEGRAM_ALLOWED_USER_IDS` may use the bot.
- `HARLE_TELEGRAM_ACCESS_POLICY=open`: any Telegram user may use the bot.

The default must be safe for deployment. `open` is an explicit opt-in, intended for development or intentionally public bots.

### Stage 3+ — Organizational policy

Later stages may extend the policy model to include:

- allowed Telegram user IDs
- allowed group IDs
- allowed forum topic scopes
- role-based policy definitions for organization use

The policy mechanism should remain declarative and config-driven rather than hard-coded in handlers.

---

## Security — Threats and Mitigations

| Threat | Mitigation (Stage 1) | Future stages |
|---|---|---|
| Bot token leak | Token loaded from env var (`HARLE_TELEGRAM_BOT_TOKEN`) only, never in committed config files. `.env` is in `.gitignore`. | Rotate via BotFather. |
| Unauthorized users | Access controlled by `HARLE_TELEGRAM_ACCESS_POLICY`; default `allowlist` mode admits only `HARLE_TELEGRAM_ALLOWED_USER_IDS`. `open` is explicit opt-in. | Richer organizational policy definitions (users, groups, topics, roles). |
| Orchestrator API token leak | Reuse `HARLE_API_TOKEN` env var. Bot reads it at startup. Same token the CLI uses. | Same. |
| Abuse / spam | Not fully enforced in Stage 1. Access policy is the primary gate. | Rate limiter per `user_id` plus group/topic policy (Stage 3). |
| Message content exfiltration | Telegram API uses HTTPS. Orchestrator on localhost or private network (Tailscale). | TLS to orchestrator if remote. |
| Prompt injection via Telegram | Same risk as CLI — the orchestrator is responsible for sandboxing. No change to the threat model. | No change. |
| Bot process compromise | Runs as unprivileged systemd service. Has access only to orchestrator API, not to the database or filesystem directly. | Same. |

---

## Configuration

Configuration follows the existing [`config.py`](../../../src/harle/config.py) pattern: env vars with optional `config.yaml` override. Field names match env var names.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `HARLE_TELEGRAM_BOT_TOKEN` | yes | — | BotFather token for the chat bot |
| `HARLE_API_URL` | no | `http://127.0.0.1:8000` | Orchestrator base URL |
| `HARLE_API_TOKEN` | no | — | Bearer token for orchestrator auth (same as CLI) |
| `HARLE_TELEGRAM_ACCESS_POLICY` | no | `allowlist` | Access mode: `allowlist` or `open` in Stage 1 |
| `HARLE_TELEGRAM_ALLOWED_USER_IDS` | no | empty | Comma-separated Telegram user IDs used when policy is `allowlist` |
| `HARLE_TELEGRAM_STATE_PATH` | no | `telegram_state.sqlite` | SQLite file that stores DM `chat_id → conversation_id` mappings |

The bot deliberately exposes **no** config knob for the orchestrator's `context` field. Stage 1 omits `context` from `POST /chat` so the orchestrator applies its own default; per-message context selection is the role/orchestrator's responsibility, not the bot's. (Stage 4's `/context` command is a per-conversation override, not a startup config.)

**Important:** the existing `HARLE_TELEGRAM_ALERT_BOT_TOKEN` and `HARLE_TELEGRAM_ALERT_CHAT_ID` (used by `scripts/health-monitor.sh` for operational alerts) are separate from the chat bot token. The chat bot should use its own dedicated BotFather token to keep alert and chat concerns isolated.

---

## Deployment

### Stage 1: long polling

The bot runs in **long-polling mode** — it connects outbound to Telegram's servers and waits for updates. This requires no public IP, no webhook endpoint, and no TLS certificate setup.

- **Entrypoint:** new `[project.scripts]` entry in `pyproject.toml`:
  `harle-telegram = "harle.telegram.main:run"`
- **Start:** `harle-telegram` (after `pip install -e .`)
- **Systemd:** optional `harle-telegram.service` alongside `harle-server.service` for the remote server.
- **Docker:** add as a new service in `docker-compose.yml` depending on `harle-server`.

### Future: webhook mode

When the deployment has a stable public endpoint (e.g. behind a reverse proxy with TLS), webhook mode is more efficient. This is deferred to Stage 5+.

---

## Project Structure

```
src/harle/telegram/
    __init__.py
    main.py          # entrypoint: bot setup, polling loop, signal handling
    handlers.py      # message and command handlers (/start, /help, text)
    client.py        # thin HTTP wrapper: POST /chat, auth headers
    processing.py    # request-id generation, /processing polling, timeout classification
    transport.py     # Telegram reply splitting, escaping, content-type rejections
    config.py        # Telegram-specific settings (or extend harle.config)
```

Each file stays under 500 lines per project convention. `client.py` mirrors the patterns from the Go CLI's `client.go` — a struct/class that holds the base URL, API token, and a method per endpoint. `processing.py` should intentionally mirror the CLI's liveness behavior so timeout handling and `/processing` semantics do not diverge across clients.

---

## Technology Choices

| Choice | Rationale |
|---|---|
| `aiogram 3.x` | Async-native Telegram bot framework. Well-maintained, strong typing support, good documentation. Aligns with the existing Python ecosystem. |
| Long-polling (not webhook) for Stage 1 | Simpler deployment — no public endpoint, no TLS certificate, no reverse proxy. The bot process connects outbound. |
| Separate process (not embedded in FastAPI) | The bot has its own event loop and lifecycle. Decoupling from the orchestrator means either can restart independently. The orchestrator does not need to know about Telegram. |
| `httpx` for orchestrator calls | Async HTTP client already used elsewhere in the project. Supports timeouts, connection pooling, and auth headers. |
| CLI-aligned `/processing` liveness | Reuse the same server contract, request-id semantics, and error classification as the CLI so clients behave consistently during long runs. |

**Why not `python-telegram-bot`?**
Both `aiogram` and `python-telegram-bot` are mature. `aiogram 3.x` was chosen for its async-first design (no synchronous fallback confusion), cleaner handler registration via routers, and stronger type annotations. Either would work.

---

## How to Run (Stage 1)

### Prerequisites

- Orchestrator running (`harle-server`) with `DATABASE_URL` configured.
- A Telegram bot token from [@BotFather](https://t.me/BotFather) (send `/newbot`, follow prompts).

### Steps

1. Add the bot token to your `.env`:

```bash
HARLE_TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
```

2. Choose an access policy. Safe default for a private deployment:

```bash
HARLE_TELEGRAM_ACCESS_POLICY=allowlist
HARLE_TELEGRAM_ALLOWED_USER_IDS=123456789
```

To find your Telegram user ID, message [@userinfobot](https://t.me/userinfobot) or check the bot's startup logs after sending it a message.

Use `HARLE_TELEGRAM_ACCESS_POLICY=open` only when you intentionally want an open bot.

3. Install and run:

```bash
pip install -e .
harle-telegram
```

4. Open Telegram, find your bot, send `/start`, then type a message. The bot forwards it to the orchestrator and replies with the assistant's answer.

### Systemd (remote server)

A `harle-telegram.service` unit file can be placed alongside the existing `harle-server.service`:

```ini
[Unit]
Description=Harle Telegram Bot
After=harle-server.service
Wants=harle-server.service

[Service]
Type=simple
User=harle
EnvironmentFile=/home/harle/.env
ExecStart=/home/harle/.venv/bin/harle-telegram
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

---

## What Comes Next

After Stage 1 is implemented and stable:

- **Stage 2** — Conversation continuity in DM (`conversation_id` mapping, `/new`, typing indicator, Markdown rendering).
- **Stage 3** — Forum group support for parallel project workspaces, rate limiting, structured errors.
- **Stage 4** — Context switching, capture interviews, vault import from Telegram.
- **Stage 5+** — Streaming replies, inline keyboards, voice messages, full feature parity with CLI.

Each stage will be its own issue with implementation scoped to the boundaries defined above.
