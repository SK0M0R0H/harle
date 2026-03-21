---
title: "Dynamic LLM Model Switching During Agent Execution"
tags: [orchestrator, model-routing, cost-optimization, llm, multi-model, architecture]
context: global
last_updated: 2026-03-21
summary: "Defines how Harle switches between LLM model tiers during a single agent execution to balance cost, latency, and quality."
---

# Dynamic LLM Model Switching During Agent Execution

> Agents should use the right-sized model for each step: a capable model for planning and reasoning, a cheap model for straightforward execution, and a fast model for classification. This document defines how Harle switches between model tiers during a single run.

This document covers:
1. The problem and current state.
2. Research survey: how the industry and academia solve mid-execution model switching.
3. Model-tier taxonomy for Harle.
4. Trigger mechanisms (algorithmic, LLM-requested, hybrid).
5. Configuration schema.
6. Cost/latency trade-offs and fallback behaviour.
7. Proposed changes to the orchestrator loop, config, and run logging.

For the current orchestrator architecture, see [orchestrator.md](./orchestrator.md).
For multi-step reasoning levels, see [multi_step_reasoning.md](./multi_step_reasoning.md).

---

## The Problem

### Current state

Harle uses a single LLM model for the entire agent execution lifecycle. The model is set once at startup via `HARLE_LLM_MODEL` in `config.py` (default `gpt-4o-mini`) and passed to `OrchestratorService`, which stores it as `self.model` and forwards it unchanged to:

- The OpenAI Agents SDK `Agent` object (via `model=self.model` in `runner_execution.py`).
- Planning agent construction (via `planning_model or model` in `run_agent_execution`).
- Reflection calls (via `reflection_model` parameter, defaults to execution model).
- Multi-agent handoffs — all agents in the handoff graph receive the same `model` parameter in `build_execution_agents()`.
- Run logging — `finalize.py` logs a single `model` value.

The TRD `orchestrator.md` already references `models.default`, `models.complex`, and `models.classifier` in its configuration example, but none of these are wired into the code. `RunRequest` only carries `message`, `context`, and `conversation_id` — no per-request model override.

### Why this matters

A single agent run can span multiple execution phases with vastly different complexity requirements:

```
POST /chat "Research privacy solutions for L2 and create a Trello card"

Phase 1: Route (classify intent)          → trivial, ~50 tokens
Phase 2: Plan (generate execution plan)   → moderate reasoning
Phase 3: Execute step 1 (web search)      → tool call + synthesis
Phase 4: Execute step 2 (dataset search)  → tool call + synthesis
Phase 5: Execute step 3 (synthesize)      → complex reasoning
Phase 6: Handoff to Secretary             → tool call, simple
Phase 7: Reflect (quality review)         → moderate reasoning
```

Using `gpt-4o` for every phase is correct but wasteful — phases 1 and 6 could use a model 10–20x cheaper. Using `gpt-4o-mini` for every phase is fast but brittle — phase 5 may produce a qualitatively worse synthesis.

The cost difference is significant. At Harle's usage level (20–50 runs/day), a well-configured multi-tier setup can reduce LLM costs by 40–70% with negligible quality loss, based on industry benchmarks showing that most production queries are not frontier-hard.

---

## Research Survey

### OpenAI Agents SDK — Per-Agent Model Configuration

The OpenAI Agents SDK (current version) supports model specification at three levels:

1. **Per-agent:** `Agent(name="planner", model="gpt-4o", ...)` — each agent in a handoff graph can use a different model.
2. **Per-run default:** `RunConfig(model="gpt-4o-mini")` — applies to agents that don't specify their own model.
3. **Environment default:** `OPENAI_DEFAULT_MODEL` — system-wide fallback.

The SDK explicitly supports **mixing models in one workflow** — their documentation shows a triage agent using `gpt-5.4`, a Spanish agent using `gpt-5-mini`, and an English agent using `gpt-5-nano`, all in a single handoff chain. Each agent's model is resolved independently per turn.

**What this means for Harle:** The SDK already provides the mechanism for different models per agent (and therefore per execution phase, since Harle can construct separate Agent objects for planning, execution, and reflection). No SDK modifications are needed — only changes to how Harle constructs agents.

### LangGraph — Conditional Model Routing

LangGraph enables conditional workflows where the next step — including which model to use — is dynamically chosen based on state conditions. The core pattern uses:

- A **routing function** that inspects the state and returns the next node.
- **State** as a shared `TypedDict` flowing through the graph.
- **Conditional edges** that call routing functions to decide destinations.

LangGraph's plan-and-execute pattern explicitly uses a stronger model for planning and a cheaper model for execution steps. This is the most widely deployed multi-model pattern in LangChain/LangGraph production systems.

**What this means for Harle:** LangGraph validates the approach of different models for different phases. Harle's orchestrator already has the equivalent structure (planning → execution → reflection as separate phases), so the pattern translates directly.

### AutoGen — Model Policies and Handoff Patterns

AutoGen (v0.4+) supports designating a primary model with fallback options. Real-world implementations use patterns like "Claude Sonnet for primary, GPT-4o as fallback for certain tasks." Multi-agent handoffs allow agents with different model configurations to collaborate.

AutoGen's fundamental design is conversation-based between agent pairs, which works for simple routing but becomes awkward for complex branching. Harle's phase-based architecture avoids this limitation.

### Classifier-Based and Cascading Routing (Industry & Academic)

The most relevant industry and academic approaches to mid-execution model switching:

**Static routing** (task-type → model mapping) is the simplest production pattern. Hardcode models per execution phase. Predictable, zero overhead, easy to audit. Limitation: cannot adapt to query-level variation within a task type.

**Classifier-based routing** uses a lightweight model or heuristic to evaluate query complexity and predict which tier suffices. RouteLLM (LMSYS, ICLR 2025) achieves 85% cost reduction on MT-Bench routing between GPT-4 and Mixtral while maintaining 95% quality. Their BERT classifier variant runs in <10ms.

**Cascading** tries a cheap model first and escalates if confidence is low. ETH Zurich's 2024 paper "A Unified Approach to Routing and Cascading" proves theoretical optimality conditions and introduces cascade routing — combining both approaches. The key insight: cascading pays a latency tax (sequential calls) but eliminates the need for an accurate upfront classifier.

**Stepwise routing** (STEER, 2025) performs fine-grained, step-level routing between smaller and larger models during reasoning. Uses confidence scores from the smaller model's logits to invoke the larger model only when necessary. Achieves 20% accuracy improvements with 48% fewer FLOPs on mathematical reasoning.

**Agent-internal routing** is the pattern where different steps within an agent loop (intent classification, tool selection, reasoning, response synthesis) are independently routed to appropriate models. Zylos Research (2026) shows this can reduce inference costs by 40–85% while maintaining 90–95% quality.

**Budget-constrained routing** treats cost as a hard budget and maximizes quality within it. The PILOT paper (2025) formulates this as a contextual bandit problem, enabling operators to dial the cost/quality trade-off at inference time without retraining.

### LLM Self-Escalation

Self-REF (2024) introduces confidence tokens into LLMs for reliable confidence expression without external models. This enables a model to signal when it is unsure and should escalate.

The "Orchestrating Intelligence" paper (January 2026) extends this with confidence-aware routing — agents self-report confidence and the orchestrator dynamically reassigns subtasks based on live confidence signals.

**What this means for Harle (future):** LLM-initiated escalation is promising but adds complexity (parsing confidence signals, managing escalation loops). A hybrid approach — algorithmic routing with an extension point for model-requested escalation — is the pragmatic path.

---

## Design Decisions

### Decision 1: Algorithmic-First, Hybrid-Ready

Harle uses **algorithmic routing** (execution phase → model tier mapping) as the primary mechanism, with a **clear extension point** for LLM-initiated escalation in the future.

**Why algorithmic first:**
- Harle's execution phases are already well-defined (routing, planning, execution, reflection) — the phase determines the tier with zero overhead.
- Algorithmic routing is deterministic, debuggable, and costs nothing (no extra LLM call for the routing decision).
- The existing complexity classifier (Level 3) already provides a signal for when to use a stronger model.
- At Harle's scale (20–50 runs/day), the engineering cost of a classifier-based router exceeds the savings from marginal routing improvements.

**Why hybrid-ready:**
- The extension point for self-escalation (Decision 5) prepares for future confidence-based routing without requiring architectural changes.
- As Harle scales or tasks become more varied, upgrading to classifier-based routing within phases becomes a configuration change, not a rewrite.

### Decision 2: Phase-Based Tier Assignment

Each execution phase maps to a **model tier** (logical name), and each tier maps to a **concrete model** (configured per deployment). This two-level indirection separates the "what kind of model" decision from the "which specific model" decision.

```
Execution Phase → Model Tier → Concrete Model
─────────────────────────────────────────────────
routing/classify  → classifier   → gpt-4o-mini
planning          → planner      → gpt-4o
execution         → executor     → gpt-4o-mini
reflection        → planner      → gpt-4o
improvement       → executor     → gpt-4o-mini
```

Multiple phases can share the same tier. The tier assignment is configurable — operators who want a single model for everything set all tiers to the same value, preserving backward compatibility.

### Decision 3: Explicit Configuration With Warnings

Each tier has a built-in default model. The resolution order for any tier is:

```
1. Explicit tier model in config (e.g., HARLE_MODEL_PLANNER)
2. Built-in default for that tier (see tier definitions table)
```

`HARLE_LLM_MODEL` does **not** act as a fallback for tier resolution. The tier system is self-contained — each tier resolves independently to its own configured or default value. This keeps tier behaviour predictable: an operator always knows which model a tier uses by looking at one place (the tier key or its documented default), never at a shared fallback.

When a tier key is not set, the server logs a **warning** at startup indicating which tier is using its built-in default. This makes unconfigured tiers visible without failing the startup:

```
WARNING: HARLE_MODEL_PLANNER not configured — using built-in default "gpt-4o"
WARNING: HARLE_MODEL_EXECUTOR not configured — using built-in default "gpt-4o-mini"
```

A deployment with no `HARLE_MODEL_*` keys set uses the built-in defaults for all tiers (classifier=`gpt-4o-mini`, planner=`gpt-4o`, executor=`gpt-4o-mini`) and logs a warning for each.

### Decision 4: Per-Step Model Logging

Run logging records which model was actually used at each phase, not just the default. This enables:
- Accurate cost attribution per phase.
- Debugging why a particular phase produced a certain quality.
- Analytics on model usage distribution across runs.

### Decision 5: Extension Point for LLM-Initiated Escalation

A future escalation mechanism is designed but not implemented in the first version. The design reserves a `model_tier_hint` field in internal run state that, when set by a tool or guardrail, overrides the algorithmic tier for the next phase.

Concrete use case: if the execution agent encounters a problem it cannot solve (e.g., complex reasoning failure), a future guardrail could detect this (via output validation or tool-call patterns) and trigger re-execution with the planner-tier model.

---

## Model-Tier Taxonomy

### Tier definitions

Harle defines three model tiers. Each tier has a purpose, a complexity profile, and a default model.

| Tier | Purpose | When used | Default model | Typical cost |
|------|---------|-----------|---------------|-------------|
| **classifier** | Fast, cheap decisions with structured output | Routing fallback (LLM classification), complexity classification | `gpt-4o-mini` | Lowest |
| **planner** | Capable reasoning and evaluation | Planning (Level 3), reflection critic (Level 4), complex synthesis | `gpt-4o` | Higher |
| **executor** | Balanced cost/quality for tool-calling loops | Main execution loop, improvement pass, handoff agents | `gpt-4o-mini` | Lower |

### Phase-to-tier mapping

| Execution phase | Tier | Rationale |
|----------------|------|-----------|
| Router LLM fallback (step 4 in TRD) | `classifier` | Fast, cheap classification; structured output |
| Complexity classification | `classifier` | Simple yes/no decision |
| Planning (Level 3) | `planner` | Plan quality drives entire run quality; worth the investment |
| Execution loop (Level 1–2) | `executor` | Most work is tool calling + moderate synthesis; cheaper model suffices |
| Handoff target agents | `executor` | Same rationale as execution |
| Reflection critic (Level 4) | `planner` | Quality evaluation needs strong reasoning |
| Improvement pass (Level 4) | `executor` | Executing improvements with tool calls; same as execution |

### Tier override rules

Operators can customize the mapping for specific roles or use cases:

1. **Per-role tier override:** A role's prompt frontmatter can specify `preferred_model_tier: planner` to force all execution for that role to use the planner tier. The Researcher role, for example, might always use the planner tier because research synthesis requires stronger reasoning.

2. **Per-request tier hint (future):** `RunRequest` can carry a `model_tier` field that overrides the default phase-to-tier mapping for the entire run. This enables callers to force a premium tier for important requests.

---

## Trigger Mechanisms

### Primary: Algorithmic Phase-Based Switching

The orchestrator determines the model tier automatically based on the current execution phase. No extra LLM call or classification step is needed — the phase identity *is* the trigger.

```python
def resolve_model_for_phase(
    phase: str,
    tier_config: ModelTierConfig,
    role_override: str | None = None,
) -> str:
    """Resolve the concrete model name for an execution phase.

    Args:
        phase: Current execution phase (planning, execution, reflection, etc.).
        tier_config: Tier-to-model mapping from config.
        role_override: Optional per-role tier override from prompt frontmatter.

    Returns:
        Concrete model name string.
    """
    if role_override:
        return tier_config.model_for_tier(role_override)

    phase_tier_map = {
        "routing": "classifier",
        "classification": "classifier",
        "planning": "planner",
        "execution": "executor",
        "handoff": "executor",
        "reflection": "planner",
        "improvement": "executor",
    }
    tier = phase_tier_map.get(phase, "executor")
    return tier_config.model_for_tier(tier)
```

**When switching happens:**
- **Before planning:** If Level 3 planning is triggered, the planning Agent is constructed with `tier_config.planner` model.
- **Before execution:** The execution Agent is constructed with `tier_config.executor` model.
- **Before reflection:** If Level 4 reflection is triggered, the reflection Agent uses `tier_config.planner` model.
- **Before improvement:** The improvement Agent uses `tier_config.executor` model.
- **At handoff:** Handoff target agents use `tier_config.executor` model (or the target role's override).

Since the OpenAI Agents SDK supports per-agent model configuration, each phase simply constructs its Agent with the resolved model. No mid-loop model switching is needed — each phase is a separate `Runner.run_sync()` call (planning, execution, reflection, improvement are already separate calls in `runner_execution.py`).

### Future: LLM-Initiated Escalation (Extension Point)

The extension point for model-requested escalation consists of:

1. A `model_escalation_requested` field on the internal `AgentExecutionResult`.
2. A guardrail check after execution: if the execution result indicates low quality (e.g., the response is a refusal, a repetition of the question, or exceeds `MaxTurnsExceeded`), the orchestrator can re-run with the planner tier.
3. A dedicated escalation tool (future) that the model can call: `escalate_model(reason="This task requires stronger reasoning for multi-step mathematical proof")`.

**Why this is deferred:** Implementing escalation correctly requires:
- Reliable confidence estimation (not yet solved generically).
- Guard against escalation loops (model A escalates to model B, which also fails).
- Cost controls (escalation doubles the LLM cost of a run).

The algorithmic approach covers 90%+ of cases. The extension point ensures escalation can be added without architectural changes.

### Hybrid: Complexity-Informed Tier Boosting

A lightweight hybrid is available immediately via the existing complexity classifier (Level 3, `classify_complexity()` in `orchestrator/planner.py`). The classifier is a heuristic function (no LLM call) that returns one of two values:

| Classifier result | Meaning | Signals used |
|-------------------|---------|-------------|
| `"simple"` | Routine request; planning is skipped | Short message, starts with a question word, no multi-step phrases |
| `"complex"` | Multi-step or knowledge-intensive; planning is triggered | Long message, keywords like "research"/"compare"/"analyze", multi-step phrases, multiple questions |

When the classifier returns `"complex"`:

1. The **planning** phase already uses the planner tier (by default).
2. The **execution** phase can optionally be boosted to the planner tier as well.

This is controlled by a new config key `HARLE_COMPLEX_EXECUTION_TIER` (default: `executor`, can be set to `planner` to boost complex requests).

```
simple request:  planning=N/A (skipped)  execution=executor  reflection=N/A (skipped)
complex request: planning=planner        execution=executor  reflection=planner
complex+boosted: planning=planner        execution=planner   reflection=planner
```

---

## Configuration Schema

### Config file (config.yaml)

New keys under the existing flat `HARLE_` namespace, following the established pattern:

```yaml
# --- Model tiers ---
# Each tier maps to a concrete model name. When unset, the built-in
# default for that tier is used (a startup warning is logged).
# Built-in defaults: classifier=gpt-4o-mini, planner=gpt-4o, executor=gpt-4o-mini.
HARLE_MODEL_CLASSIFIER: "gpt-4o-mini"    # Fast/cheap: routing, classification
HARLE_MODEL_PLANNER: "gpt-4o"            # Capable: planning, reflection
HARLE_MODEL_EXECUTOR: "gpt-4o-mini"      # Balanced: execution, improvement

# Boost execution tier when the complexity classifier returns "complex".
# The classifier is a local heuristic (no LLM call) that returns
# "simple" or "complex" based on message length, keywords, and structure.
# Options: "executor" (default, no boost) or "planner" (use planner model)
HARLE_COMPLEX_EXECUTION_TIER: "executor"
```

### Environment variable support

Each key can be set as an environment variable (same name), following the existing resolution order: config file > env var > built-in default.

### Settings dataclass changes

```python
@dataclass(frozen=True)
class Settings:
    # ... existing fields ...

    # Model tiers (None = use built-in default for that tier; warning logged)
    HARLE_MODEL_CLASSIFIER: str | None = None
    HARLE_MODEL_PLANNER: str | None = None
    HARLE_MODEL_EXECUTOR: str | None = None
    HARLE_COMPLEX_EXECUTION_TIER: str = "executor"
```

### ModelTierConfig helper

A new lightweight dataclass encapsulates tier resolution:

```python
TIER_DEFAULTS: dict[str, str] = {
    "classifier": "gpt-4o-mini",
    "planner": "gpt-4o",
    "executor": "gpt-4o-mini",
}

@dataclass(frozen=True)
class ModelTierConfig:
    """Resolved model names for each tier."""

    classifier: str
    planner: str
    executor: str

    @staticmethod
    def from_settings(settings: Settings) -> ModelTierConfig:
        def _resolve(key: str | None, tier: str) -> str:
            if key:
                return key
            logger.warning(
                "HARLE_MODEL_%s not configured — using built-in default %r",
                tier.upper(),
                TIER_DEFAULTS[tier],
            )
            return TIER_DEFAULTS[tier]

        return ModelTierConfig(
            classifier=_resolve(settings.HARLE_MODEL_CLASSIFIER, "classifier"),
            planner=_resolve(settings.HARLE_MODEL_PLANNER, "planner"),
            executor=_resolve(settings.HARLE_MODEL_EXECUTOR, "executor"),
        )

    def model_for_tier(self, tier: str) -> str:
        return getattr(self, tier, TIER_DEFAULTS.get(tier, "gpt-4o-mini"))
```

### Backward compatibility

A deployment with no `HARLE_MODEL_*` keys set uses the built-in defaults for each tier (classifier=`gpt-4o-mini`, planner=`gpt-4o`, executor=`gpt-4o-mini`). A warning is logged for each unconfigured tier at startup. Existing tests and deployments continue to work — the defaults match the models already used — but the warnings make the implicit configuration visible.

---

## Cost/Latency Trade-Offs

### Cost projections

Based on OpenAI pricing as of March 2026 (GPT-4o-mini: $0.15/$0.60 per 1M input/output tokens; GPT-4o: $2.50/$10.00 per 1M input/output tokens):

| Scenario | Models used | Est. cost/run | Savings vs all-gpt-4o |
|----------|-----------|--------------|----------------------|
| Single model (current, gpt-4o-mini) | all mini | $0.003–0.03 | — |
| Single model (all gpt-4o) | all 4o | $0.05–0.50 | baseline |
| **Multi-tier (recommended)** | classifier=mini, planner=4o, executor=mini | $0.01–0.10 | **60–80%** |
| Boosted complex (all planner) | classifier=mini, rest=4o | $0.04–0.40 | **10–20%** |

The multi-tier setup costs slightly more than all-mini but produces significantly better planning and reflection quality (the phases where model capability matters most).

### Latency impact

Model switching adds zero latency overhead because:
- The switch is a parameter change on Agent construction, not an additional API call.
- Planning, execution, and reflection are already separate `Runner.run_sync()` calls.
- No classifier model call is needed — the phase identity determines the tier.

The only latency difference is the per-token speed of different models. GPT-4o has somewhat higher time-to-first-token than GPT-4o-mini, so planning and reflection phases will be slightly slower. This is acceptable because planning and reflection are inherently sequential phases where speed matters less than quality.

### When to use which configuration

| Use case | Recommended config | Rationale |
|----------|-------------------|-----------|
| Development/testing | Single model (mini) | Cheapest, fastest iteration |
| Production (cost-sensitive) | Multi-tier (mini + 4o) | Best cost/quality balance |
| Production (quality-first) | All planner (4o) | Maximum quality, higher cost |
| Batch processing | Single model (mini) | Throughput over quality |

---

## Fallback Behaviour

### Model unavailability

If a configured model is unavailable (API error, rate limit), the fallback order is:

```
1. Retry with the same model (existing retry logic)
2. If retries exhausted, the run fails with a clear error
```

There is no automatic fallback to a different model. If a tier's model is down, the run fails rather than silently using an unintended model — this prevents a planning phase from quietly downgrading to a weaker model that could produce a bad plan. The operator can reconfigure tier models if a model is permanently unavailable.

Model failure is logged as an etrace DETAIL event with the tier, failed model, and error reason.

### Invalid tier configuration

If a configured tier name in `HARLE_COMPLEX_EXECUTION_TIER` is not a known tier, the orchestrator logs a warning and uses `executor`. No crash, no silent misbehaviour.

### Provider mismatch

If `HARLE_MODEL_PLANNER` specifies a model from a different provider than `HARLE_LLM_PROVIDER` (out of scope for this TRD — multi-provider is explicitly excluded), the run fails with a clear configuration error at startup, not at request time.

---

## Proposed Changes

### 1. Config (`config.py`)

| Change | Detail |
|--------|--------|
| Add `HARLE_MODEL_CLASSIFIER`, `HARLE_MODEL_PLANNER`, `HARLE_MODEL_EXECUTOR` fields to `Settings` | `str \| None`, default `None` (uses built-in tier default; warning logged) |
| Add `HARLE_COMPLEX_EXECUTION_TIER` field to `Settings` | `str`, default `"executor"` |
| New `ModelTierConfig` dataclass | Encapsulates tier resolution with `from_settings()` factory |
| Update `config.example.yaml` | Add commented-out model tier keys with documentation |

### 2. Orchestrator service (`orchestrator/orchestrator_service.py`)

| Change | Detail |
|--------|--------|
| Add `model_tier_config: ModelTierConfig` attribute | Replaces the need to pass individual model names per phase |
| Pass tier-resolved models to `run_agent_execution` | Planning model, execution model, and reflection model all come from `ModelTierConfig` |
| Remove redundant `planning_model` and `reflection_model` attributes | These become derivable from `model_tier_config` |

### 3. Runner execution (`orchestrator/runner_execution.py`)

| Change | Detail |
|--------|--------|
| Accept `ModelTierConfig` instead of individual `model`, `planning_model`, `reflection_model` parameters | Cleaner interface, single source of truth |
| Construct planning Agent with `tier_config.planner` model | Currently uses `planning_model or model` |
| Construct execution Agent with `tier_config.executor` model | Currently uses `model` for all agents |
| Pass `tier_config.planner` to reflection pipeline | Currently uses `reflection_model` (which defaults to execution model) |
| Add `models_used` to `AgentExecutionResult` | Dict mapping phase names to model names used |

### 4. Multi-agent handoffs (`orchestrator/agents.py`)

| Change | Detail |
|--------|--------|
| `build_execution_agents` accepts `ModelTierConfig` | All handoff agents use `tier_config.executor` (or role-specific override) |
| Each Agent in the handoff graph gets its tier-resolved model | Currently all agents share the same `model` parameter |

### 5. Builder (`orchestrator/builder.py`)

| Change | Detail |
|--------|--------|
| Build `ModelTierConfig` from `Settings` | Pass to `OrchestratorService` |
| Remove separate `planning_model`, `reflection_model` plumbing | Consolidated into `ModelTierConfig` |

### 6. Run logging (`orchestrator/finalize.py`, `db/runs.py`)

| Change | Detail |
|--------|--------|
| Log `models_used` dict in vault result body | New `## Models Used` section showing which model was used at each phase |
| Extend `runs` table: `models_used` JSON column | Nullable; stores `{"planning": "gpt-4o", "execution": "gpt-4o-mini", ...}` |
| Update `create_run` to accept and persist `models_used` | Existing `model_used` column remains for backward compat (stores the executor model) |

### 7. API models (`api/models.py`)

| Change | Detail |
|--------|--------|
| Add `models_used: dict[str, str] \| None` to `RunResponse` | Optional; shows per-phase model info when multi-tier is active |
| Add `models_used: dict[str, str] \| None` to `RunDetail` | Same field on the GET /run/{id} response |

### 8. Execution tracing

| Span | Level | Module | Attributes |
|------|-------|--------|------------|
| `Model tier resolved` | DETAIL | orchestrator | `phase="planning"`, `tier="planner"`, `model="gpt-4o"`, `source="config"` or `"default"` |
| `Model tier using default` | DETAIL | orchestrator | `tier="executor"`, `default_model="gpt-4o-mini"` (emitted at startup for unconfigured tiers) |

---

## Migration Path

### Phase 1: Config and tier resolution (this TRD)

1. Add `HARLE_MODEL_*` settings and `ModelTierConfig`.
2. Wire `ModelTierConfig` through builder → service → runner_execution.
3. Construct planning Agent with `tier_config.planner`, execution Agent with `tier_config.executor`, reflection with `tier_config.planner`.
4. Log `models_used` in vault and DB.
5. Update `RunResponse` and `RunDetail` with `models_used`.

All existing tests pass without changes (default config produces single-model behaviour). New tests verify multi-tier resolution and per-phase model construction.

### Phase 2: Complexity-informed boosting

1. Add `HARLE_COMPLEX_EXECUTION_TIER` support.
2. When the complexity classifier returns "complex" and `HARLE_COMPLEX_EXECUTION_TIER` is `"planner"`, the execution phase uses the planner model.
3. Log the boost decision in etrace.

### Phase 3: Extension point for escalation (future)

1. Add `model_escalation_requested` field to `AgentExecutionResult`.
2. Implement escalation guardrail: detect execution failures that could benefit from a stronger model.
3. Re-run with the planner tier when escalation is triggered (with a hard limit of 1 escalation per run).
4. Add `escalate_model` tool for LLM-initiated escalation (gated behind a config flag).

---

## Interaction With Existing Features

### Planning (Level 3)

Today: `HARLE_PLANNING_MODEL` is an optional override; when `None`, the execution model is used. After this change: `HARLE_PLANNING_MODEL` is **deprecated** in favour of `HARLE_MODEL_PLANNER`. If both are set, `HARLE_PLANNING_MODEL` takes precedence (to avoid breaking existing configs), and a deprecation warning is logged.

### Reflection (Level 4)

Today: `HARLE_REFLECTION_MODEL` is an optional override; when `None`, the execution model is used. After this change: `HARLE_REFLECTION_MODEL` is **deprecated** in favour of `HARLE_MODEL_PLANNER` for the critic and `HARLE_MODEL_EXECUTOR` for the improvement pass. Same precedence rule as planning.

### Capture module

Out of scope. The capture module (`CaptureEngine`) manages its own model parameter independently. This TRD does not change capture model usage.

### Multi-provider switching

Out of scope. This TRD focuses on model-tier switching within a single provider (OpenAI). Cross-provider switching (OpenAI → Anthropic mid-run) requires provider abstraction changes that are separate work.

---

## Key Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Config complexity** — more knobs to tune | User confusion, mis-configuration | Sensible built-in defaults per tier; startup warnings for unconfigured tiers; clear docs; `config.example.yaml` with explanatory comments |
| **Model capability mismatch** — executor model too weak for a particular task | Lower quality on complex execution steps | Complexity-informed boosting (Phase 2); escalation extension point (Phase 3) |
| **Cost surprise** — planner model is expensive, user doesn't realize planning is using it | Unexpected bills | `models_used` in RunResponse; cost tracking per phase in run logs |
| **Deprecation of HARLE_PLANNING_MODEL / HARLE_REFLECTION_MODEL** | Existing configs break silently | Explicit deprecation warnings in logs; old keys take precedence during transition |
| **Feature interaction** — tier selection interacts with handoff model, think tool, future features | Unexpected model selection | Single `ModelTierConfig` as source of truth; all model resolution flows through it |

---

## Summary

Dynamic model switching transforms a single knob (`HARLE_LLM_MODEL`) into a tier system that matches model capability to task complexity. The design is:

- **Algorithmic-first:** Phase identity determines model tier — zero overhead, fully deterministic.
- **Backward-compatible:** Single-model deployments work unchanged.
- **Observable:** Per-phase model usage is logged in vault, DB, API, and etrace.
- **Extensible:** The escalation extension point prepares for LLM-initiated model switching without architectural changes.
- **Cost-effective:** Multi-tier routing is projected to reduce costs by 60–80% compared to using the strongest model everywhere, while maintaining quality on the phases that matter (planning, reflection).

The recommended starting configuration for production is:

```yaml
HARLE_MODEL_CLASSIFIER: "gpt-4o-mini"  # routing, classification
HARLE_MODEL_PLANNER: "gpt-4o"          # planning + reflection
HARLE_MODEL_EXECUTOR: "gpt-4o-mini"    # execution, improvement
```

Three keys, explicit per tier. 60–80% savings on planning-heavy runs. No silent fallbacks — if a tier is unconfigured, the server warns and uses its built-in default.
