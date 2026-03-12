---
title: "Harle Debug Logging — Architecture & Functionality"
tags: [debug, logging, tracing, observability, opentelemetry, cli, vault, architecture]
context: global
last_updated: 2026-03-12
summary: "Describes the debug logging system built on OpenTelemetry that captures hierarchical processing traces across all subsystems, stores them to DB and vault unconditionally, and surfaces them in the UI when debug mode is active."
---

# Harle Debug Logging — Architecture & Functionality

> When you ask Harle a question, the result appears — but you cannot see what happened inside: which agent was chosen, what context was assembled, which tools were called, or why the model decided what it decided. Debug logging makes the invisible visible.

This document describes a **system-wide debug logging layer** that captures structured, hierarchical traces of every processing step across every Harle subsystem. The traces are **always written** to the database and vault (regardless of mode), and **displayed in the UI only when the user activates debug mode**.

The system is built on [OpenTelemetry](https://opentelemetry.io/) — the industry-standard observability framework — with a thin convenience API (`dtrace`) and three custom exporters for Harle's specific output targets.

For the overall system architecture, see [overview.md](./overview.md).
For the Run Logger (per-run result/context files), see [orchestrator.md](./orchestrator.md) §7.

---

## Why This Exists

Harle already has two kinds of logging:

1. **Standard Python logging** (`logging.getLogger(__name__)`) — used throughout the codebase for developer-facing messages (`INFO`, `WARNING`, `ERROR`). This is operational logging: it goes to the server console and is useful for diagnosing crashes or configuration problems. It is **not** visible to the end user.

2. **Run Logger** (`src/harle/logging/run_logger.py`) — writes per-run result files and optional context snapshots to the vault `logs/` directory and to PostgreSQL. This is a structured record of **what** happened (which agent, which tools, final result), but not **how** it happened step by step.

Neither of these answers the question: *"Why did Harle do that?"*

Debug logging fills this gap. It captures the **internal reasoning chain** — every decision point, every intermediate value, every branch taken — in a hierarchical, human-readable format. Think of it as a flight recorder for every request.

**What debug logging enables:**

| Scenario | Without debug logging | With debug logging |
|---|---|---|
| Result seems wrong | "Something broke, no idea where" | Trace shows the router picked the wrong agent because keyword "research" matched |
| Response is slow | "It took 12 seconds, I don't know why" | Trace shows web search tool timed out on the second query |
| Context seems off | "The model ignored my policy file" | Trace shows the policy was loaded but trimmed at P3 priority due to token budget |
| Tool failed silently | "Trello integration isn't working" | Trace shows the API returned 401, caught by retry logic, gave up after 3 attempts |
| User wants transparency | "What did you actually do?" | Full hierarchical trace shown inline in the CLI |

---

## Design Principles

1. **Always capture, conditionally display.** Traces are written to DB and vault on every run. The user controls visibility — not whether data is recorded.
2. **Hierarchical, not flat.** Steps nest naturally: a request contains routing, which contains rule evaluation. A flat list of log lines is hard to follow; a tree is intuitive.
3. **Human-readable first.** Traces must make sense to someone reading them in a terminal or in a Markdown file — not just to a machine.
4. **Visually distinct in code.** A developer reading the source code must immediately tell debug logging calls apart from business logic. Debug logging is infrastructure, not behavior.
5. **Zero overhead when not displayed.** Collection is lightweight (appending to an in-memory list). The user pays no latency cost for debug logging — only storage cost (which is negligible for text).
6. **Any subsystem, no coupling.** The capture module, tools, orchestrator, context assembler, search, imports, connections — any current or future module can emit debug entries without importing heavy dependencies or knowing about other modules.
7. **Build on proven infrastructure.** Span collection, context propagation, parallel-safe nesting, and thread safety are solved problems. OpenTelemetry handles all of this. Harle only builds what is unique to Harle: the three custom exporters and the convenience API.

---

## Architecture Overview

```
                     ┌───────────────────────────────────────────┐
                     │               REQUEST SCOPE               │
                     │                                           │
  CLI ──HTTP──>      │   ┌─────────────────────────────────┐     │
                     │   │     OpenTelemetry TracerProvider │     │
                     │   │                                 │     │
                     │   │   root span: "run_abc123"       │     │
                     │   │   ├── routing                   │     │
                     │   │   │   ├── keyword check         │     │
                     │   │   │   └── agent selected        │     │
                     │   │   ├── context assembly          │     │
                     │   │   │   ├── search (3 results)    │     │
                     │   │   │   ├── policy loaded         │     │
                     │   │   │   └── token budget: 82%     │     │
                     │   │   ├── agent execution           │     │
                     │   │   │   ├── LLM call #1           │     │
                     │   │   │   ├── tool: web_search      │     │
                     │   │   │   │   ├── query sent        │     │
                     │   │   │   │   └── 5 results back    │     │
                     │   │   │   └── LLM call #2 (final)   │     │
                     │   │   └── result stored             │     │
                     │   │                                 │     │
                     │   └─────────────┬───────────────────┘     │
                     │                 │                         │
                     └─────────────────┼─────────────────────────┘
                                       │
                          ┌────────────┼────────────┐
                          │            │            │
                          ▼            ▼            ▼
                   ┌──────────┐  ┌─────────┐  ┌─────────┐
                   │ CLI SSE  │  │ Vault   │  │ Postgre │
                   │ exporter │  │exporter │  │SQL      │
                   │ (if      │  │(always) │  │exporter │
                   │ debug)   │  │         │  │(always) │
                   └──────────┘  └─────────┘  └─────────┘
                   Custom SpanExporter implementations
```

Three components work together:

1. **OpenTelemetry SDK** — the `TracerProvider`, `Tracer`, and `Span` types handle all span creation, context propagation, parent-child linking, and concurrency safety. This is the engine.
2. **Custom `SpanExporter` implementations** — three adapters that receive completed spans from OTel and write them to Harle's specific destinations (vault Markdown files, PostgreSQL JSONB, CLI SSE stream).
3. **`dtrace` API** — a thin convenience wrapper so subsystem code writes `dtrace.step(...)` instead of the verbose OTel API directly.

---

## Why OpenTelemetry

Building a custom span collector, context propagation system, and parallel-safe nesting tracker is the same work OpenTelemetry has already done — and battle-tested across thousands of production systems. Using OTel directly eliminates an entire category of bugs and gives us capabilities for free.

**What OpenTelemetry provides (that we do not build):**

| Capability | OTel component | What we would have had to build |
|---|---|---|
| Span creation and lifecycle | `Tracer.start_as_current_span()` | `DebugCollector` with flat list + lock |
| Parent-child linking | Automatic via context propagation | Manual `parent_id` tracking |
| Parallel-safe nesting (`asyncio.gather`) | Built-in `contextvars` context copying | Two separate `ContextVar` instances, manual stack management |
| Thread safety (`asyncio.to_thread`) | Built-in thread-safe span storage | `threading.Lock` on span list, explicit context copying |
| Span attributes (key-value data) | `span.set_attribute()` | Custom `attributes: dict[str, Any]` |
| Span status (ok/error) | `span.set_status()` | Custom `SpanStatus` enum |
| Decorator for auto-spanning | `@tracer.start_as_current_span` | Custom `@dtrace.span_fn` decorator |
| No-op when no provider configured | `NoOpTracer` (default) | Manual "check if collector exists" logic |
| Export pipeline | `SpanProcessor` + `SpanExporter` interface | Custom sink architecture |

**What OpenTelemetry does NOT provide (what we build):**

| Capability | Why it's Harle-specific |
|---|---|
| Vault Markdown exporter | OTel has no concept of writing Markdown files to an Obsidian vault |
| PostgreSQL JSONB exporter | OTel's standard exporters target OTLP, Jaeger, Zipkin — not our `debug_traces` table |
| CLI SSE stream exporter | Real-time debug output interleaved with response streaming is a Harle UI feature |
| `dtrace` convenience API | Maps Harle's trace levels (STEP/DETAIL/TRACE/INTERNAL) to OTel span attributes; provides a clean, minimal API |
| Trace level filtering | OTel spans don't have "levels" — we add `harle.level` as a custom attribute and filter in exporters |

**Why not use OTel's standard exporters (OTLP, Jaeger)?**

Those exporters send spans to external observability platforms. Harle needs to write traces to its own vault and database — not to a Jaeger instance. However, because we use the standard OTel SDK, adding an OTLP exporter later is a one-line configuration change. The two approaches are not mutually exclusive.

### Technology: OpenTelemetry Python SDK

The [opentelemetry-api](https://pypi.org/project/opentelemetry-api/) and [opentelemetry-sdk](https://pypi.org/project/opentelemetry-sdk/) packages provide the core tracing functionality. These are the official Python implementation maintained by the OpenTelemetry project (a CNCF graduated project, the same foundation behind Kubernetes).

**Key packages:**

| Package | Purpose | Size |
|---|---|---|
| `opentelemetry-api` | Tracer, Span, Context interfaces | ~100 KB |
| `opentelemetry-sdk` | TracerProvider, SpanProcessors, in-memory span storage | ~200 KB |

No additional OTel packages are needed. We do **not** use auto-instrumentation, OTLP exporters, or any contrib packages. The footprint is minimal.

---

## Trace Levels

OpenTelemetry spans do not have a built-in "level" or "importance" concept — every span is just a span. Harle adds a custom attribute `harle.level` to each span to express importance:

| Level | Name | When to use | Example |
|---|---|---|---|
| **1** | `STEP` | Major processing stages — the "chapter headings" of a run | "Routing to agent: secretary", "Context assembly complete" |
| **2** | `DETAIL` | Decisions, parameters, intermediate results | "Keyword 'trello' matched rule #3", "Token budget: 3420/4096 used" |
| **3** | `TRACE` | Fine-grained internals for deep debugging | "Whoosh query: 'trello AND stalled'", "HTTP 200 from api.trello.com in 142ms" |
| **4** | `INTERNAL` | Very low-level, rarely needed outside development | "Cache hit for tokenizer model cl100k_base", "Pydantic validation passed" |

**In the CLI**, the debug mode has a verbosity flag:
- `--debug` — shows `STEP` only (clean overview of what happened).
- `--debug=detail` (or `-dd`) — shows `STEP` + `DETAIL`.
- `--debug=trace` (or `-ddd`) — shows everything down to `TRACE`.
- `INTERNAL` is never shown in the CLI; it is only in the stored logs.

**In the vault and DB**, all levels are always stored.

Levels are stored as the span attribute `harle.level` (a string: `"STEP"`, `"DETAIL"`, `"TRACE"`, `"INTERNAL"`). Each exporter filters spans by level according to its configuration. The OTel SDK collects all spans regardless — filtering happens at export time, not at collection time. You never lose data because of a display setting.

---

## The `dtrace` API — How Subsystem Code Emits Entries

The `dtrace` module is a thin wrapper around the OpenTelemetry `Tracer`. It exists for two reasons: (1) to provide a clean, minimal API that is visually distinct in the codebase, and (2) to map Harle's trace levels to OTel span attributes automatically.

### Naming convention: `dtrace`

The module is called `dtrace` (short for "debug trace"). All calls in the codebase start with `dtrace.`:

```python
from harle.debug import dtrace
```

This prefix serves as a visual marker. When you read source code, every line starting with `dtrace.` is debug logging — not business logic. You can mentally skip it when reading for functionality, or focus on it when reading for observability.

### Core API

```python
# --- Span-based (hierarchical) ---

# Open a span (context manager for automatic close)
with dtrace.span("context_assembly", level=dtrace.STEP, module="context"):
    # ... do work ...
    dtrace.detail("Loaded 3 policy files", policies=["a.md", "b.md", "c.md"])
    dtrace.detail("Token budget: {used}/{total}", used=3420, total=4096)
    # span is closed automatically at the end of the `with` block

# --- Standalone entries (leaf spans, no nesting) ---

dtrace.step("Router selected agent: secretary", method="keyword_match")
dtrace.detail("Search returned 5 results", query="trello stalled", count=5)
dtrace.trace("HTTP response", status=200, duration_ms=142, url="https://api.trello.com/...")
dtrace.internal("Tokenizer cache hit", model="cl100k_base")
```

### What happens under the hood

Each `dtrace` function is a thin translation to OTel:

```python
from opentelemetry import trace

_tracer = trace.get_tracer("harle")

@contextmanager
def span(name: str, *, level: TraceLevel = STEP, module: str = "", **attrs):
    with _tracer.start_as_current_span(name) as otel_span:
        otel_span.set_attribute("harle.level", level.value)
        otel_span.set_attribute("harle.module", module)
        for k, v in attrs.items():
            otel_span.set_attribute(k, _serialize_attr(v))
        yield otel_span

def step(name: str, **attrs):
    _emit_leaf_span(name, level=STEP, **attrs)

def detail(name: str, **attrs):
    _emit_leaf_span(name, level=DETAIL, **attrs)

def _emit_leaf_span(name: str, *, level: TraceLevel, **attrs):
    with _tracer.start_as_current_span(name) as s:
        s.set_attribute("harle.level", level.value)
        for k, v in attrs.items():
            s.set_attribute(k, _serialize_attr(v))
```

**Key point:** `_tracer.start_as_current_span()` handles all the complexity:
- It creates a span with the correct parent (via OTel's internal context propagation).
- It is parallel-safe (`asyncio.gather` gives each branch its own context copy).
- It is thread-safe (OTel's SDK uses internal locking).
- When no `TracerProvider` is configured (e.g. in tests), it returns a `NoOpSpan` that does nothing.

The `dtrace` module adds exactly two things on top: the `harle.level` attribute and the `harle.module` attribute.

### How it looks in real code

Here is what an existing function looks like **before** and **after** adding debug logging. Notice how the debug lines are visually separate from the business logic:

**Before (orchestrator `service.py`):**

```python
async def handle_request(request: RunRequest) -> RunResult:
    agent_role = await route(request)
    context = await assemble_context(request, agent_role)
    result = await execute_agent(agent_role, context, request)
    await log_run(request, result)
    return result
```

**After:**

```python
async def handle_request(request: RunRequest) -> RunResult:
    with dtrace.span("handle_request", level=dtrace.STEP, module="orchestrator"):

        agent_role = await route(request)
        dtrace.step("Routed to agent", agent=agent_role, method="keyword_match")

        context = await assemble_context(request, agent_role)
        dtrace.step("Context assembled", tokens=context.total_tokens)

        result = await execute_agent(agent_role, context, request)
        dtrace.step("Agent execution complete", iterations=result.iterations)

        await log_run(request, result)

    return result
```

**Key observation:** the four lines of business logic (`route`, `assemble_context`, `execute_agent`, `log_run`) are unchanged. The `dtrace` calls are additions that do not alter control flow or return values. A developer can read the function by ignoring every `dtrace.` line and the behavior is identical.

### Decorator for automatic span wrapping

For functions that represent a single logical step, a decorator avoids the `with` boilerplate:

```python
@dtrace.span_fn(level=dtrace.STEP, module="orchestrator")
async def route(request: RunRequest) -> str:
    # span is opened automatically with name "route"
    # and closed when the function returns
    ...
```

Under the hood, this uses OTel's `@_tracer.start_as_current_span("route")` with the additional `harle.level` and `harle.module` attributes set automatically.

### No-op when tracing is not configured

If no `TracerProvider` is configured (e.g. during startup, in unit tests, or in scripts that import Harle modules), OTel's default `NoOpTracer` handles all calls silently — zero cost, zero side effects. Subsystem code does not need to check whether tracing is active before calling `dtrace`.

---

## Custom Exporters — Where Debug Data Goes

OpenTelemetry's export pipeline works as follows: when a span completes, the `SpanProcessor` passes it to one or more `SpanExporter` implementations. We write three custom exporters.

### How the export pipeline is wired

```python
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, BatchSpanProcessor

provider = TracerProvider()

# Vault and DB: batch for efficiency (flush when request completes)
provider.add_span_processor(BatchSpanProcessor(VaultExporter(vault_path)))
provider.add_span_processor(BatchSpanProcessor(PostgresExporter(db_engine)))

# CLI: simple (immediate) processor for real-time streaming
if debug_mode:
    provider.add_span_processor(SimpleSpanProcessor(CliSseExporter(sse_queue)))

trace.set_tracer_provider(provider)
```

- **`BatchSpanProcessor`** — accumulates spans and flushes them in batches. For vault and DB, this means the full trace is written once when the request completes.
- **`SimpleSpanProcessor`** — exports each span immediately when it closes. For the CLI, this enables real-time streaming of debug output as each step finishes.

### 1. Vault exporter (always active)

Receives completed spans, reconstructs the span tree, and writes a human-readable Markdown file to the vault alongside the Run Logger's output:

```
vault/
└── logs/
    └── 2026/
        └── 03/
            ├── run_abc123_result.md       ← Run Logger (existing)
            ├── run_abc123_context.md      ← Run Logger (existing, optional)
            └── run_abc123_debug.md        ← Debug trace (new)
```

**Example `run_abc123_debug.md`:**

```markdown
---
run_id: run_abc123
timestamp: 2026-03-12T14:23:01Z
total_spans: 14
duration_ms: 4200
---

# Debug Trace — run_abc123

## [STEP] handle_request (4200ms)

### [STEP] Routed to agent: secretary
- method: keyword_match
- confidence: high

### [STEP] Context assembly (320ms)
- [DETAIL] Search query: "trello stalled tasks"
- [DETAIL] Search returned 3 results
- [DETAIL] Loaded policies: tools-allowlist.md
- [DETAIL] Token budget: 3420 / 4096 (83%)
  - [TRACE] Whoosh query parsed in 2ms
  - [TRACE] Policy file read: 142 tokens

### [STEP] Agent execution (3800ms)
- [DETAIL] Model: gpt-4o-mini
- [DETAIL] Iteration 1: tool call
  - [STEP] Tool: trello_list_cards (340ms)
    - [DETAIL] Input: {"board": "Work"}
    - [DETAIL] Output: 23 cards returned
    - [TRACE] HTTP POST api.trello.com → 200 (285ms)
- [DETAIL] Iteration 2: final response
  - [TRACE] Response tokens: 482

### [STEP] Run logged to vault and DB
```

This file is Markdown: you can open it in any editor, in Obsidian (since the vault is an Obsidian vault), or read it in a terminal. The indentation and heading levels reflect the span hierarchy.

**Tree reconstruction:** OTel exports spans as a flat list (each span carries its `parent_span_id`). The vault exporter reconstructs the tree at write time by grouping spans by `parent_span_id` — the same approach any OTel backend uses. This is a few lines of code.

### 2. Database exporter (always active)

Serializes the span tree to JSON and stores it in PostgreSQL. This enables querying across runs:

```sql
CREATE TABLE debug_traces (
    id            SERIAL PRIMARY KEY,
    run_id        VARCHAR NOT NULL,
    trace_json    JSONB NOT NULL,
    total_spans   INTEGER NOT NULL DEFAULT 0,
    duration_ms   INTEGER,
    created_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT fk_debug_traces_run
        FOREIGN KEY (run_id) REFERENCES runs(run_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_debug_traces_run_id ON debug_traces(run_id);
CREATE INDEX idx_debug_traces_created ON debug_traces(created_at);
```

**Why JSONB, not normalized tables?**

The span tree is hierarchical and variable-depth. Normalizing it into relational tables (a `spans` table with `parent_id` foreign keys) would make writes more complex and reads slower for the common case (retrieving the full tree for a single run). JSONB stores the tree as-is and PostgreSQL can still query inside it:

```sql
-- Find all runs where web_search took longer than 5 seconds
SELECT run_id
FROM debug_traces
WHERE trace_json @? '$..children[*] ? (@.name == "web_search" && @.duration_ms > 5000)';
```

### 3. CLI SSE exporter (only when debug mode is active)

When the user launches Harle with debug mode, trace entries are streamed to the CLI **in real time** — not after the run completes. This means the user sees each step as it happens, interleaved with the streamed response.

**How it works:**

This exporter uses `SimpleSpanProcessor`, which calls `export()` immediately when each span closes. The exporter pushes the span data into the SSE event queue that the API already uses for response streaming:

```
event: token
data: {"text": "Found 7 stalled tasks"}

event: debug
data: {"level": "STEP", "name": "Tool: trello_list_cards", "duration_ms": 340}

event: token
data: {"text": ". Here are suggested reformulations..."}

event: debug
data: {"level": "DETAIL", "name": "Iteration 2: final response", "tokens": 482}
```

The CLI renders debug entries differently from response text — for example, dimmed color, a `[DEBUG]` prefix, or a collapsible panel (using Bubbletea's layout capabilities). The exact rendering is a CLI design decision, but the principle is: **debug output must never be confused with the actual response**.

**Level filtering:** The CLI exporter checks the `harle.level` attribute and drops spans below the user's verbosity threshold (e.g. in `--debug` mode, only `STEP` spans are emitted as SSE events).

**CLI activation:**

```bash
# Normal mode — no debug output shown
harle ask "Find stalled Trello tasks"

# Debug mode — show STEP-level entries
harle ask --debug "Find stalled Trello tasks"

# Verbose debug — show STEP + DETAIL
harle ask -dd "Find stalled Trello tasks"

# Full trace — show everything except INTERNAL
harle ask -ddd "Find stalled Trello tasks"
```

---

## Concurrency & Parallel Execution

Parallel execution safety is the primary reason for using OpenTelemetry instead of a custom solution.

OTel's Python SDK uses `contextvars` internally to track the current span. When `asyncio.create_task()` or `asyncio.gather()` forks a coroutine, Python automatically copies the context — each branch gets its own "current span" pointer while all branches share the same `TracerProvider` and span storage. This is the exact two-variable pattern (shared storage + per-branch nesting) that a custom solution would need to implement manually.

**All scenarios are handled:**

| Execution model | Works? | How OTel handles it |
|---|---|---|
| Sequential (normal) | Yes | Single coroutine, no contention |
| `asyncio.gather` / `create_task` | Yes | `contextvars` copied per branch — each branch tracks its own parent span independently |
| `asyncio.to_thread` | Yes | OTel copies context to threads; span storage is thread-safe |
| Raw `threading.Thread` | Yes | Use `opentelemetry.context.attach()` to propagate context explicitly |

**Example: parallel tool calls**

```python
async def execute_iteration(tools_to_call: list[ToolCall]):
    with dtrace.span("iteration_1", level=dtrace.DETAIL, module="orchestrator"):
        results = await asyncio.gather(
            execute_tool(tools_to_call[0]),   # gets its own context copy
            execute_tool(tools_to_call[1]),   # gets its own context copy
        )
```

Each `execute_tool` call opens spans that are correctly parented under `"iteration_1"`. Neither branch interferes with the other's nesting. The resulting trace tree shows both tools as siblings — exactly as expected.

---

## Integration Points — How Each Subsystem Uses Debug Logging

Debug logging is a **cross-cutting concern**. Every subsystem adds its own entries. The table below shows what each subsystem logs and at which level:

| Subsystem | STEP entries | DETAIL entries | TRACE entries |
|---|---|---|---|
| **HTTP API** | Request received, response sent | Request validation result | Raw request headers |
| **Router** | Agent selected, routing method used | Each rule evaluated, match/no-match | LLM fallback prompt and response |
| **Clarifier** | Clarification needed / not needed | Questions generated | LLM prompt for ambiguity check |
| **Context Assembler** | Assembly complete, total tokens | Each priority tier loaded, items included/excluded, budget status | Individual file token counts, search scores |
| **Agent Runner** | Execution started/completed, iteration count | Each iteration (tool call or final), model used | Full tool call input/output, LLM token usage per call |
| **Tool modules** | Tool invoked, tool completed | Input parameters, output summary, duration | HTTP requests/responses, retries, error details |
| **Search** | Search executed, result count | Query text, scoring method | Raw Whoosh/pgvector query, per-result scores |
| **Capture module** | Capture triggered | Source type, vault path written | File content size, frontmatter parsed |
| **Connections** | Connection established / failed | Service name, auth method | Connection pool stats, retry attempts |
| **Run Logger** | Run logged to vault and DB | File paths written | Write duration, byte sizes |

**Future subsystems** follow the same pattern: import `dtrace`, call `dtrace.step()` / `dtrace.detail()` / `dtrace.trace()` with a `module` parameter. No registration, no configuration, no changes to other modules.

---

## Relationship to Existing Logging

Debug logging (`dtrace`) and Python standard logging (`logging`) serve **different purposes** and **coexist**:

| Aspect | Standard `logging` | Debug `dtrace` |
|---|---|---|
| **Audience** | Developer / ops (server logs) | End user + developer (run traces) |
| **Scope** | Application-wide, always on | Per-request, always captured |
| **Structure** | Flat text lines with timestamp | Hierarchical span tree |
| **Storage** | stdout / log files (server-side) | DB + vault (per-run files) |
| **Visibility** | Server console | CLI (when debug mode active) |
| **Purpose** | Diagnose crashes, config issues, startup | Understand request processing, transparency |

**Rule of thumb:**
- If it matters for **server health** (connection errors, startup failures, config problems) → use `logger.warning()` / `logger.error()`.
- If it matters for **understanding what happened during a user's request** → use `dtrace.step()` / `dtrace.detail()` / `dtrace.trace()`.
- Some events may be logged to both (e.g. a tool failure is both a `logger.error` for ops and a `dtrace.step` with error status for the user's trace).

---

## Configuration

### TracerProvider setup (application startup)

The `TracerProvider` is configured once at application startup (`main.py` or `bootstrap.py`):

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor

from harle.debug.exporters import VaultExporter, PostgresExporter, CliSseExporter

def configure_tracing(config: HarleConfig, debug_mode: bool, sse_queue=None):
    provider = TracerProvider()

    if config.debug.vault_sink_enabled:
        provider.add_span_processor(
            BatchSpanProcessor(VaultExporter(config.dataset.path))
        )

    if config.debug.db_sink_enabled:
        provider.add_span_processor(
            BatchSpanProcessor(PostgresExporter(config.indexer.database_url))
        )

    if debug_mode and sse_queue is not None:
        provider.add_span_processor(
            SimpleSpanProcessor(CliSseExporter(sse_queue, min_level=config.debug.cli_level))
        )

    trace.set_tracer_provider(provider)
```

### Config file additions

Debug logging adds the following to `config.yaml`:

```yaml
debug:
  # Whether debug traces are written to the vault logs/ directory.
  # Default: true. Set to false only if vault disk space is a concern.
  vault_sink_enabled: true

  # Whether debug traces are written to PostgreSQL.
  # Default: true. Set to false if DB storage is limited.
  db_sink_enabled: true

  # Minimum level stored in vault and DB.
  # Even if the CLI shows only STEP, the sinks store down to this level.
  # Options: STEP, DETAIL, TRACE, INTERNAL
  # Default: TRACE (store everything except INTERNAL)
  min_storage_level: "TRACE"
```

The CLI flag (`--debug`, `-dd`, `-ddd`) controls **display** level. The config controls **storage** level. They are independent.

---

## Best Practices Applied

### 1. Structured logging (not string formatting)

Trace entries use key-value attributes (OTel span attributes), not formatted strings:

```python
# Good — structured, queryable
dtrace.detail("Search completed", query="trello stalled", count=5, duration_ms=42)

# Bad — formatted string, hard to parse
dtrace.detail(f"Search for 'trello stalled' returned 5 results in 42ms")
```

Structured data can be queried in PostgreSQL (`trace_json @> '{"query": "trello"}'`), filtered in the CLI, and formatted differently per exporter.

### 2. Industry-standard tracing foundation

By using OpenTelemetry directly rather than reimplementing its concepts, Harle gets:
- **Battle-tested concurrency safety** — span context propagation across async tasks and threads.
- **Ecosystem compatibility** — if Harle ever needs external observability (Jaeger, Grafana Tempo, Datadog), adding an OTLP exporter is a one-line change.
- **Maintained by the community** — security patches, performance improvements, and new features arrive via package updates, not custom maintenance.

### 3. Separation of collection and output

OTel enforces this architecturally: the `Tracer` creates spans, `SpanProcessor` decides when to flush, and `SpanExporter` decides where to write. These three concerns cannot be tangled because they are separate interfaces.

### 4. Levels as filters, not gates

All spans are collected by OTel regardless of their `harle.level` attribute. Levels are used for **filtering at export time** — each exporter independently decides which levels to include. The vault and DB exporters store everything; the CLI exporter filters by the user's verbosity flag. You never lose data because of a display setting.

---

## Project Structure

```
src/harle/debug/                     ← New package
├── __init__.py                      # Public API: from harle.debug import dtrace
├── trace.py                         # dtrace module: span(), step(), detail(), trace(), internal()
│                                    #   Thin wrapper over opentelemetry.trace.get_tracer("harle")
├── levels.py                        # TraceLevel enum (STEP, DETAIL, TRACE, INTERNAL)
├── setup.py                         # configure_tracing(): TracerProvider + processor wiring
└── exporters/
    ├── __init__.py
    ├── vault.py                     # VaultExporter(SpanExporter): span tree → Markdown → vault logs/
    ├── db.py                        # PostgresExporter(SpanExporter): span tree → JSON → debug_traces table
    └── cli.py                       # CliSseExporter(SpanExporter): span → SSE event for CLI streaming

src/harle/db/
└── models.py                        # Add DebugTrace SQLAlchemy model

src/harle/api/
└── routes.py                        # Start root span per request; pass debug_mode to SSE

harle-cli/
└── (Go source)                      # Add --debug flag, render debug SSE events
```

Each exporter is ~50–100 lines. The `dtrace` module is ~30 lines. The setup function is ~20 lines. Total Harle-specific code: **~250–350 lines** (compared to ~600–800 for the previous from-scratch approach).

### Database migration

A new table `debug_traces` is added:

```sql
CREATE TABLE debug_traces (
    id            SERIAL PRIMARY KEY,
    run_id        VARCHAR NOT NULL,
    trace_json    JSONB NOT NULL,
    total_spans   INTEGER NOT NULL DEFAULT 0,
    duration_ms   INTEGER,
    created_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT fk_debug_traces_run
        FOREIGN KEY (run_id) REFERENCES runs(run_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_debug_traces_run_id ON debug_traces(run_id);
CREATE INDEX idx_debug_traces_created ON debug_traces(created_at);
```

### Dependencies

| Package | Purpose |
|---|---|
| `opentelemetry-api` | Tracer, Span, Context interfaces |
| `opentelemetry-sdk` | TracerProvider, SpanProcessors, in-process span storage |

No other OTel packages are needed. Auto-instrumentation and OTLP exporters are not used in the initial implementation.

---

## Examples: Full Traces

### Example 1: Sequential request

A complete trace for the request *"Find stalled tasks in Trello"*:

```
[STEP] handle_request (4200ms) — orchestrator
├── [STEP] Routed to agent: secretary — orchestrator
│   ├── [DETAIL] Rule #3 matched keyword "trello" — orchestrator
│   └── [DETAIL] Method: keyword_match, confidence: high — orchestrator
├── [STEP] Clarification: not needed — orchestrator
│   └── [TRACE] LLM check skipped (keyword match is high confidence) — orchestrator
├── [STEP] Context assembly complete (320ms) — context
│   ├── [DETAIL] P0: agent prompt loaded (secretary.md, 840 tokens) — context
│   ├── [DETAIL] P0: policy loaded (tools-allowlist.md, 220 tokens) — context
│   ├── [DETAIL] P1: search returned 3 results — context
│   │   ├── [TRACE] Whoosh query: "trello stalled tasks" — search
│   │   ├── [TRACE] Result: workflows/task-triage.md (score 4.2) — search
│   │   ├── [TRACE] Result: logs/2026/02/run_prev01_result.md (score 2.1) — search
│   │   └── [TRACE] Result: notes/trello-boards.md (score 1.8) — search
│   ├── [DETAIL] P3: 1 prior run referenced — context
│   └── [DETAIL] Token budget: 3420 / 4096 (83%) — context
├── [STEP] Agent execution started — orchestrator
│   ├── [DETAIL] Model: gpt-4o-mini — orchestrator
│   ├── [DETAIL] Iteration 1: tool call — orchestrator
│   │   └── [STEP] Tool: trello_list_cards (340ms) — tools.trello
│   │       ├── [DETAIL] Input: {board: "Work"} — tools.trello
│   │       ├── [DETAIL] Output: 23 cards returned — tools.trello
│   │       └── [TRACE] HTTP GET api.trello.com/1/boards/.../cards → 200 (285ms) — tools.trello
│   ├── [DETAIL] Iteration 2: final response — orchestrator
│   │   └── [TRACE] Response: 482 tokens, finish_reason: stop — orchestrator
│   └── [STEP] Agent execution complete (3800ms, 2 iterations) — orchestrator
└── [STEP] Run logged — orchestrator
    ├── [DETAIL] Vault: logs/2026/03/run_abc123_result.md — logging
    └── [DETAIL] DB: runs table updated — logging
```

### Example 2: Parallel execution (concurrent tool calls + agent branches)

A trace for *"Research privacy solutions and create a Trello card with the findings"*, where the agent calls two tools in parallel and later hands off to a second agent:

```
[STEP] handle_request (8900ms) — orchestrator
├── [STEP] Routed to agent: secretary — orchestrator
├── [STEP] Context assembly complete (280ms) — context
├── [STEP] Agent execution started — orchestrator
│   ├── [DETAIL] Model: gpt-4o — orchestrator
│   ├── [DETAIL] Iteration 1: parallel tool calls — orchestrator
│   │   ├── [STEP] Tool: web_search (1200ms) — tools.web_search      ← Branch A
│   │   │   ├── [DETAIL] Query: "GDPR privacy solutions 2026" — tools.web_search
│   │   │   ├── [DETAIL] Output: 8 results — tools.web_search
│   │   │   ├── [TRACE] HTTP GET serpapi.com → 200 (850ms) — tools.web_search
│   │   │   └── [TRACE] HTTP GET serpapi.com → 200 (320ms) — tools.web_search
│   │   └── [STEP] Tool: vault_search (90ms) — tools.vault            ← Branch B
│   │       ├── [DETAIL] Query: "privacy policy" — tools.vault
│   │       └── [DETAIL] Output: 2 vault files matched — tools.vault
│   ├── [DETAIL] Iteration 2: handoff to researcher — orchestrator
│   │   └── [STEP] Handoff: secretary → researcher — orchestrator
│   │       └── [STEP] Agent execution (researcher) (5200ms) — orchestrator
│   │           ├── [DETAIL] Model: gpt-4o — orchestrator
│   │           ├── [DETAIL] Iteration 1: analysis — orchestrator
│   │           │   └── [TRACE] Response: 1840 tokens — orchestrator
│   │           └── [STEP] Agent execution complete (5200ms) — orchestrator
│   ├── [DETAIL] Iteration 3: tool call — orchestrator
│   │   └── [STEP] Tool: trello_create_card (420ms) — tools.trello
│   │       ├── [DETAIL] Board: "Work", list: "Research" — tools.trello
│   │       ├── [DETAIL] Approval: requested → approved — tools.trello
│   │       └── [TRACE] HTTP POST api.trello.com → 200 (380ms) — tools.trello
│   ├── [DETAIL] Iteration 4: final response — orchestrator
│   └── [STEP] Agent execution complete (8500ms, 4 iterations) — orchestrator
└── [STEP] Run logged — orchestrator
```

Note how `web_search` and `vault_search` appear as siblings under "Iteration 1" — they ran concurrently via `asyncio.gather`, but OTel's context propagation correctly parents both under the same iteration span. Each branch tracked its own nesting independently via its own `contextvars` copy.

---

## Implementation Plan

The system is implemented incrementally. Each phase is independently useful.

### Phase 1: Core infrastructure + vault exporter

- Add `opentelemetry-api` and `opentelemetry-sdk` to dependencies.
- Create `src/harle/debug/` package: `trace.py` (dtrace API), `levels.py`, `setup.py`.
- Implement `VaultExporter` (span tree → Markdown → vault `logs/` directory).
- Wire `configure_tracing()` into application startup (`bootstrap.py`).
- Add root span creation in the orchestrator request lifecycle.

**Result:** Every run produces a `_debug.md` file in the vault. No CLI changes yet.

### Phase 2: Database exporter and CLI streaming

- `debug_traces` PostgreSQL table and SQLAlchemy model (migration).
- Implement `PostgresExporter` (span tree → JSON → DB).
- Implement `CliSseExporter` (span → SSE event, with level filtering).
- SSE `debug` event type in the API routes.
- CLI `--debug` flag and debug event rendering.

**Result:** Debug traces are queryable in the DB. Users can see live debug output in the CLI.

### Phase 3: Subsystem instrumentation

- Add `dtrace` calls to all existing subsystems (router, context assembler, agent runner, tools, search, capture, run logger).
- Establish conventions for module-specific trace entries (documented in the integration points table above).

**Result:** Full observability across the entire request pipeline.

### Phase 4: Query, analysis, and external export

- API endpoint to retrieve debug traces by run ID.
- CLI command to view past traces: `harle debug run_abc123`.
- Specialist agent integration: the Specialist can analyze debug traces to identify performance bottlenecks and error patterns.
- (Optional) Add `opentelemetry-exporter-otlp` for external observability platforms — a one-line addition.

**Result:** Debug data becomes actionable for system self-improvement, and external observability is available if needed.
