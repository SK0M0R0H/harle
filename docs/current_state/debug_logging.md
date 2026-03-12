---
title: "Harle Debug Logging — Current State"
tags: [debug, logging, tracing, observability, opentelemetry, current-state, implementation-status]
context: global
last_updated: 2026-03-12
summary: "Tracks what the debug logging system implements vs the TRD, and what each missing part would unlock."
---

# Harle Debug Logging — Current State

> This document compares the target design in the Debug Logging TRD with the codebase. It describes what is implemented, what is partial, and what is missing, and what each missing part would unlock.

Reference TRD: [Harle Debug Logging — Architecture & Functionality](../trd/debug_logging.md).

---

## Overall Status

**Phases 1, 2, and 3 are implemented.** The core debug logging infrastructure exists: the `dtrace` API, trace levels, TracerProvider setup, vault exporter, database exporter, and CLI SSE exporter. The orchestrator, context assembler, search engine, run logger, and tool registry are instrumented with STEP/DETAIL/TRACE entries so that each run produces a full hierarchical trace across the request pipeline. Phase 4 (query/analysis, API endpoint, CLI command) is not yet implemented.

---

## Implementation Snapshot

| TRD area | Current status | Notes |
|----------|----------------|-------|
| `dtrace` API (`trace.py`) | Implemented | `span()`, `step()`, `detail()`, `trace_entry()`, `internal()`, `span_fn()` decorator. Uses OTel `get_tracer("harle")`. |
| `TraceLevel` enum (`levels.py`) | Implemented | STEP=1, DETAIL=2, TRACE=3, INTERNAL=4 with `from_name()`. |
| `configure_tracing()` (`setup.py`) | Implemented | Creates `TracerProvider`, wires vault, DB, and CLI SSE exporters based on config. |
| `VaultExporter` (`exporters/vault.py`) | Implemented | Reconstructs span tree, renders Markdown, writes `_debug.md` to vault `logs/YYYY/MM/`. |
| `PostgresExporter` (`exporters/db.py`) | Implemented | Serialises span tree to JSONB, inserts into `debug_traces` table. Uses lazy engine creation. |
| `CliSseExporter` (`exporters/cli.py`) | Implemented | Pushes qualifying spans to a shared `Queue` for SSE streaming. Level-filtered. |
| `DebugTrace` model (`db/models.py`) | Implemented | SQLAlchemy model with `run_id`, `trace_json` (JSONB), `total_spans`, `duration_ms`, `created_at`. |
| `debug_traces` CRUD (`db/debug_traces.py`) | Implemented | `create_debug_trace()` and `get_debug_trace()` helpers. |
| SSE `debug` event type in API | Implemented | `/run` and `/chat` accept `?debug=true` and return `EventSourceResponse` with `event: debug` and `event: result` events. |
| Shared span helpers (`exporters/_spans.py`) | Implemented | Extracted from vault exporter: `group_by_trace`, `filter_by_level`, `find_root`, `extract_run_id`, `span_start_time`, `span_duration_ms`, `build_tree`. |
| Debug queue (`debug/queue.py`) | Implemented | `init_debug_queue()` / `get_debug_queue()` for shared SSE event queue. |
| SSE streaming helpers (`api/streaming.py`) | Implemented | `drain_debug_events()` and `result_event()`. |
| Config fields | Implemented | `HARLE_DEBUG_VAULT_ENABLED`, `HARLE_DEBUG_DB_ENABLED`, `HARLE_DEBUG_MIN_STORAGE_LEVEL` in `Settings`. |
| Startup wiring (`main.py`) | Implemented | `configure_tracing()` called with vault, DB, and optional SSE queue parameters. |
| Root spans in orchestrator | Implemented | `run()` and `chat()` wrapped in root spans with `run_id` attribute. |
| CLI `--debug` flag | Not implemented | Go CLI work. The API-side SSE support is ready. |
| Subsystem instrumentation (Phase 3) | Implemented | Router (routed to agent), context assembler (P0/P1/P4, budget), search (query, result count, scores), run logger (paths written), tools (Tool: name span + invoked/completed). |
| API endpoint for trace retrieval | Not implemented | Phase 4. |
| CLI `harle debug <run_id>` command | Not implemented | Phase 4. |
| Specialist agent trace analysis | Not implemented | Phase 4. |
| OTLP external exporter | Not implemented | Phase 4 (optional). |

---

## What Is Implemented

### Core infrastructure (`src/harle/debug/`)

- **`levels.py`** — `TraceLevel` enum with STEP, DETAIL, TRACE, INTERNAL values and `from_name()` class method for case-insensitive lookup.
- **`trace.py`** — The `dtrace` API module providing `span()` context manager, `step()`, `detail()`, `trace_entry()`, `internal()` leaf-span emitters, and `span_fn()` decorator. All functions set `harle.level` and `harle.module` attributes. Uses `_serialize_attr()` to coerce non-primitive values to JSON strings.
- **`setup.py`** — `configure_tracing()` creates a `TracerProvider` and conditionally adds processors for vault (`BatchSpanProcessor`), DB (`BatchSpanProcessor`), and CLI SSE (`SimpleSpanProcessor`) exporters. Sets the global tracer provider.
- **`queue.py`** — Shared debug event queue module with `init_debug_queue()` and `get_debug_queue()`.
- **`__init__.py`** — Exports `dtrace`, `TraceLevel`, and `configure_tracing`.

### Exporters (`src/harle/debug/exporters/`)

- **`_spans.py`** — Shared span-processing helpers used by both vault and DB exporters: `group_by_trace`, `filter_by_level`, `find_root`, `extract_run_id`, `span_start_time`, `span_duration_ms`, `build_tree`.
- **`vault.py`** — Groups spans by trace ID, filters by `min_level`, reconstructs the parent-child tree, and renders a Markdown document with YAML frontmatter. Writes to `logs/YYYY/MM/<run_id>_debug.md`.
- **`db.py`** — `PostgresExporter` serialises the span tree to JSONB and inserts one row per trace into `debug_traces`. Uses lazy engine creation to avoid importing SQLAlchemy at module level.
- **`cli.py`** — `CliSseExporter` pushes debug events onto a shared `Queue`. Each event is a dict with `type`, `level`, `name`, `duration_ms`, `module`, and optional `attributes`. Level filtering drops spans below the configured verbosity.

### Database layer

- **`db/models.py`** — `DebugTrace` model with `id`, `run_id` (indexed), `trace_json` (JSONB), `total_spans`, `duration_ms`, `created_at`.
- **`db/debug_traces.py`** — `create_debug_trace()` and `get_debug_trace()` CRUD helpers.

### API SSE support

- **`api/streaming.py`** — `drain_debug_events()` yields queued debug events as SSE-formatted dicts; `result_event()` wraps a `RunResponse` as an SSE `result` event.
- **`api/routes.py`** — `/run` and `/chat` accept `?debug=true` query parameter. When set, the response is an `EventSourceResponse` with `event: debug` events followed by `event: result`.

### Orchestrator instrumentation

- `OrchestratorService.run()` — root span `handle_request` with `run_id`; STEP "Routed to agent" (agent, routing_method); context assembly; STEP "Context assembled"; DETAIL "Agent execution started" (model, max_turns, has_tools); agent execution; STEP "Agent execution complete"; STEP "Run logged".
- `OrchestratorService.chat()` — same pattern with root span `handle_chat`; conversation load/create; context assembly; execution; message persist; run persist; STEP "Run logged".

### Subsystem instrumentation (Phase 3)

- **Context assembler** (`context/assembler.py`) — DETAIL "P0 loaded" (files, tokens), "P1 loaded" (results_included, tokens), TRACE "Search result included" (file_path, score) for first 5, DETAIL "P4 loaded" (messages_included, tokens), STEP "Context assembly complete" (total_tokens, budget_remaining), DETAIL "Budget status" (total_used, budget, remaining).
- **Search engine** (`search/engine.py`) — DETAIL "Search query" (query, context, max_results); DETAIL "Search skipped" when empty query; TRACE "Search result score" (file_path, score) for first 5; STEP "Search executed" (result_count, scoring).
- **Run logger** (`logging/run_logger.py`) — STEP "Run logged to vault" (result_path), DETAIL "File paths written", DETAIL "Context file written" when store_context.
- **Tool registry** (`tools/registry.py`) — each registered tool is wrapped with a span "Tool: {name}" (STEP, module=module_name); DETAIL "Tool invoked" and "Tool completed" per invocation. Supports both sync and async tools.

### Configuration

- Three `Settings` fields: `HARLE_DEBUG_VAULT_ENABLED` (default `True`), `HARLE_DEBUG_DB_ENABLED` (default `True`), `HARLE_DEBUG_MIN_STORAGE_LEVEL` (default `"TRACE"`).
- Corresponding entries in `config.yaml`.

### Dependencies

- `opentelemetry-api>=1.20.0`, `opentelemetry-sdk>=1.20.0`, and `sse-starlette>=2.0.0` in `pyproject.toml`.

---

## What Is Only Partially Implemented

### Agent runner iteration-level detail

The orchestrator emits "Agent execution started" (model, max_turns, has_tools) and "Agent execution complete" (tools_called, turns_used). Per-iteration DETAIL (each tool call or final response within the agentic loop) is not emitted because the Agents SDK Runner does not expose hooks for each turn; tool invocations are traced via the tool registry wrapper instead.

### CLI `--debug` flag

The API-side SSE support is ready (`?debug=true` returns an `EventSourceResponse`), but the Go CLI does not yet pass the `--debug` flag or render debug events. This is a CLI-side change.

### Database migration

The `DebugTrace` model exists in `db/models.py` and the table is created via `Base.metadata.create_all()`. No Alembic migration script has been generated yet.

---

## What Is Not Implemented Yet

### 1. Query, analysis, and external export (Phase 4)

- **Missing:** API endpoint to retrieve debug traces by run ID, CLI `harle debug <run_id>` command, Specialist agent analysis of traces, optional OTLP exporter.
- **Unlocks:** Post-hoc analysis, performance bottleneck identification, and integration with external observability platforms.

---

## Key Deviations from TRD

1. **`trace_entry()` instead of `trace()`** — The TRD shows `dtrace.trace()` but the implementation uses `dtrace.trace_entry()` to avoid shadowing the `opentelemetry.trace` module and the Python `trace` builtin. The functionality is identical.

---

## Assessment

Phases 1–3 deliver the full debug logging pipeline: three output channels (vault, DB, CLI SSE) and instrumentation across the orchestrator, context assembler, search engine, run logger, and tool registry. Traces now capture routing, context tiers and budget, search query and results, vault write paths, and each tool invocation. The remaining work is Phase 4 (query API, CLI command, specialist analysis, optional OTLP).
