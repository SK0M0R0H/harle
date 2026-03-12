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

**Phase 1 is implemented.** The core debug logging infrastructure exists: the `dtrace` API (`src/harle/debug/trace.py`), trace levels (`levels.py`), TracerProvider setup (`setup.py`), and the vault exporter (`exporters/vault.py`). The orchestrator's `run()` and `chat()` methods are wrapped in root spans with `dtrace.step()` calls for context assembly and agent execution. Every run produces a `_debug.md` file in the vault. Phase 2 (DB exporter, CLI SSE exporter), Phase 3 (subsystem instrumentation), and Phase 4 (query/analysis) are not yet implemented.

---

## Implementation Snapshot

| TRD area | Current status | Notes |
|----------|----------------|-------|
| `dtrace` API (`trace.py`) | Implemented | `span()`, `step()`, `detail()`, `trace_entry()`, `internal()`, `span_fn()` decorator. Uses OTel `get_tracer("harle")`. |
| `TraceLevel` enum (`levels.py`) | Implemented | STEP=1, DETAIL=2, TRACE=3, INTERNAL=4 with `from_name()`. |
| `configure_tracing()` (`setup.py`) | Implemented | Creates `TracerProvider`, wires vault `BatchSpanProcessor`. |
| `VaultExporter` (`exporters/vault.py`) | Implemented | Reconstructs span tree, renders Markdown, writes `_debug.md` to vault `logs/YYYY/MM/`. |
| Config fields | Implemented | `HARLE_DEBUG_VAULT_ENABLED`, `HARLE_DEBUG_DB_ENABLED`, `HARLE_DEBUG_MIN_STORAGE_LEVEL` in `Settings`. |
| Startup wiring (`main.py`) | Implemented | `configure_tracing()` called in `create_app()` before other setup. |
| Root spans in orchestrator | Implemented | `run()` and `chat()` wrapped in `handle_request` / `handle_chat` root spans with `run_id` attribute. |
| `PostgresExporter` | Not implemented | Phase 2. |
| `CliSseExporter` | Not implemented | Phase 2. |
| `debug_traces` DB table / model | Not implemented | Phase 2. |
| SSE `debug` event type in API | Not implemented | Phase 2. |
| CLI `--debug` flag | Not implemented | Phase 2 (Go CLI). |
| Subsystem instrumentation (router, context assembler, agent runner, tools, search, capture, run logger) | Not implemented | Phase 3. Orchestrator has root spans + basic step entries only. |
| API endpoint for trace retrieval | Not implemented | Phase 4. |
| CLI `harle debug <run_id>` command | Not implemented | Phase 4. |
| Specialist agent trace analysis | Not implemented | Phase 4. |
| OTLP external exporter | Not implemented | Phase 4 (optional). |

---

## What Is Implemented

### Core infrastructure (`src/harle/debug/`)

- **`levels.py`** — `TraceLevel` enum with STEP, DETAIL, TRACE, INTERNAL values and `from_name()` class method for case-insensitive lookup.
- **`trace.py`** — The `dtrace` API module providing `span()` context manager, `step()`, `detail()`, `trace_entry()`, `internal()` leaf-span emitters, and `span_fn()` decorator. All functions set `harle.level` and `harle.module` attributes. Uses `_serialize_attr()` to coerce non-primitive values to JSON strings.
- **`setup.py`** — `configure_tracing()` creates a `TracerProvider` and conditionally adds a `BatchSpanProcessor(VaultExporter(...))` based on config. Sets the global tracer provider.
- **`__init__.py`** — Exports `dtrace`, `TraceLevel`, and `configure_tracing`.

### Vault exporter (`src/harle/debug/exporters/vault.py`)

- Groups spans by trace ID, filters by `min_level`, reconstructs the parent-child tree from `parent_span_id`, and renders a Markdown document with YAML frontmatter.
- Writes to `logs/YYYY/MM/<run_id>_debug.md` alongside existing Run Logger output.
- Tree rendering uses heading levels for depth 0–1 and bullet indentation for deeper spans.

### Orchestrator instrumentation

- `OrchestratorService.run()` — root span `handle_request` with `run_id`; step entries for context assembly and agent execution.
- `OrchestratorService.chat()` — root span `handle_chat` with `run_id`; step entries for context assembly and agent execution.

### Configuration

- Three new `Settings` fields: `HARLE_DEBUG_VAULT_ENABLED` (default `True`), `HARLE_DEBUG_DB_ENABLED` (default `True`), `HARLE_DEBUG_MIN_STORAGE_LEVEL` (default `"TRACE"`).
- Corresponding entries in `config.yaml`.

### Dependencies

- `opentelemetry-api>=1.20.0` and `opentelemetry-sdk>=1.20.0` added to `pyproject.toml`.

---

## What Is Only Partially Implemented

### Orchestrator trace depth

The orchestrator emits root spans and a few STEP-level entries (context assembled, agent execution complete, run logged). The TRD's full orchestrator instrumentation (routing decision, clarifier check, each agent iteration, model selection) is not yet present — that is Phase 3 work.

---

## What Is Not Implemented Yet

### 1. Database exporter (Phase 2)

- **Missing:** `PostgresExporter` (`exporters/db.py`), `debug_traces` table, SQLAlchemy `DebugTrace` model, Alembic migration.
- **Unlocks:** Queryable traces across runs; ability to find all runs where a specific tool was slow or a specific error occurred.

### 2. CLI SSE exporter (Phase 2)

- **Missing:** `CliSseExporter` (`exporters/cli.py`), SSE `debug` event type in API routes, CLI `--debug` / `-dd` / `-ddd` flags (Go CLI).
- **Unlocks:** Real-time debug output in the terminal as spans close, interleaved with streamed response text.

### 3. Subsystem instrumentation (Phase 3)

- **Missing:** `dtrace` calls in router, context assembler, agent runner, tool modules, search engine, capture module, connections, and run logger.
- **Unlocks:** Full observability across the entire request pipeline — every decision, intermediate value, and branch taken.

### 4. Query, analysis, and external export (Phase 4)

- **Missing:** API endpoint to retrieve debug traces by run ID, CLI `harle debug <run_id>` command, Specialist agent analysis of traces, optional OTLP exporter.
- **Unlocks:** Post-hoc analysis, performance bottleneck identification, and integration with external observability platforms.

---

## Key Deviations from TRD

1. **`trace_entry()` instead of `trace()`** — The TRD shows `dtrace.trace()` but the implementation uses `dtrace.trace_entry()` to avoid shadowing the `opentelemetry.trace` module and the Python `trace` builtin. The functionality is identical.

---

## Assessment

Phase 1 delivers the foundational infrastructure. The `dtrace` API, OTel integration, and vault exporter are production-ready. The main gap is breadth of instrumentation (only the orchestrator root spans are instrumented) and the missing DB/CLI output channels — both addressed by Phases 2 and 3.
