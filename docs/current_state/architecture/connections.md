---
title: "Harle Connections Layer — Current State"
tags: [connections, current-state, architecture, api-clients, credentials, implementation-status]
context: global
last_updated: 2026-03-14
summary: "Tracks what the Connections Layer implements vs the TRD, and what each missing part would unlock."
---

# Harle Connections Layer — Current State

> This document compares the target design in the Connections Layer TRD with the codebase. It describes what is implemented, what is partial, and what is missing, and what each missing part would unlock.

Reference TRD: [Harle Connections Layer — Shared External Service Connections](../../trd/architecture/connections.md).

---

## Overall Status

The Connections Layer is **substantially implemented**. The `src/harle/connections/` package provides `BaseConnection`, `ConnectionStatus`, `ConnectionRegistry`, `RateLimiter`/`RateLimitConfig`, and custom exceptions (`ConnectionConfigError`, `ConnectionNotFound`). Three concrete connections exist: **TavilyConnection**, **TrelloConnection**, and **NotionConnection**. Connections are built from environment variables in `build_connections()` (in `src/harle/tools/factory.py`) and the shared `ConnectionRegistry` is passed to both tool modules and import sources. Config-driven connections via `config.yaml` and CLI commands are not yet implemented.

---

## Implementation Snapshot

| TRD area | Current status | Notes |
|----------|----------------|-------|
| BaseConnection ABC | Implemented | `base.py`: name, service_display_name, initialize, shutdown, health_check, get_client. |
| ConnectionStatus | Implemented | Dataclass with healthy, service_name, message, latency_ms. |
| ConnectionRegistry | Implemented | `registry.py`: register, get, has, list, health_check_all, shutdown_all. |
| RateLimiter / RateLimitConfig | Implemented | `rate_limiter.py`: token-bucket rate limiter. Not yet wired per-connection by default. |
| Exceptions | Implemented | `exceptions.py`: ConnectionConfigError, ConnectionNotFound. |
| config.yaml `connections` section | Not implemented | Credentials come from env vars, not config.yaml. |
| tool_modules `connection: <name>` | Implemented | Trello and Notion modules use `connections.get("trello")` / `connections.get("notion")`. Web Search uses `connections.get("tavily")`. |
| import_sources `connection: <name>` | Implemented | NotionImportSource uses `connections.get("notion")` via initialize(). |
| Orchestrator startup: Connection Registry first | Implemented | `build_connections()` runs before tool and import registries; shared registry passed to both. |
| BaseToolModule.initialize(config, connections) | Implemented | All API-based modules accept optional ConnectionRegistry. |
| BaseImportSource.initialize(config, connections) | Implemented | Notion source receives connections in initialize(). |
| TavilyConnection | Implemented | `tavily.py`: api_key auth, httpx client, health_check via POST. |
| TrelloConnection | Implemented | `trello.py`: api_key + api_token, httpx client, health_check via GET boards. |
| NotionConnection | Implemented | `notion.py`: api_token Bearer auth, Notion-Version header, health_check via GET /users/me. |
| Miro connection | Not implemented | No MiroConnection class. |
| CLI: harle connections status/list/test | Not implemented | No connections command group. |
| Service-specific helpers (optional) | Not implemented | No shared helpers on connection classes. |

---

## What Is Implemented

### 1. Core infrastructure

`src/harle/connections/` package with:
- `base.py`: `BaseConnection` ABC (name, service_display_name, initialize, shutdown, health_check, get_client), `ConnectionStatus` dataclass.
- `registry.py`: `ConnectionRegistry` (register, get, has, list, health_check_all, shutdown_all).
- `rate_limiter.py`: `RateLimiter`, `RateLimitConfig` (token-bucket).
- `exceptions.py`: `ConnectionConfigError`, `ConnectionNotFound`.

### 2. Concrete connections

- **TavilyConnection**: API key auth, base_url `https://api.tavily.com`, health_check via POST search.
- **TrelloConnection**: API key + token as query params, base_url `https://api.trello.com/1`, health_check via GET boards.
- **NotionConnection**: Bearer token auth with `Notion-Version: 2022-06-28`, base_url `https://api.notion.com/v1`, health_check via GET `/users/me`.

### 3. Connection Registry lifecycle

`build_connections()` in `factory.py` reads env vars (`TAVILY_API_KEY`, `TRELLO_API_KEY`/`TRELLO_API_TOKEN`, `NOTION_API_TOKEN`), creates and initializes connections, registers them in a `ConnectionRegistry`, and returns it. The registry is shared with both `build_tool_registry()` and `build_import_registry()`.

### 4. Module consumption

- **WebSearchModule**: `connections.get("tavily")` → `connection.get_client()`.
- **TrelloModule**: `connections.get("trello")` → `connection.get_client()`.
- **NotionModule**: `connections.get("notion")` → `connection.get_client()`.
- **NotionImportSource**: `connections.get("notion")` → `connection.get_client()`.

---

## What Is Only Partially Implemented

### Rate limiting not wired per-connection

`RateLimiter` and `RateLimitConfig` exist but connections do not automatically attach a rate limiter. The `get_rate_limiter()` method from the TRD is not implemented on `BaseConnection`. Rate limiting can be used manually by consumers.

---

## What Is Not Implemented Yet

### 1. Config-driven connections

- **Missing:** A `connections` section in `config.yaml` with per-service credential blocks and optional rate_limit config.
- **Unlocks:** Credential management without code changes; rotation without redeployment.

### 2. CLI integration

- **Missing:** `harle connections status`, `harle connections list`, `harle connections test <name>`.
- **Unlocks:** Quick visibility into connection health from the terminal.

### 3. Miro connection

- **Missing:** No `MiroConnection` class.
- **Unlocks:** Miro integration for tools and import.

### 4. Service-specific helpers

- **Missing:** Optional methods like `query_database`, `get_page` on connection classes for shared pagination logic.
- **Unlocks:** Less duplicated pagination/API logic across tool and import consumers.

---

## Key Deviations

- **Env-var based**: Connections are built from environment variables, not from a `connections` config section. This is simpler but means no config-driven rotation or per-connection rate_limit config.
- **No get_rate_limiter()**: BaseConnection does not expose `get_rate_limiter()` as in the TRD. Rate limiting infrastructure exists but is not automatically attached.

---

## Assessment

The Connections Layer is functional and used by all API-based modules (Tavily, Trello, Notion). The core contract, registry, and lifecycle are in place. The main gaps are config-driven connection management, CLI commands, and automatic rate limiter attachment. These are nice-to-haves for the current deployment scale.
