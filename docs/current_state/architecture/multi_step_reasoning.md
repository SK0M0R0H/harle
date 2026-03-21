---
title: "Multi-Step Reasoning — Current State"
tags: [multi-step-reasoning, current-state, architecture, agentic-loop, tool-use, implementation-status, planning]
context: global
last_updated: 2026-03-21
summary: "Tracks what multi-step reasoning implements vs the TRD (levels 0–7), and what each missing part would unlock. Level 4 (reflection, think tool) is implemented."
---

# Multi-Step Reasoning — Current State

> This document compares the target design in the Multi-Step Reasoning TRD with the code that exists today. Implementation lives in `src/harle/orchestrator/` (agentic loop, Runner, planning, max_turns) and `src/harle/tools/` (tool registry, vault, web search, Trello). It describes what is implemented, what is partial, and what is missing, and what each missing part would unlock.

Reference TRD: [Multi-Step Reasoning — Design & Incremental Implementation Plan](../../trd/architecture/multi_step_reasoning.md). See also [Orchestrator TRD](../../trd/architecture/orchestrator.md) and [Tools TRD](../../trd/architecture/tools.md).

---

## Overall Status

**Levels 1–4 are implemented for the OpenAI Agents SDK path.** The orchestrator uses the OpenAI Agents SDK `Runner` with an `Agent` (instructions from Context Assembler, tools from the registry), `max_turns` from config (default 10), and run logging. The tool-calling loop (ReAct-style) works: the LLM can call dataset tools, web search, and Trello during a run and see results in subsequent turns. **Level 3 (plan-then-execute)** adds a heuristic complexity classifier; for **complex** requests it runs a **planning agent** (same tools as execution, separate `max_turns` budget) that may call tools before emitting a numbered plan; the validated plan is injected into execution instructions; optional `REVISED PLAN:` blocks in the final answer are parsed for vault logging. **Level 4 (reflection and self-critique)** runs after execution when triggers match: `orchestrator/reflection.py` (`should_reflect`, `run_reflection`, `run_improvement`, `apply_reflection_pipeline`), optional improvement pass (at most one) with the same tools as execution, fail-open JSON parsing, vault `## Reflection` section, DB columns `reflection_triggered` / `reflection_improved`, `RunResponse` fields, and config keys `HARLE_REFLECTION_*` plus `HARLE_THINK_TOOL_ENABLED`. The **think** tool (`tools/think/`) is a no-op scratchpad registered via `build_tool_registry(..., think_tool_enabled=...)`. **Levels 5–7 are not implemented:** multi-agent handoffs, adaptive strategy selection, or parallel execution. Streaming during multi-step runs is not implemented. **Existing PostgreSQL databases** need `ALTER TABLE runs ADD COLUMN ...` for the new nullable columns (see snapshot notes) if tables were created before this feature.

---

## Implementation Snapshot

| TRD area | Current status | Notes |
|----------|----------------|-------|
| Level 0: Baseline (single LLM call) | Superseded | Legacy provider path still exists when no OpenAI key; primary path is Level 1+. |
| Level 1: Basic tool-calling loop | Implemented | Agents SDK `Runner.run_sync`, `Agent` with instructions + tools, `max_turns` (config `max_iterations`), run logging per run; vault + dataset tools. |
| Level 2: External tools | Implemented | Web search and Trello modules in tool registry; tool allowlist and constraints in tools layer; default `max_iterations=10`. Approval infrastructure exists on tools; orchestrator does not pause for approval in request path. |
| Level 3: Plan-then-Execute | Implemented | `orchestrator/planner.py`: `classify_complexity` (heuristics), `generate_plan` (planning `Agent` + tools + `HARLE_PLANNING_MAX_TURNS`), `validate_plan`, injection via `format_plan_for_injection` plus `sdk_result.build_planning_tool_context_section` (planning tool outputs for execution), `extract_plan_revisions` for logs. `orchestrator/runner_execution.py` orchestrates planning then execution. Config: `HARLE_PLANNING_ENABLED`, `HARLE_PLANNING_MODEL`, `HARLE_PLANNING_MAX_TURNS`, `HARLE_PLANNED_MAX_TURNS`. Simple requests skip planning. Failure modes: fall back to Level 2 (no extra user-visible error). |
| Level 4: Reflection and self-critique | Implemented | `reflection.py` + `runner_execution.py` post-execution pipeline; triggers (OR: tool count, keywords, `routing_method==planned`, role); reflection `Agent` (`max_turns=1`, no tools); improvement `Agent` reuses execution tools; `ThinkToolModule` + factory; `HARLE_REFLECTION_*`, `HARLE_THINK_TOOL_ENABLED`. Existing DBs: add nullable `reflection_triggered`, `reflection_improved` on `runs` if upgrading. |
| Level 5: Multi-agent handoffs | Not implemented | Single agent only; no handoff declarations, shared conversation on handoff, or Router-based starting agent. |
| Level 6: Adaptive strategy selection | Not implemented | No strategy selector; no per-role strategy config or user override. |
| Level 7: Parallel execution | Not implemented | No parallel tool calls, parallel agents, or branch-and-merge. |
| Context assembly once before loop | Implemented | Context Assembler runs before the loop; system prompt is fixed for the run. |
| Tool results as appendable context | Implemented | SDK appends tool results to conversation; agent sees them in later turns. |
| Layered guardrails | Partially implemented | SDK `max_turns`; tool allowlist and constraints in tools layer. No per-run timeout, token-budget cap, or output validation in orchestrator. |
| Streaming during multi-step runs | Not implemented | No tool-call notifications or intermediate status over SSE. |
| Thinking step via system prompt | Implemented | Instruction in agent prompt to state what is known, what is needed, and why calling a tool; **plus** optional Level 4 `think` tool (no-op) when `HARLE_THINK_TOOL_ENABLED` is true. |

---

## What Is Implemented

### 1. Level 1: Basic tool-calling loop (ReAct)

- **Runner and Agent:** `orchestrator/runner_execution.py` and `orchestrator/orchestrator_service.py` (via `execution.py` mixin; `service.py` re-exports) build an `Agent` with name, instructions (system prompt + tool skills + thinking instruction), tools from the registry, and model; calls `Runner.run_sync(agent, user_message, max_turns=...)`.
- **max_turns:** Config `HARLE_MAX_ITERATIONS` (default 10); `MaxTurnsExceeded` is caught and returns a clear partial-result message.
- **Tool module foundations:** Vault tools (`dataset_search`, `dataset_read_file`) and tool registry; tools are resolved and passed to the Agent.
- **Run logging:** Run logger records run to vault and PostgreSQL; tools_called and turns_used are extracted from the SDK result and stored.

This matches the TRD’s Level 1 architecture: one agentic loop, tools called mid-reasoning, results appended by the SDK.

### 2. Level 2: External tools and guardrails

- **Web search and Trello:** Registered in the tool registry; agent can call them when configured. Tool registry provides `list_all_tools()`, `get_agent_tools()`, `get_skills_for_tools()`.
- **Tool allowlist and constraints:** Enforced in the tools layer (see tools current-state doc). Orchestrator currently passes all registered tools; per-role allowlist from vault is not yet wired.
- **Default max_turns:** Set to 10 in config, consistent with TRD Level 2.

### 3. Level 3: Plan-then-Execute

- **Classifier:** `classify_complexity` in `planner.py` — keyword/heuristic score; **simple** requests skip planning (no extra latency).
- **Planning agent:** `generate_plan` runs a `planner` Agent with the same tools as execution, `HARLE_PLANNING_MAX_TURNS` (default 5), and optional `HARLE_PLANNING_MODEL` (default: same as execution model).
- **Validation:** `validate_plan` enforces parseable numbered steps with `[intent]` tags, min/max step counts; invalid plans fall back to Level 2.
- **Injection:** Valid plan is prepended to execution instructions via `format_plan_for_injection`. Tool outputs from the planning `Runner` pass (names and return payloads from `new_items`) are formatted by `build_planning_tool_context_section` in `sdk_result.py` and injected after the plan (or alone if validation failed but tools ran), so the execution agent does not repeat discovery work unnecessarily.
- **Revisions:** After execution, `extract_plan_revisions` collects `REVISED PLAN:` sections for vault `## Plan` content (with initial plan and revisions).
- **Logging:** `runs.routing_method` is set to `direct` or `planned`; vault result body may include a `## Plan` section when a plan or revisions exist.
- **Tests:** Unit tests in `tests/unit/test_planner.py` and `tests/unit/test_orchestrator.py`; integration tests in `tests/integration/test_plan_then_execute.py` (vault plan section, `create_run` routing, `POST /chat`, stubbed two-phase `Runner.run_sync`).

### 4. Level 4: Reflection and self-critique

- **Trigger:** `should_reflect()` in `orchestrator/reflection.py` — master switch `HARLE_REFLECTION_ENABLED`, minimum **tool-invocation** count (`HARLE_REFLECTION_MIN_TOOL_CALLS`: planning + execution runs, each `tool_call_item` counted; repeated calls to the same tool count), comma-separated keywords/roles in config, `planned` routing, OR logic. Keyword/role lists empty in config disable those rules.
- **Reflection call:** `run_reflection` builds a critic `Agent` (no tools, `max_turns=1`); JSON verdict `pass` / `improve`; malformed output fails open (pass).
- **Improvement pass:** `run_improvement` / `apply_reflection_pipeline` — at most one follow-up `Runner.run_sync` with execution tools; `HARLE_REFLECTION_IMPROVEMENT_MAX_TURNS` defaults to `HARLE_MAX_ITERATIONS`; does not re-enter reflection.
- **Think tool:** `harle.tools.think.module` — async `think(reasoning)` returning `""`; registered in `factory._register_think` when `think_tool_enabled` is true (`main.py` passes `HARLE_THINK_TOOL_ENABLED`).
- **Logging:** Vault appends `## Reflection` when triggered; `create_run` persists `reflection_triggered` / `reflection_improved`; `RunResponse` and `RunDetail` expose the same; etrace detail/step spans in `reflection.py`.
- **Tests:** `tests/unit/test_reflection.py`, `TestOrchestratorReflection` in `tests/unit/test_orchestrator.py`, `tests/integration/test_reflection.py`.

### 5. Harle-specific design (implemented parts)

- **Context once before loop:** Context Assembler runs once; its output feeds both planning and execution base instructions. No mid-loop context reassembly.
- **Tool results appendable:** Handled by the SDK; no custom logic required.
- **Thinking step:** System prompt includes an instruction to briefly state what is known, what is needed, and why calling a tool, to maintain reasoning coherence; optional `think` tool for scratchpad traces.

---

## What Is Only Partially Implemented

### 1. Guardrails

**Implemented:** `max_turns` (SDK), tool-layer constraints and allowlist.  
**Missing:** Per-run timeout, token-budget cap with optional pause, output validation (empty/repetition/artifact check). Orchestrator does not enforce TRD Layer 3 config (timeout, token budget cap, cost threshold).

### 2. Tool allowlist per agent role

Tools are filtered by the registry, but the orchestrator does not load the active agent’s allowed tools from its prompt file (or vault). All registered tools are passed to the single default agent.

### 3. Approval flow

Tools can declare `requires_approval`; the orchestrator does not pause the run, return an approval request to the client, or resume after approval. So Level 2 “approval flow for write tools” infrastructure exists in the tools layer but is not wired in the request path.

---

## What Is Not Implemented Yet

### 1. Level 5: Multi-agent handoffs

**Missing:** Agent definitions from vault (per-role instructions, tools, handoff targets), handoff declarations (e.g. Secretary ↔ Researcher), shared conversation context on handoff, Router integration for starting agent, and handoff logging.

**What this would unlock:** Composite tasks spanning roles (e.g. research then create Trello card); natural task decomposition where the LLM hands off to a specialist; security boundary so each agent only accesses its own tools.

### 2. Level 6: Adaptive strategy selection

**Missing:** Strategy selector (rules + optional LLM) that chooses direct / planned / reflective / multi-agent (or combinations) per request; per-role strategy config in prompt frontmatter; user override (e.g. `--strategy=planned`); cost-aware selection or warning.

**What this would unlock:** Simple tasks staying fast and cheap; complex tasks automatically getting planning and/or reflection; user override when the default strategy is wrong.

### 3. Level 7: Parallel execution and advanced orchestration

**Missing:** Parallel tool calls (e.g. multiple tools in one turn via async); parallel agent execution; branch-and-merge for exploratory tasks; progressive streaming of partial results; adaptive concurrency limits in config.

**What this would unlock:** Faster multi-source tasks (parallel web + dataset + Trello); higher quality on open-ended research by exploring multiple angles; better UX with progressive results instead of one long wait.

### 4. Streaming during multi-step runs

**Missing:** SSE or equivalent so the user sees tool-call notifications (“Searching Trello…”), intermediate status (“Found 23 cards, analyzing…”), and final result streaming.

**What this would unlock:** No “blank screen for 30 seconds”; better perceived performance and clarity during long runs.

---

## Key Deviations From The TRD

### Single agent, no handoffs

The TRD describes multiple agents with handoffs (Level 5). The codebase has one default agent role (`researcher`) for execution plus a **planner** `Agent` only for planning; there is no Router and no handoff mechanism.

### Agent Runner in orchestrator package

The TRD’s “HarleAgentRunner” and wrapper responsibilities are implemented across `orchestrator/orchestrator_service.py`, `orchestrator/execution.py`, `orchestrator/chat.py`, `orchestrator/finalize.py`, `orchestrator/service.py` (public re-exports), `orchestrator/runner_execution.py`, and `orchestrator/planner.py` rather than a dedicated `agents/` package. Cost tracking is not implemented; run logging is present but not the full TRD execution detail (per-tool-call timing, token/cost per turn).

### No mandatory “approve plan before run”

The TRD lists optional user approval of the plan; that is not implemented in the HTTP path.

---

## Current Assessment

Multi-step reasoning is **usable at Levels 1–4** on the OpenAI path: the agentic loop, tool use (vault, web search, Trello, optional `think`), plan-then-execute for complex requests, **reflection and optional improvement pass** when triggers match, max_turns, and run logging (including reflection metadata) are in place. The remaining gaps are **multi-agent handoffs** (Level 5), **strategy selection** (Level 6), **parallel execution** (Level 7), and **streaming** during runs.
