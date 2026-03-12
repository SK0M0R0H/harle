---
title: "Harle Connections Layer — Current State"
tags: [connections, current-state, architecture, api-clients, credentials, implementation-status]
context: global
last_updated: 2026-03-10
summary: "Tracks what the Connections Layer implements vs the TRD, and what each missing part would unlock."
---

# Harle Connections Layer — Current State

> This document compares the target design in the Connections Layer TRD with the codebase. It describes what is implemented, what is partial, and what is missing, and what each missing part would unlock.

Reference TRD: [Harle Connections Layer — Shared External Service Connections](../../trd/architecture/connections.md).

---

## Overall Status

The Connections Layer is **not implemented**. There is no `src/harle/connections/` package. Tool modules (e.g. Web Search) and import sources each use their own API clients and credentials; there is no shared Connection Registry, no `BaseConnection` contract, and no `connections` section in config. The TRD’s incremental plan (Phases 1–5) has not been started. Implementing it would unlock a single place for credentials and clients per service, shared rate limiting, and consistent health checks across tools and imports.

---

## Implementation Snapshot

| TRD area | Current status | Notes |
|----------|----------------|-------|
| BaseConnection ABC | Not implemented | No `src/harle/connections/base.py`; no contract for name, service_display_name, initialize, shutdown, health_check, get_client, get_rate_limiter. |
| ConnectionStatus | Not implemented | No dataclass for healthy, service_name, message, latency_ms. |
| ConnectionRegistry | Not implemented | No registry with register, get, has, list, health_check_all, shutdown_all. |
| RateLimiter / RateLimitConfig | Not implemented | No `rate_limiter.py`; no token-bucket shared per connection. |
| Exceptions | Not implemented | No ConnectionConfigError, ConnectionNotFound in a connections package. |
| config.yaml `connections` section | Not implemented | No single place for credentials; tool_modules and import_sources carry their own (e.g. api_key in web_search). |
| tool_modules / import_sources `connection: <name>` | Not implemented | Modules do not reference a connection by name; they embed or read credentials directly. |
| Orchestrator startup: Connection Registry first | Not implemented | No Connection Registry; Tool and Import registries are built without a connections dependency. |
| BaseToolModule.initialize(config, connections) | Not implemented | `initialize(config)` only; no optional ConnectionRegistry parameter. |
| BaseImportSource.initialize(config, connections) | Not implemented | Import base has a placeholder comment for ConnectionRegistry; no initialize(connections) contract. |
| Concrete connections (Notion, Trello, Miro, Tavily) | Not implemented | No connection classes; Web Search uses its own client; no shared Notion/Trello/Miro clients. |
| CLI: harle connections status/list/test | Not implemented | No connections command group. |
| Service-specific helpers (optional) | Not implemented | No shared helpers (e.g. query_database, get_page) on connection classes. |
| TRD impact on tools.md / import_module.md | Not implemented | tools.md and import_module.md describe connection consumption; code does not implement it. |

---

## What Is Implemented

Nothing. There is no Connections Layer code. The only reference is a comment in `src/harle/vault_imports/base.py` that `ConnectionRegistry` can be imported when the connections layer exists.

---

## What Is Only Partially Implemented

Nothing. The design is fully specified in the TRD but has no implementation.

---

## What Is Not Implemented Yet

### 1. Core infrastructure (Phase 1)

- **Missing:** `src/harle/connections/` with `base.py` (BaseConnection, ConnectionStatus), `registry.py` (ConnectionRegistry), `rate_limiter.py` (RateLimiter, RateLimitConfig), `exceptions.py` (ConnectionConfigError, ConnectionNotFound).
- **Unlocks:** A single contract and registry for all external service connections; ability to add the first connection (e.g. Tavily) and migrate one module to use it.

### 2. Configuration: single `connections` section

- **Missing:** A `connections` key in config with one block per service (notion, trello, miro, tavily, …) holding credentials (e.g. api_token, api_key) and optional rate_limit; `tool_modules.<module>.connection: <name>` and `import_sources.<source>.connection: <name>` instead of embedding credentials in each module.
- **Unlocks:** One place to set and rotate API keys; no duplicate credential blocks for the same service across tools and imports.

### 3. Orchestrator lifecycle: Connection Registry before modules

- **Missing:** At startup, create ConnectionRegistry; for each enabled connection in config, instantiate connection, call `register(connection, config)`, run health_check; then pass ConnectionRegistry to Tool Registry and Import Registry when building/initializing modules.
- **Unlocks:** All modules get a shared registry; unhealthy connections can be logged at startup while still allowing dependent modules to initialize and fail gracefully when used.

### 4. Tool modules consuming connections

- **Missing:** `BaseToolModule.initialize(self, config, connections: ConnectionRegistry | None = None)`; tool modules that need an API (e.g. web_search, trello) calling `connections.get("tavily")` or `connections.get("trello")` and using `connection.get_client()`; removal of per-module client/credential code.
- **Unlocks:** No duplicate Trello/Notion/Tavily client code across tools; shared rate limiter so bulk imports and tool calls do not exhaust quota independently.

### 5. Import sources consuming connections

- **Missing:** `BaseImportSource.initialize(config, connections)` (or equivalent) and API-mode sources looking up their connection by name; file-mode sources continuing to work without a connection.
- **Unlocks:** Same as above for import side: one client per service, shared rate limiting, no duplicate api_client.py in each import source.

### 6. Concrete connection implementations

- **Missing:** Connection classes for Tavily, Notion, Trello, Miro (and any others) implementing BaseConnection: initialize (credentials + httpx client), shutdown, health_check, get_client; optional get_rate_limiter and service-specific helpers.
- **Unlocks:** Each external service configured once and reused by every tool and import that needs it; consistent auth, timeouts, and retries.

### 7. CLI integration (Phase 5)

- **Missing:** `harle connections status`, `harle connections list`, `harle connections test <name>` with health and latency output.
- **Unlocks:** Single command to see status of all external services; easier debugging of credential and reachability issues.

### 8. Rate limiting per connection

- **Missing:** Token-bucket RateLimiter owned by each connection, shared by all consumers; optional rate_limit config per connection; get_rate_limiter() for bulk operations that need pacing.
- **Unlocks:** Prevents bulk import and concurrent tool calls from exceeding API quotas; predictable behaviour under load.

### 9. Service-specific helpers (optional)

- **Missing:** Optional methods on connection classes (e.g. NotionConnection.query_database, get_page) for pagination and common operations shared by tool and import consumers.
- **Unlocks:** Less duplicated pagination/API logic in each module; consistent handling of rate limits inside the connection.

### 10. Error handling as specified in TRD

- **Missing:** ConnectionConfigError (missing/invalid credentials at initialize); ConnectionNotFound when a module requests an unregistered connection; unhealthy status from health_check; clear user-facing messages in CLI and module errors.
- **Unlocks:** Clear diagnostics at startup and when a tool or import runs; users know where to fix credentials (connections section) and which connection is missing.

---

## Key Deviations

None. There is no implementation to deviate from the TRD.

---

## Assessment

The TRD is complete and the implementation plan (Phases 1–5) is clear. Implementing Phase 1 (core infrastructure) and Phase 2 (Tavily connection) plus Phase 3 (migrate Web Search module) would validate the pattern with minimal scope. The rest of the system (tools, imports, orchestrator) is structured so that adding a Connection Registry and an optional `connections` parameter to module initialization is backward-compatible. Until the Connections Layer exists, tool and import modules will continue to manage their own clients and credentials, with the drawbacks described in the TRD (duplicate code, duplicate config, no shared rate limiting).
