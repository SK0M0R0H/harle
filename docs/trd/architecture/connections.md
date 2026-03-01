---
title: "Harle Connections Layer — Shared External Service Connections"
tags: [connections, architecture, api-clients, credentials, extensibility, reuse, import, tools]
context: global
last_updated: 2026-03-01
summary: "Describes the Connections Layer: a shared abstraction for external service credentials and API clients, consumed by both the Tool Module Layer and the Import Module Layer."
---

# Harle Connections Layer — Shared External Service Connections

> The Connections Layer is the single place where Harle knows how to talk to an external service. Every API credential, every HTTP client, every rate-limiter for a given service (Notion, Miro, Trello, Tavily, etc.) lives here once and is consumed by any module that needs it — whether that module is a tool, an import source, or something else entirely.

This document describes the Connections Layer's architecture: why it exists, what a connection provides, how connections are configured and discovered, and how the Tool Module Layer and the Import Module Layer consume them.

For the overall system architecture, see [overview.md](./overview.md).
For the Tool Module Layer (which consumes connections), see [tools.md](./tools.md).
For the Import Module Layer (which consumes connections), see [import_module.md](./import_module.md).

---

## The Problem

Both the Tool Module Layer and the Import Module Layer interact with the same external services. A Notion tool module queries databases at request time; a Notion import source extracts pages during a bulk import. Both need:

1. **The same credentials** — a Notion API token, a Trello API key + secret, a Miro OAuth token.
2. **The same HTTP client** — authentication headers, base URL, error mapping, retry logic, rate-limit handling.
3. **The same health check** — "can I reach this service with these credentials?"

Without a shared layer, these concerns are duplicated:

```
CURRENT (without Connections Layer):

src/harle/tools/trello/
├── client.py          ← Trello API wrapper (httpx, auth, retries)
└── ...

src/harle/imports/trello/
├── api_client.py      ← Another Trello API wrapper (same auth, same retries)
└── ...

config.yaml:
  tool_modules:
    trello:
      api_key: ${TRELLO_API_KEY}         ← credential declared here
      api_token: ${TRELLO_API_TOKEN}

  import_sources:
    trello:
      api_key: ${TRELLO_API_KEY}         ← same credential declared again
      api_token: ${TRELLO_API_TOKEN}
```

This creates three problems:

| Problem | Impact |
|---|---|
| **Duplicate client code** | Two wrappers for the same API, each with its own bugs, retry logic, and error handling. Fixes to one do not propagate to the other. |
| **Duplicate credential config** | The user enters the same API key in two places. If they rotate a key, they must update both. |
| **No shared rate limiting** | The tool module and import module each manage their own rate limiters. A bulk import can exhaust the API quota, causing simultaneous tool calls to fail — neither module knows about the other's usage. |

---

## What the Connections Layer Provides

The Connections Layer introduces a single abstraction — a **connection** — for each external service. A connection encapsulates:

```
┌──────────────────────────────────────────────────────┐
│                   Connection                          │
│                   (e.g. "notion")                     │
│                                                      │
│  1. Credentials   ← API key, token, OAuth config     │
│  2. API Client    ← Authenticated httpx client        │
│  3. Rate Limiter  ← Shared across all consumers       │
│  4. Health Check  ← "Can I reach this service?"       │
│  5. Metadata      ← Service name, base URL, docs URL  │
└──────────────────────────────────────────────────────┘
         │                          │
         ▼                          ▼
   Tool Module                Import Module
   (request-time)             (bulk operations)
```

A connection is **not** a module. It does not contain business logic, tool functions, or import pipelines. It is infrastructure — a configured, authenticated, rate-limited client that modules take as a dependency.

---

## Where the Connections Layer Sits

```
                        ┌──────────────────────────────────────────────────┐
                        │              ORCHESTRATOR                        │
                        │                                                  │
                        │  ┌──────────────────────────────────────────┐   │
                        │  │           Connection Registry             │   │
                        │  │                                          │   │
                        │  │  ┌─────────┐ ┌─────────┐ ┌─────────┐   │   │
                        │  │  │ Notion  │ │ Trello  │ │  Miro   │   │   │
                        │  │  │  Conn   │ │  Conn   │ │  Conn   │   │   │
                        │  │  └────┬────┘ └────┬────┘ └────┬────┘   │   │
                        │  └───────┼──────────┼──────────┼─────────┘   │
                        │          │          │          │              │
                        │   ┌──────▼──────────▼──────────▼──────────┐  │
                        │   │                                       │  │
                        │   │  ┌───────────────┐ ┌───────────────┐  │  │
                        │   │  │ Tool Module   │ │ Import Module │  │  │
                        │   │  │ Layer         │ │ Layer         │  │  │
                        │   │  └───────────────┘ └───────────────┘  │  │
                        │   │                                       │  │
                        │   └───────────────────────────────────────┘  │
                        └──────────────────────────────────────────────┘
```

The Connection Registry is initialized at Orchestrator startup, before either the Tool Registry or the Import Registry. Both registries receive a reference to the Connection Registry and use it to look up connections for the services they need.

---

## BaseConnection (the contract every connection implements)

Every external service connection implements the same interface. The interface is deliberately minimal — a connection knows how to authenticate and communicate, not what to do with the data.

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import httpx


@dataclass
class ConnectionStatus:
    """Result of a connection health check."""
    healthy: bool
    service_name: str
    message: str = ""
    latency_ms: float | None = None


class BaseConnection(ABC):

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique connection identifier (e.g. 'notion', 'trello').

        This name is used as the lookup key in the Connection Registry
        and as the config section name in config.yaml.
        """
        ...

    @property
    @abstractmethod
    def service_display_name(self) -> str:
        """Human-readable service name for logging and CLI output."""
        ...

    @abstractmethod
    async def initialize(self, config: dict) -> None:
        """Set up the authenticated client using the provided config.

        Reads credentials from config (which may reference env vars),
        constructs the httpx.AsyncClient with auth headers and base URL,
        and configures the rate limiter.

        Raises ConnectionConfigError if required credentials are missing
        or invalid.
        """
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        """Close the HTTP client and release resources."""
        ...

    @abstractmethod
    async def health_check(self) -> ConnectionStatus:
        """Verify that the service is reachable and credentials are valid.

        Makes a lightweight API call (e.g. "get current user" or
        "list workspaces") to confirm the connection works.
        """
        ...

    @abstractmethod
    def get_client(self) -> httpx.AsyncClient:
        """Return the authenticated, rate-limited HTTP client.

        Consumers (tool modules, import sources) use this client
        for all API calls to the service. The client has:
        - Base URL pre-configured
        - Auth headers set
        - Timeout defaults applied
        - Rate limiting via the shared limiter
        """
        ...

    def get_rate_limiter(self) -> "RateLimiter | None":
        """Return the shared rate limiter for this service, if any.

        Consumers that need fine-grained rate control (e.g. bulk
        imports that must pace requests) can access the limiter
        directly. Returns None if the service has no rate limits.
        """
        return None
```

**What a connection owns vs. what it does not:**

| Owned by the connection | NOT owned by the connection |
|---|---|
| API credentials (keys, tokens) | Business logic (what to do with API responses) |
| Authenticated HTTP client | Tool function definitions |
| Base URL, auth headers | Import extraction logic |
| Rate limiter (shared) | Conversion pipelines |
| Health check (credential validity) | Vault writing |
| Retry policy (transient errors) | Frontmatter generation |
| Timeout defaults | Skills / domain knowledge |

---

## Connection Registry

The Connection Registry is the central catalog of all available connections. It initializes connections at startup and provides them to any module that needs one.

```python
class ConnectionRegistry:

    async def register(self, connection: BaseConnection, config: dict) -> None:
        """Initialize and register a connection.

        Calls connection.initialize(config), then stores it
        by name for lookup.
        """
        await connection.initialize(config)
        self._connections[connection.name] = connection

    def get(self, name: str) -> BaseConnection:
        """Return a registered connection by name.

        Raises ConnectionNotFound if the connection is not registered
        or was not enabled in config.
        """
        if name not in self._connections:
            available = ", ".join(self.list()) or "(none)"
            raise ConnectionNotFound(
                f"Connection '{name}' is not registered. "
                f"Available: {available}"
            )
        return self._connections[name]

    def has(self, name: str) -> bool:
        """Check if a connection is registered (without raising)."""
        return name in self._connections

    def list(self) -> list[str]:
        """Return names of all registered connections."""
        return list(self._connections.keys())

    async def health_check_all(self) -> dict[str, ConnectionStatus]:
        """Run health checks on all registered connections."""
        results = {}
        for name, conn in self._connections.items():
            results[name] = await conn.health_check()
        return results

    async def shutdown_all(self) -> None:
        """Shut down all registered connections."""
        for conn in self._connections.values():
            await conn.shutdown()
```

**Lifecycle:**

```
Orchestrator startup:
  1. Read config.yaml → connections section
  2. For each enabled connection:
     a. Instantiate the connection class
     b. Call ConnectionRegistry.register(connection, config)
        → connection.initialize(config) is called internally
     c. Call connection.health_check()
        → If unhealthy: log warning, mark as degraded, continue
  3. Pass ConnectionRegistry to ToolRegistry and ImportRegistry
  4. Tool modules and import sources request connections by name

Orchestrator shutdown:
  1. Call ConnectionRegistry.shutdown_all()
     → Each connection's shutdown() closes its HTTP client
```

---

## How Modules Consume Connections

### Tool Modules

A tool module declares which connection it needs. During initialization, it receives the Connection Registry and looks up its connection.

```python
from harle.tools.base import BaseToolModule
from harle.connections.registry import ConnectionRegistry


class TrelloModule(BaseToolModule):
    name = "trello"
    description = "Trello board management for task tracking"

    async def initialize(
        self, config: dict, connections: ConnectionRegistry
    ) -> None:
        self._conn = connections.get("trello")
        self._client = self._conn.get_client()
        self._default_board = config.get("default_board")

    async def shutdown(self) -> None:
        pass  # HTTP client lifecycle is managed by the connection

    def get_tools(self) -> list:
        return [search_cards, create_card, move_card]

    async def health_check(self) -> bool:
        status = await self._conn.health_check()
        return status.healthy
```

The `initialize()` signature gains an optional `connections` parameter. Modules that do not use external services (e.g. the vault module, the scripts module) ignore it.

The change to `BaseToolModule` is backward-compatible: `connections` has a default value of `None`, so existing modules that do not need connections continue to work unchanged.

```python
class BaseToolModule(ABC):

    @abstractmethod
    async def initialize(
        self,
        config: dict,
        connections: "ConnectionRegistry | None" = None,
    ) -> None:
        """Set up clients, validate credentials, prepare state.

        Modules that need external service connections should look
        them up from the connections registry. Modules that operate
        locally (vault, scripts) can ignore the connections parameter.
        """
        ...
```

### Import Sources

Import sources follow the same pattern:

```python
from harle.imports.base import BaseImportSource
from harle.connections.registry import ConnectionRegistry


class NotionImportSource(BaseImportSource):
    name = "notion"
    description = "Import pages and databases from Notion"

    def supported_modes(self) -> list[str]:
        return ["file", "api"]

    async def initialize(
        self, config: dict, connections: ConnectionRegistry | None = None
    ) -> None:
        self._config = config
        if connections and connections.has("notion"):
            self._conn = connections.get("notion")
        else:
            self._conn = None

    async def extract(self, config: dict) -> list["ImportItem"]:
        mode = config.get("mode", "file")

        if mode == "file":
            return await self._extract_from_zip(config)

        if self._conn is None:
            raise ImportError(
                "Notion API mode requires the 'notion' connection. "
                "Add it to the connections section in config.yaml."
            )
        client = self._conn.get_client()
        return await self._extract_from_api(config, client)
```

For file-based import modes (e.g. Notion ZIP export), no connection is needed. For API-based modes, the source uses the shared connection. This keeps file-based imports working without any connection configuration — important for the onboarding experience where a user might start with a ZIP export before setting up API tokens.

---

## Connection Examples

### Notion Connection

```python
import httpx

from harle.connections.base import BaseConnection, ConnectionStatus


class NotionConnection(BaseConnection):
    name = "notion"
    service_display_name = "Notion"

    async def initialize(self, config: dict) -> None:
        token = config.get("api_token")
        if not token:
            raise ConnectionConfigError(
                "Notion connection requires 'api_token'. "
                "Set NOTION_API_TOKEN or add api_token to the "
                "notion connection config."
            )
        self._client = httpx.AsyncClient(
            base_url="https://api.notion.com/v1",
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": "2022-06-28",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(30.0),
        )

    async def shutdown(self) -> None:
        await self._client.aclose()

    async def health_check(self) -> ConnectionStatus:
        try:
            resp = await self._client.get("/users/me")
            if resp.status_code == 200:
                return ConnectionStatus(
                    healthy=True,
                    service_name=self.service_display_name,
                    message="Authenticated successfully",
                )
            return ConnectionStatus(
                healthy=False,
                service_name=self.service_display_name,
                message=f"API returned {resp.status_code}",
            )
        except httpx.HTTPError as e:
            return ConnectionStatus(
                healthy=False,
                service_name=self.service_display_name,
                message=str(e),
            )

    def get_client(self) -> httpx.AsyncClient:
        return self._client
```

### Trello Connection

```python
import httpx

from harle.connections.base import BaseConnection, ConnectionStatus


class TrelloConnection(BaseConnection):
    name = "trello"
    service_display_name = "Trello"

    async def initialize(self, config: dict) -> None:
        api_key = config.get("api_key")
        api_token = config.get("api_token")
        if not api_key or not api_token:
            raise ConnectionConfigError(
                "Trello connection requires 'api_key' and 'api_token'. "
                "Set TRELLO_API_KEY and TRELLO_API_TOKEN or add them "
                "to the trello connection config."
            )
        self._client = httpx.AsyncClient(
            base_url="https://api.trello.com/1",
            params={"key": api_key, "token": api_token},
            timeout=httpx.Timeout(30.0),
        )

    async def shutdown(self) -> None:
        await self._client.aclose()

    async def health_check(self) -> ConnectionStatus:
        try:
            resp = await self._client.get("/members/me")
            if resp.status_code == 200:
                return ConnectionStatus(
                    healthy=True,
                    service_name=self.service_display_name,
                    message="Authenticated successfully",
                )
            return ConnectionStatus(
                healthy=False,
                service_name=self.service_display_name,
                message=f"API returned {resp.status_code}",
            )
        except httpx.HTTPError as e:
            return ConnectionStatus(
                healthy=False,
                service_name=self.service_display_name,
                message=str(e),
            )

    def get_client(self) -> httpx.AsyncClient:
        return self._client
```

---

## Rate Limiting

External APIs enforce rate limits. When both a tool module and an import source hit the same API, they must share a single rate limiter — otherwise a bulk import can exhaust the quota and break concurrent tool calls.

The connection owns the rate limiter. Consumers do not need to think about rate limits — the limiter is applied transparently through the shared client or can be queried explicitly for bulk operations that need pacing.

```python
import asyncio
import time
from dataclasses import dataclass


@dataclass
class RateLimitConfig:
    """Rate limit configuration for a connection."""
    requests_per_second: float = 3.0
    burst: int = 5


class RateLimiter:
    """Token-bucket rate limiter shared across all consumers of a connection."""

    def __init__(self, config: RateLimitConfig) -> None:
        self._rate = config.requests_per_second
        self._burst = config.burst
        self._tokens = float(config.burst)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a request token is available."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(
                self._burst, self._tokens + elapsed * self._rate
            )
            self._last_refill = now

            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0.0
            else:
                self._tokens -= 1.0
```

A connection optionally creates a `RateLimiter` based on config and applies it inside `get_client()` or exposes it via `get_rate_limiter()`. For services with well-documented rate limits (Notion: 3 req/s, Trello: 100 req/10s), the connection ships sensible defaults. The user can override via config.

---

## Configuration

Connection configuration lives in `config.yaml` under a dedicated `connections` section. This is the **single place** where credentials for each external service are declared.

```yaml
connections:
  notion:
    enabled: true
    api_token: ${NOTION_API_TOKEN}
    rate_limit:
      requests_per_second: 3
      burst: 5

  trello:
    enabled: true
    api_key: ${TRELLO_API_KEY}
    api_token: ${TRELLO_API_TOKEN}
    rate_limit:
      requests_per_second: 10
      burst: 20

  miro:
    enabled: true
    api_token: ${MIRO_API_TOKEN}
    rate_limit:
      requests_per_second: 5
      burst: 10

  tavily:
    enabled: true
    api_key: ${TAVILY_API_KEY}

# Tool modules reference connections by name — no credentials here
tool_modules:
  trello:
    enabled: true
    connection: trello          # ← references connections.trello
    default_board: "Work Tasks"
    mode: propose
    skills: [triage, conventions]

  web_search:
    enabled: true
    connection: tavily          # ← references connections.tavily
    max_results: 5
    mode: auto
    skills: [research]

  notion:
    enabled: false
    connection: notion          # ← references connections.notion
    skills: []

# Import sources also reference connections by name
import_sources:
  notion:
    enabled: true
    connection: notion          # ← same connection as the tool module
    default_mode: file
    default_context: personal
    target_dir: "knowledge/"

  miro:
    enabled: true
    connection: miro            # ← references connections.miro
    default_context: work
    target_dir: "knowledge/work/"
```

**What changes from the current config pattern:**

| Before (without connections) | After (with connections) |
|---|---|
| Credentials in `tool_modules.trello.api_key` | Credentials in `connections.trello.api_key` |
| Same credentials duplicated in `import_sources.trello.api_key` | Tool module and import source both say `connection: trello` |
| Rate limiting per module (or absent) | Rate limiting per connection, shared across all consumers |
| No unified health check dashboard | `harle connections status` shows all services at once |

**Secrets stay in environment variables.** The `connections` section references env vars (`${TRELLO_API_KEY}`) just like the existing config pattern. No credentials are hardcoded. The difference is that each credential is referenced exactly once, in the connection config, rather than repeated per-module.

---

## CLI Integration

The Connections Layer adds a `connections` command group to the CLI for managing and inspecting connections.

```
harle connections status        Show health status of all connections
harle connections list          List all configured connections
harle connections test <name>   Test a specific connection
```

**Example output:**

```
$ harle connections status
Connection       Status     Latency   Details
─────────────────────────────────────────────────────
notion           healthy     142ms    Authenticated as workspace "Acme Corp"
trello           healthy      89ms    Authenticated as user "alex@example.com"
miro             unhealthy     —      API returned 401 (token expired)
tavily           healthy      67ms    API key valid

3 healthy, 1 unhealthy
```

This replaces the need to debug connection issues through scattered tool module health checks. A single command shows the status of all external services.

---

## How It Fits Into the Startup Sequence

```
Orchestrator startup (revised order):

  1. Load config.yaml
  2. Initialize Connection Registry                    ← NEW (before modules)
     For each enabled connection in config.connections:
       a. Instantiate connection class
       b. Call registry.register(connection, config)
       c. Run health_check() — log results, mark unhealthy connections
  3. Initialize Tool Module Layer
     For each enabled tool module:
       a. Import module class
       b. Call module.initialize(config, connections=connection_registry)
          → Module looks up its connection by name
       c. Call module.health_check()
       d. Register with Tool Registry
  4. Initialize Import Module Layer
     For each enabled import source:
       a. Import source class
       b. Call source.initialize(config, connections=connection_registry)
          → Source looks up its connection by name (if it has API mode)
       c. Register with Import Registry
  5. Start HTTP server
```

Connections are initialized first because both tool modules and import sources depend on them. If a connection is unhealthy at startup, the dependent modules are still initialized — they report degraded status and fail gracefully when invoked (e.g. "Trello connection is not available. Check your API credentials.").

---

## Modules Without Connections

Not every module needs an external connection:

| Module | Connection needed? | Why |
|---|---|---|
| Vault (tools) | No | Reads/writes local files |
| Scripts (tools) | No | Executes local processes |
| Web Search (tools) | Yes (`tavily` or `bing`) | Calls a search API |
| Trello (tools) | Yes (`trello`) | Calls the Trello API |
| Notion (tools) | Yes (`notion`) | Calls the Notion API |
| Notion (import, file mode) | No | Parses a local ZIP file |
| Notion (import, API mode) | Yes (`notion`) | Calls the Notion API |
| Miro (import) | Yes (`miro`) | Calls the Miro API |
| Bookmarks (import) | No | Parses a local HTML file |

Modules that do not use connections simply ignore the `connections` parameter in `initialize()`. The Connection Registry is passed but not required.

---

## Service-Specific Helpers

While `get_client()` returns a raw `httpx.AsyncClient`, some services have complex APIs that benefit from a thin helper layer on top of the authenticated client. These helpers live alongside the connection and provide typed methods for common operations.

```python
class NotionConnection(BaseConnection):
    name = "notion"
    service_display_name = "Notion"

    # ... initialize, shutdown, health_check, get_client ...

    async def query_database(
        self, database_id: str, filter: dict | None = None
    ) -> list[dict]:
        """Query a Notion database with optional filter.

        This is a convenience method used by both the Notion tool
        module and the Notion import source. It handles pagination
        and rate limiting transparently.
        """
        results = []
        has_more = True
        start_cursor = None

        while has_more:
            if self.get_rate_limiter():
                await self.get_rate_limiter().acquire()
            body = {"page_size": 100}
            if filter:
                body["filter"] = filter
            if start_cursor:
                body["start_cursor"] = start_cursor

            resp = await self._client.post(
                f"/databases/{database_id}/query", json=body
            )
            resp.raise_for_status()
            data = resp.json()
            results.extend(data["results"])
            has_more = data.get("has_more", False)
            start_cursor = data.get("next_cursor")

        return results

    async def get_page(self, page_id: str) -> dict:
        """Retrieve a single Notion page by ID."""
        if self.get_rate_limiter():
            await self.get_rate_limiter().acquire()
        resp = await self._client.get(f"/pages/{page_id}")
        resp.raise_for_status()
        return resp.json()
```

These helper methods are **optional**. Simple services (like Tavily) may only need `get_client()`. Complex services (like Notion, with pagination, nested blocks, and rich property types) benefit from shared helpers that both the tool module and import source reuse.

The helpers are not meant to be exhaustive API wrappers — they cover the operations that multiple consumers share. Module-specific logic (e.g. how the Notion import source flattens a page hierarchy into vault paths) stays in the module.

---

## Adding a New Connection

Adding a connection for a new external service requires two steps:

1. **Create the connection class:** `src/harle/connections/<service>.py` — implement `BaseConnection`.
2. **Add config:** Add the service's section to `connections` in `config.yaml`.

No changes to the Connection Registry, the CLI, or any module are needed. The new connection automatically appears in `harle connections list` and is available for any module to reference.

**Checklist:**

| Step | What to do |
|---|---|
| Create `<service>.py` | Implement `BaseConnection` with `initialize()`, `shutdown()`, `health_check()`, `get_client()` |
| Add rate limiter | If the service has documented rate limits, create a `RateLimiter` with appropriate defaults |
| Add service helpers | If the API has complex patterns (pagination, nested resources), add typed helper methods |
| Add config block | Add the connection's section to `config.example.yaml` with credential env var references |
| Register | Add the connection to the registry in `src/harle/connections/__init__.py` |
| Test | Unit test with mocked HTTP responses for `health_check()` and helper methods |

---

## Error Handling

| Error | What happens | User experience |
|---|---|---|
| **Missing credentials** | `initialize()` raises `ConnectionConfigError` | Startup log: "Connection 'trello' failed: api_key is required. Set TRELLO_API_KEY." |
| **Invalid credentials** | `health_check()` returns unhealthy status | `harle connections status`: "trello — unhealthy — API returned 401" |
| **Service unreachable** | `health_check()` returns unhealthy, httpx timeout | `harle connections status`: "notion — unhealthy — Connection timed out" |
| **Rate limited** | Rate limiter pauses before the request | Transparent to the consumer. Bulk imports log: "Rate limited. Pacing at 3 req/s." |
| **Connection not found** | `registry.get()` raises `ConnectionNotFound` | Module init fails with: "Connection 'xyz' is not registered. Available: notion, trello" |
| **Module references disabled connection** | `registry.get()` raises `ConnectionNotFound` | "Connection 'miro' is not enabled. Enable it in the connections section of config.yaml." |
| **Token expiry (OAuth)** | `health_check()` detects 401 on periodic check | `harle connections status`: "miro — unhealthy — token expired. Re-authenticate." |

All connection errors are logged with the service name and error details. When a module's connection is unhealthy, the module itself reports degraded status — tool calls return a clear error message, and import runs for that source are blocked with an explanation.

---

## Project Structure

```
src/harle/connections/                  ← Connections Layer code
├── __init__.py                         # Package init, connection discovery
├── base.py                             # BaseConnection ABC, ConnectionStatus
├── registry.py                         # ConnectionRegistry class
├── rate_limiter.py                     # RateLimiter (token bucket, shared)
├── exceptions.py                       # ConnectionConfigError, ConnectionNotFound
│
├── notion.py                           # NotionConnection(BaseConnection)
├── trello.py                           # TrelloConnection(BaseConnection)
├── miro.py                             # MiroConnection(BaseConnection)
├── tavily.py                           # TavilyConnection(BaseConnection)
└── ...                                 # Future connections
```

Connections are flat files (one per service), not nested directories, because a connection is a single class with no submodules. This keeps the layer lightweight.

**Relationship to existing module directories:**

```
BEFORE:
  src/harle/tools/trello/client.py      ← API wrapper + credentials
  src/harle/imports/trello/api_client.py ← Duplicate API wrapper + credentials

AFTER:
  src/harle/connections/trello.py        ← Shared connection (credentials, client, rate limiter)
  src/harle/tools/trello/tools.py        ← Tool functions (use connection.get_client())
  src/harle/imports/trello/source.py     ← Import source (use connection.get_client())
```

The `client.py` / `api_client.py` files in individual tool and import modules are replaced by the connection. Module-specific logic (tool functions, extraction pipelines) remains in the module.

---

## Technology Choices Summary

| Decision | Choice | Key reason |
|---|---|---|
| **Connection interface** | Python ABC (`BaseConnection`) | Mirrors `BaseToolModule` and `BaseImportSource` — consistent pattern across the project |
| **Registry pattern** | Central `ConnectionRegistry` class | Matches `ToolRegistry` and `ImportRegistry` — uniform discovery, lifecycle, lookup |
| **HTTP client** | httpx (async) | Already used by tool modules and import sources — no new dependency |
| **Rate limiting** | Token-bucket algorithm | Simple, effective, well-understood. Shared instance prevents quota exhaustion across consumers |
| **Configuration** | `config.yaml` under `connections` key | Single location for credentials, referenced by name from `tool_modules` and `import_sources` |
| **Helper methods** | Optional methods on the connection class | Avoids a separate "service SDK" layer while enabling shared complex operations (pagination, nested queries) |

---

## Impact on Existing TRDs

This design requires updates to two existing documents:

### tools.md changes

- `BaseToolModule.initialize()` gains an optional `connections` parameter.
- Tool module `client.py` files are replaced by connection lookups. Module-specific business logic remains in `tools.py`.
- The `tool_modules` config section references connections by name (`connection: trello`) instead of embedding credentials (`api_key`, `api_token`).
- The health check in tool modules delegates to the connection's health check.
- The Orchestrator startup sequence initializes the Connection Registry before the Tool Registry.

### import_module.md changes

- `BaseImportSource` gains an optional `initialize()` method with a `connections` parameter (currently the interface does not have `initialize()`; sources receive config at `extract()` time).
- Import source `api_client.py` files are replaced by connection lookups. Source-specific extraction logic remains in `source.py`.
- The `import_sources` config section references connections by name instead of embedding credentials.
- File-mode import sources (e.g. Notion ZIP) continue to work without any connection.

These updates are additive — existing module code works unchanged until it opts in to using a connection.

---

## Incremental Implementation Plan

### Phase overview

```
Phase 1: Core infrastructure
    │     (base.py, registry.py, rate_limiter.py, exceptions.py)
    │
    ├──→ Phase 2: First connection (Tavily — simplest service)
    │       │
    │       └──→ Phase 3: Migrate Web Search tool module to use connection
    │
    └──→ Phase 4: Remaining connections + module migration
            │
            └──→ Phase 5: CLI integration (harle connections status)
```

### Phase 1: Core Infrastructure

**Goal:** Establish the connection contract, the registry, and the rate limiter. After this phase, the framework exists and can accept connections.

| File | Contents |
|---|---|
| `src/harle/connections/__init__.py` | Package init, re-exports `BaseConnection` and `ConnectionRegistry` |
| `src/harle/connections/base.py` | `BaseConnection` ABC, `ConnectionStatus` dataclass |
| `src/harle/connections/registry.py` | `ConnectionRegistry` — `register()`, `get()`, `has()`, `list()`, `health_check_all()`, `shutdown_all()` |
| `src/harle/connections/rate_limiter.py` | `RateLimiter` (token-bucket), `RateLimitConfig` |
| `src/harle/connections/exceptions.py` | `ConnectionConfigError`, `ConnectionNotFound` |

**Verification:** Write a test connection with a mocked HTTP client. Register it with the registry. Verify `get()`, `health_check_all()`, and `shutdown_all()` work correctly.

**Dependencies:** None.

**Estimated size:** ~250 lines of production code, ~200 lines of tests.

### Phase 2: First Connection (Tavily)

**Goal:** Prove the pattern works with the simplest external service. Tavily is a good first connection because it has a single API key, no OAuth, no complex pagination, and is already used by the Web Search tool module.

| File | Contents |
|---|---|
| `src/harle/connections/tavily.py` | `TavilyConnection(BaseConnection)` |

**Verification:** Unit test with mocked Tavily API. Verify `health_check()` and `get_client()`.

**Dependencies:** Phase 1.

**Estimated size:** ~80 lines of production code, ~60 lines of tests.

### Phase 3: Migrate Web Search Module

**Goal:** Update the Web Search tool module to use the Tavily connection instead of its own embedded client. This validates the full integration path: Connection Registry → Tool Module → tool function execution.

**What changes:**

| Component | Change |
|---|---|
| `WebSearchModule.initialize()` | Receives `connections` parameter, looks up `tavily` connection |
| `WebSearchModule` client usage | Uses `connection.get_client()` instead of creating its own `httpx.AsyncClient` |
| `config.yaml` | Move `api_key` from `tool_modules.web_search` to `connections.tavily`; add `connection: tavily` to `tool_modules.web_search` |
| Orchestrator startup | Initialize Connection Registry before Tool Registry |

**Dependencies:** Phase 2.

**Estimated size:** ~50 lines of changes (mostly deletions from the module's `client.py`).

### Phase 4: Remaining Connections + Module Migration

**Goal:** Add connections for Notion, Trello, and Miro. Migrate the corresponding tool modules and import sources to use shared connections.

| Connection | Consumers |
|---|---|
| `NotionConnection` | Notion tool module, Notion import source (API mode) |
| `TrelloConnection` | Trello tool module, Trello import source (future) |
| `MiroConnection` | Miro import source |

Each connection + migration is independent and can be done in any order.

**Dependencies:** Phase 1 (for connections), Phase 3 pattern (for migration approach).

**Estimated size per connection:** ~100–150 lines of production code, ~80–100 lines of tests. Module migration: ~30–50 lines of changes per module (mostly deletions).

### Phase 5: CLI Integration

**Goal:** Add `harle connections status/list/test` commands to the CLI.

**Dependencies:** Phase 3 (at least one connection wired end-to-end).

**Estimated size:** ~150 lines Go CLI code.

### Phase dependency diagram

```
                Phase 1
           Core Infrastructure
          (base, registry, limiter)
                │
        ┌───────┴───────┐
        │               │
        ▼               │
    Phase 2             │
    First Connection    │
    (Tavily)            │
        │               │
        ▼               │
    Phase 3             │
    Migrate Web Search  │
    Module              │
        │               │
        ├───────────────┘
        │
        ▼
    Phase 4
    Remaining Connections
    + Module Migration
        │
        ▼
    Phase 5
    CLI Integration
```

### Effort estimates

| Phase | Estimated effort | Can parallelize with |
|---|---|---|
| **1. Core infrastructure** | 1 day | — |
| **2. Tavily connection** | 0.5 day | — |
| **3. Web Search migration** | 0.5 day | — |
| **4. Remaining connections** | 1–2 days | Each connection is independent |
| **5. CLI integration** | 0.5–1 day | Phase 4 |
| **Total** | ~4–5 days | |

The Connections Layer is a small, focused piece of infrastructure. The bulk of the work is migrating existing modules to use connections — and each migration is a simplification (deleting duplicate client code), not new complexity.

---

## Relationship to Other Components

| Component | Relationship |
|---|---|
| **Tool Module Layer** | Tool modules are primary consumers. Modules that access external APIs receive a `ConnectionRegistry` at `initialize()` and look up their connection by name. The module's `client.py` is replaced by `connection.get_client()`. Module-specific tool functions and business logic are unchanged. |
| **Import Module Layer** | Import sources are the other primary consumer. API-mode sources use shared connections; file-mode sources do not need connections. This eliminates the duplicate `api_client.py` files in import source directories. |
| **Orchestrator** | The Orchestrator owns the `ConnectionRegistry` and initializes it before the Tool and Import registries. It passes the registry to both layers during startup. |
| **CLI** | The CLI gains a `connections` command group for inspecting connection status. This provides a unified view of all external service health. |
| **Configuration** | The `connections` section in `config.yaml` becomes the single source of truth for external service credentials. `tool_modules` and `import_sources` sections reference connections by name, not by credential values. |
| **Vault Capture Module** | Does not use connections. Vault capture interacts with the user and writes to the local vault — no external APIs. |
