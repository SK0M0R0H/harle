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

Dynamic model switching is **not implemented**. The codebase uses a single model (`HARLE_LLM_MODEL`) for all execution phases, with optional per-feature overrides (`HARLE_PLANNING_MODEL`, `HARLE_REFLECTION_MODEL`) that default to the same base model. There is no model-tier taxonomy, no `ModelTierConfig`, and run logging records a single `model_used` value.

---

## Implementation Snapshot

| TRD area | Current status | Notes |
|----------|----------------|-------|
| Model-tier taxonomy (classifier, planner, executor) | Not implemented | Single model; `HARLE_PLANNING_MODEL` and `HARLE_REFLECTION_MODEL` exist as ad-hoc overrides but are not part of a tier system |
| `ModelTierConfig` dataclass | Not implemented | No tier resolution helper exists |
| Config keys (`HARLE_MODEL_CLASSIFIER`, `HARLE_MODEL_PLANNER`, `HARLE_MODEL_EXECUTOR`) | Not implemented | Only `HARLE_LLM_MODEL`, `HARLE_PLANNING_MODEL`, `HARLE_REFLECTION_MODEL` exist; TRD specifies per-tier built-in defaults with startup warnings (no `HARLE_LLM_MODEL` fallback) |
| Phase-based tier assignment | Not implemented | All agents in `runner_execution.py` and `agents.py` receive the same `model` parameter |
| Per-phase model logging (`models_used`) | Not implemented | `finalize.py` logs a single `model` value; `runs` table has `model_used` (singular) |
| `RunResponse` / `RunDetail` `models_used` field | Not implemented | No per-phase model info in API responses |
| Complexity-informed tier boosting | Not implemented | Complexity classifier exists (Level 3) but does not influence model tier selection |
| Escalation extension point | Not implemented | No `model_escalation_requested` field or escalation guardrail |
| Backward compatibility (single-model fallback) | N/A (current behaviour) | This is what exists today; the TRD preserves it |
| Deprecation of `HARLE_PLANNING_MODEL` / `HARLE_REFLECTION_MODEL` | Not applicable | These keys are current; deprecation happens when tier config is added |
| etrace spans for model resolution | Not implemented | No model-tier-related trace events |

---

## What Is Implemented

### Single-model configuration

- `HARLE_LLM_MODEL` in `config.py` (default `gpt-4o-mini`) used for all execution phases.
- `HARLE_PLANNING_MODEL` — optional override for the planning agent (Level 3); defaults to `HARLE_LLM_MODEL`.
- `HARLE_REFLECTION_MODEL` — optional override for the reflection critic (Level 4); defaults to `HARLE_LLM_MODEL`.
- All handoff agents in `build_execution_agents()` receive the same `model` parameter.

### Run logging (single model)

- `finalize.py` logs `model=self.model` to `create_run`.
- `runs` table has a `model_used` column (stores the single execution model name).

---

## What Is Not Implemented Yet

### 1. Model-tier taxonomy and `ModelTierConfig`

**Missing:** Three-tier system (classifier, planner, executor) with a `ModelTierConfig` dataclass that resolves tier names to concrete model strings.

**What this would unlock:** Different models for different execution phases without per-feature ad-hoc overrides.

### 2. Phase-based model assignment

**Missing:** Each execution phase (planning, execution, reflection, handoff, improvement) resolving its model via the tier config rather than using a single model.

**What this would unlock:** Automatic cost optimization — cheap models for simple phases, capable models for reasoning-heavy phases.

### 3. Per-phase model logging

**Missing:** `models_used` dict in vault logs, `runs` table, `RunResponse`, and `RunDetail` showing which model was used at each phase.

**What this would unlock:** Accurate cost attribution, debugging, and analytics per phase.

### 4. Complexity-informed tier boosting

**Missing:** `HARLE_COMPLEX_EXECUTION_TIER` config key that upgrades the execution model to the planner tier for complex requests.

**What this would unlock:** Quality improvement on complex tasks without always paying for the expensive model.

### 5. Escalation extension point

**Missing:** `model_escalation_requested` field, escalation guardrail, and `escalate_model` tool for LLM-initiated model switching.

**What this would unlock:** Adaptive model selection based on runtime signals (future work).

---

## Key Deviations From The TRD

### Ad-hoc per-feature overrides vs tier system

The current `HARLE_PLANNING_MODEL` and `HARLE_REFLECTION_MODEL` are ad-hoc overrides that partially address the same problem the TRD's tier system solves. The TRD proposes deprecating these in favour of `HARLE_MODEL_PLANNER` (covering both planning and reflection).

---

## Current Assessment

Dynamic model switching is **not yet started**. The groundwork exists (separate Runner calls for planning, execution, and reflection; per-agent model support in the OpenAI Agents SDK), but no tier resolution or per-phase model assignment is implemented. The first implementation step is adding `ModelTierConfig` and wiring it through the builder → service → runner_execution path.
