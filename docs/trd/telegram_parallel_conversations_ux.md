---
title: "Telegram Bot UX Research — Parallel Conversations"
tags: [telegram, ux, conversations, research, sessions, forum-topics]
context: global
last_updated: 2026-04-04
summary: "Research into UX patterns for handling parallel conversations in a Telegram bot, with OpenClaw case study and Harle recommendations."
---

# Telegram Bot UX — Parallel Conversations Research

> Harle's CLI supports one active conversation per session. A primary-interface Telegram bot must eventually handle multiple concurrent conversations — for example, continuing a work thread while starting a personal question. This document surveys the design space, studies how OpenClaw solves the problem, and recommends an approach for Harle.

For the Telegram bot architecture and staged roadmap, see [telegram_bot.md](./architecture/telegram_bot.md).
For the CLI's session model, see [cli.md](./architecture/cli.md).

---

## The Problem

Telegram direct messages (DMs) are a **single linear stream** — there are no tabs, windows, or thread panes like in Slack or Discord. Every message the user sends and every reply the bot posts land in the same chronological list.

At the same time, a user talking to Harle may want to:

- Continue a long-running work conversation **and** fire off a quick personal question without losing context in the first thread.
- Have separate conversations with different `context` values (`work` vs `personal`) running in parallel.
- Return to an earlier conversation days later without resetting the current one.

The orchestrator already supports arbitrary `conversation_id` strings, and the database persists full conversation history per ID. The backend is ready for parallelism. **The challenge is entirely on the Telegram UX side**: how does the user signal which conversation a message belongs to, and how does the bot keep replies visually distinguishable?

---

## Telegram's Native Mechanisms

### DM chat

A DM between a user and a bot is one flat stream. The Bot API delivers every message with the same `chat_id`. There is a `message_thread_id` field, but its behavior in DMs is unreliable — it exists primarily for reply chains in the "General" topic of forum supergroups and has edge-case bugs when used in plain DMs (Telegram may attach a random thread ID that fails on subsequent API calls). In practice, **DMs offer no native conversation-separation primitive**.

### Groups with Forum Topics

Telegram supergroups can enable **Forum mode** (via BotFather or group settings). In a forum supergroup, each **topic** gets a stable `message_thread_id`. The bot receives this ID on every incoming message and can reply to the correct topic by passing it back in `sendMessage`. Topics have names, can be pinned, closed, and reopened — all through Telegram's native UI. **This is Telegram's primary mechanism for conversation separation.**

### Reply-based threading

Telegram shows reply chains visually (a small header linking to the original message), but this is purely cosmetic in DMs. At the API level, all messages still arrive in one `chat_id` stream with no isolation. Reply chains do not produce distinct `message_thread_id` values in DMs.

### Multiple bots

Running several bot instances (one per conversation or context) is technically possible but creates bad UX: separate chat windows, separate token management, and no unified experience.

---

## Case Study: OpenClaw

[OpenClaw](https://github.com/openclaw/openclaw) is an open-source personal AI assistant that supports Telegram (among 22+ channels). Its Telegram implementation is production-grade, using the **grammY** library (TypeScript). The patterns below are drawn from its public source code and documentation.

### Session key model

OpenClaw assigns every conversation a **session key** built from structured components:

```
agent:<agent_name>:telegram:<dm|group>:<chat_id>[:topic:<thread_id>]
```

Each unique key maps to an isolated session with its own memory, context, and history. Sessions are stored on disk under `~/.openclaw/agents/<agent>/sessions/sessions.json`.

### DM behavior (single conversation)

In a DM, there is **one session per chat**. The user talks to a single "thread" at a time. The `/new` command resets the session (clears context, starts a fresh `conversation_id`). There is **no way to run parallel DM conversations** — OpenClaw does not attempt to fight Telegram's single-stream DM model.

### Forum supergroup as the parallel conversation surface

Each forum topic becomes a **separate session**. The user creates topics using Telegram's native UI (long-press → "New Topic" on mobile, or the topic button on desktop). The bot treats each topic as an independent conversation. This means:

- **Creating a new topic = starting a new conversation.** No slash commands needed.
- **Switching topics = switching conversations.** Native Telegram navigation.
- **Closing/reopening a topic** maps naturally to pausing/resuming a conversation.
- **Topic names** serve as conversation labels, visible in Telegram's sidebar.

OpenClaw supports **per-topic agent routing**: each topic can be configured to route to a different agent via `agentId` in the topic config. This gives each topic its own workspace and model identity.

### Session concurrency

The `sessionConcurrency` config (default `1`) controls how many **different sessions** the agent processes in parallel. Messages within the same session are always serialized to preserve coherence. Setting `sessionConcurrency: 3` means up to three topics can have their orchestrator calls in flight simultaneously.

### Session expiry

Sessions expire after an idle timeout (`session.idleMinutes`, default 60 minutes). After expiry, the next message starts a fresh session. This prevents stale context from accumulating in long-idle topics.

### Key takeaway

**OpenClaw treats DMs as single-conversation and uses forum topics as the parallel-conversation primitive.** It does not try to build virtual threads, conversation pickers, or other abstractions on top of the single-stream DM — it uses the mechanism Telegram already provides.

---

## Design Options for Harle

### Option A — Single DM, `/new` to reset

The simplest model. One `conversation_id` per `chat_id`. The `/new` command clears it and starts fresh.

| Dimension | Assessment |
|---|---|
| Implementation effort | Trivial — one dict mapping `chat_id → conversation_id` |
| Parallelism | None — user must finish or abandon a conversation before starting another |
| UX friction | Low for simple use, high when the user wants to context-switch |
| Matches CLI model | Yes — the CLI works exactly this way today |

### Option B — Bot-managed virtual threads in DM

The bot tracks multiple `conversation_id`s per user. Commands like `/thread list`, `/thread switch <name>`, `/thread new <name>` let the user navigate between them. The bot prefixes replies with a thread label (e.g. `[work-planning]`) so the user can visually distinguish conversations in the single DM stream.

| Dimension | Assessment |
|---|---|
| Implementation effort | Moderate — thread registry, active-thread state, label rendering |
| Parallelism | Logical parallelism, but visually interleaved in one stream |
| UX friction | High — commands to switch, labels to parse, easy to send a message to the wrong thread |
| Precedent | No major bot uses this pattern — a warning sign for discoverability |

### Option C — Forum supergroup (OpenClaw pattern)

The operator creates a private supergroup with forum mode enabled and adds the bot. Each forum topic maps to one Harle conversation. The bot maps `(group_id, topic_thread_id)` → `conversation_id`.

| Dimension | Assessment |
|---|---|
| Implementation effort | Moderate — group message handling, thread-aware routing and replies |
| Parallelism | Full — native Telegram UI for creating, naming, switching, closing topics |
| UX friction | Low once set up. Initial setup is slightly more complex (create group, enable forum mode, add bot) |
| Precedent | Proven pattern — OpenClaw uses exactly this in production |

The one downside: a single-user private forum supergroup feels slightly unusual. In practice, this is similar to creating a private Slack workspace for personal use — uncommon but functional.

### Option D — Hybrid: DM as primary assistant, forum group for project workspaces

DM chat is the main interaction surface — persistent conversation with the assistant, like messaging a colleague. The forum group provides per-topic sessions for complex, parallel project work.

| Dimension | Assessment |
|---|---|
| Implementation effort | Moderate — two code paths, but each is simpler than a full-featured single path |
| Parallelism | Full in the group; DM is single-conversation (reset with `/new`) |
| UX friction | Low — DM is the natural default. Forum group is opt-in for power-user workflows |
| Mental model | Clear: "DM = talk to your assistant, Forum topics = project workspaces" |

### Option E — Inline keyboard conversation picker in DM

After each reply, the bot offers inline buttons: "Continue this thread" / "New thread" / "Switch to: [list]". The user taps a button to set the active thread before typing.

| Dimension | Assessment |
|---|---|
| Implementation effort | Moderate — inline keyboard state management, callback handlers |
| Parallelism | Logical parallelism, single visual stream |
| UX friction | Clutters every message with buttons. Still fundamentally one visual stream |
| Precedent | Some customer-service bots use this, but not for open-ended AI chat |

---

## Decision: Option D — DM as primary assistant, forum groups for dedicated work

**Chosen approach:** Option D (hybrid), with a specific framing.

The core insight is that talking to Harle in a DM should feel like messaging a real human assistant — you open the chat, type your question, get a reply, and the assistant remembers what you discussed. This is the **primary interaction surface**. Forum groups serve a different purpose: dedicated workspaces for complex, multi-step projects where the user wants multiple parallel threads with their own context.

### DM — the primary "assistant" surface

- The DM conversation is persistent by default (not one-shot). The bot maintains a single `conversation_id` per user, and the assistant remembers prior messages — just like messaging a colleague.
- `/new` resets the conversation when the user wants a clean slate.
- This is where most day-to-day interactions happen: quick questions, follow-ups, casual requests.
- The mental model: **"DM = talking to your assistant."**

### Forum group — dedicated project workspaces

- For complex, multi-step work (a project plan, a research thread, a long-running task), the user creates a private forum supergroup and adds the bot.
- Each forum topic becomes an independent Harle conversation with its own `conversation_id` and context.
- Topics provide native Telegram UI for naming, switching, closing, and organizing parallel threads.
- The mental model: **"Forum topics = project workspaces."**

### Phased delivery

- **Stage 1**: DM only, stateless (`conversation_id=null` on every message). Validates the end-to-end pipeline.
- **Stage 2**: DM with conversation continuity (persistent `conversation_id` per user, `/new` to reset). The bot becomes a proper assistant you can have an ongoing conversation with.
- **Stage 3+**: Add forum group support. Each topic maps to an independent conversation. The DM path continues to work alongside it.

### Deferred: Options B, C (pure), and E

- **Option B** (virtual threads in DM): clunky command-driven UX with no precedent in production bots.
- **Option C** (forum group only, no DM): forces all interaction through a group, which is unnatural for simple assistant conversations.
- **Option E** (inline keyboard pickers): clutters every message and does not solve the underlying single-stream problem.

---

## Open Questions

These should be resolved before implementing Stage 3+ (not blocking for Stage 1–2):

- **Topic auto-creation**: Should the bot auto-create forum topics (e.g. one per `context` value, or one on first message), or let the user create them manually? Auto-creation reduces friction but limits naming flexibility.
- **Namespace isolation**: Should DM and forum-group sessions share the same `conversation_id` namespace, or be fully isolated? Sharing allows "continue this DM conversation in a topic" workflows; isolation is simpler.
- **Topic naming**: Should the bot suggest or auto-set topic names (e.g. from the first message summary), or leave naming entirely to the user?
- **Dual-surface support**: Should the bot support both DM and group simultaneously for the same user, or encourage choosing one? OpenClaw supports both, with DM and group sessions being independent.
- **Session expiry**: Should idle conversations in topics expire (like OpenClaw's 60-minute default), or persist indefinitely (relying on the orchestrator's database)?
