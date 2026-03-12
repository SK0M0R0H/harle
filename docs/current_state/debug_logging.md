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

**Phases 1 and 2 are implemented.** The core debug logging infrastructure exists: the `dtrace` API, trace levels, TracerProvider setup, vault exporter, database exporter, and CLI SSE exporter. The orchestrator's `run()` and `chat()` methods are wrapped in root spans. Debug traces are written to vault Markdown files, stored as JSONB in PostgreSQL, and can be streamed to the CLI via SSE when debug mode is active. Phase 3 (subsystem instrumentation) and Phase 4 (query/analysis) are not yet implemented.

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
| Subsystem instrumentation | Not implemented | Phase 3. Orchestrator has root spans + basic step entries only. |
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

- `OrchestratorService.run()` — root span `handle_request` with `run_id`; step entries for context assembly and agent execution.
- `OrchestratorService.chat()` — root span `handle_chat` with `run_id`; step entries for context assembly and agent execution.

### Configuration

- Three `Settings` fields: `HARLE_DEBUG_VAULT_ENABLED` (default `True`), `HARLE_DEBUG_DB_ENABLED` (default `True`), `HARLE_DEBUG_MIN_STORAGE_LEVEL` (default `"TRACE"`).
- Corresponding entries in `config.yaml`.

### Dependencies

- `opentelemetry-api>=1.20.0`, `opentelemetry-sdk>=1.20.0`, and `sse-starlette>=2.0.0` in `pyproject.toml`.

---

## What Is Only Partially Implemented

### Orchestrator trace depth

The orchestrator emits root spans and a few STEP-level entries (context assembled, agent execution complete, run logged). The TRD's full orchestrator instrumentation (routing decision, clarifier check, each agent iteration, model selection) is not yet present — that is Phase 3 work.

### CLI `--debug` flag

The API-side SSE support is ready (`?debug=true` returns an `EventSourceResponse`), but the Go CLI does not yet pass the `--debug` flag or render debug events. This is a CLI-side change.

### Database migration

The `DebugTrace` model exists in `db/models.py` and the table is created via `Base.metadata.create_all()`. No Alembic migration script has been generated yet.

---

## What Is Not Implemented Yet

### 1. Subsystem instrumentation (Phase 3)

- **Missing:** `dtrace` calls in router, context assembler, agent runner, tool modules, search engine, capture module, connections, and run logger.
- **Unlocks:** Full observability across the entire request pipeline — every decision, intermediate value, and branch taken.

### 2. Query, analysis, and external export (Phase 4)

- **Missing:** API endpoint to retrieve debug traces by run ID, CLI `harle debug <run_id>` command, Specialist agent analysis of traces, optional OTLP exporter.
- **Unlocks:** Post-hoc analysis, performance bottleneck identification, and integration with external observability platforms.

---

## Key Deviations from TRD

1. **`trace_entry()` instead of `trace()`** — The TRD shows `dtrace.trace()` but the implementation uses `dtrace.trace_entry()` to avoid shadowing the `opentelemetry.trace` module and the Python `trace` builtin. The functionality is identical.

---

## Assessment

Phases 1 and 2 deliver the complete debug logging pipeline with three output channels (vault Markdown, PostgreSQL JSONB, and CLI SSE). The `dtrace` API, OTel integration, and all three exporters are production-ready. The main gap is breadth of instrumentation (only the orchestrator root spans are instrumented) — addressed by Phase 3.
