---
title: "Dynamic LLM Model Switching — Current State"
tags: [orchestrator, model-routing, current-state, architecture, implementation-status]
context: global
last_updated: 2026-03-21
summary: "Tracks what the Dynamic Model Switching TRD implements vs the code that exists today."
---

# Dynamic LLM Model Switching — Current State

> This document compares the target design in the Dynamic Model Switching TRD with the code that exists today.

Reference TRD: [Dynamic LLM Model Switching During Agent Execution](../../trd/architecture/dynamic_model_switching.md)

---

## Overall Status

Phase 1 (config, `ModelTierConfig`, per-phase model assignment, `models_used` logging) and Phase 2 (`HARLE_COMPLEX_EXECUTION_TIER` boosting) are **implemented**. Phase 3 (LLM-initiated escalation, `model_escalation_requested`, `escalate_model` tool) remains **future work**.

---

## Implementation Snapshot

| TRD area | Current status | Notes |
|----------|----------------|-------|
| Model-tier taxonomy (classifier, planner, executor) | Implemented | [`ModelTierConfig`](../../../src/harle/orchestrator/model_tier.py); all three `HARLE_MODEL_*` keys must be non-empty (`Settings` defaults apply) |
| `ModelTierConfig` dataclass | Implemented | `from_settings()`, `model_for_tier()`, `resolve_model_for_phase()` |
| Config keys (`HARLE_MODEL_CLASSIFIER`, etc.) | Implemented | In [`Settings`](../../../src/harle/config.py); `HARLE_COMPLEX_EXECUTION_TIER` normalized via `normalize_complex_execution_tier()` |
| Phase-based tier assignment | Implemented | [`run_agent_execution`](../../../src/harle/orchestrator/runner_execution.py) uses planner for planning, executor for execution (with optional boost), planner for reflection critic, executor for improvement; handoffs use executor tier (via `replace(tier, executor=…)` when boosted) |
| Per-phase model logging (`models_used`) | Implemented | Vault `## Models Used`, `runs.models_used` JSON, `RunResponse` / `RunDetail` |
| Complexity-informed tier boosting | Implemented | When complexity is `complex` and `HARLE_COMPLEX_EXECUTION_TIER` is `planner`, execution uses the planner model |
| Escalation extension point | Not implemented | No `model_escalation_requested` or `escalate_model` tool (Phase 3) |
| Reflection critic model | Implemented | Always the planner tier (`effective_reflection_critic_model()` → `model_tier_config.planner`) |
| etrace spans for model resolution | Partially implemented | `Model tier resolved`, `Complex execution tier boost` DETAIL events in runner |
| Multi-provider / Capture | Out of scope | Unchanged per TRD |

---

## What Is Implemented

### Configuration

- `HARLE_MODEL_CLASSIFIER`, `HARLE_MODEL_PLANNER`, `HARLE_MODEL_EXECUTOR`, `HARLE_COMPLEX_EXECUTION_TIER` in `Settings`.
- [`build_orchestrator`](../../../src/harle/orchestrator/builder.py) builds `ModelTierConfig`, resolves reflection critic model, normalizes complex execution tier.

### Orchestrator

- [`OrchestratorService`](../../../src/harle/orchestrator/orchestrator_service.py): `model_tier_config`, `complex_execution_tier`; `effective_model_tier_config()`, `effective_reflection_critic_model()` (planner tier).
- [`build_execution_agents`](../../../src/harle/orchestrator/agents.py) takes `ModelTierConfig` (executor tier model for each handoff agent).
- [`apply_reflection_pipeline`](../../../src/harle/orchestrator/reflection.py) takes explicit `critic_model` and `improvement_model`.

### Logging and API

- [`RunState`](../../../src/harle/orchestrator/state.py) / [`AgentResult`](../../../src/harle/orchestrator/state.py): `models_used`.
- [`finalize_orchestrator_run`](../../../src/harle/orchestrator/finalize.py): vault section and `create_run(..., models_used=…)`.
- DB [`Run`](../../../src/harle/db/models.py): `models_used` JSON column (new deployments via `create_tables`; existing PostgreSQL DBs may need a manual `ALTER TABLE` to add the column).

---

## What Is Not Implemented Yet

### Phase 3 — LLM-initiated escalation

**Missing:** `model_escalation_requested` on results, guardrail re-run, `escalate_model` tool.

**What this would unlock:** Adaptive upgrades when the executor model is insufficient.

---

## Key Deviations From The TRD

### Tier keys only

Operators configure `HARLE_MODEL_CLASSIFIER`, `HARLE_MODEL_PLANNER`, and `HARLE_MODEL_EXECUTOR` (defaults on `Settings` match the recommended split). Blank tier values raise `ValueError` at tier resolution.

---

## Current Assessment

Dynamic model switching for **algorithmic phase routing**, **complexity boost**, **deprecation path**, and **observability** (`models_used`) matches the TRD for Phases 1–2. Escalation (Phase 3) is deferred.
