---
title: "Multi-Step Reasoning — Current State"
tags: [multi-step-reasoning, current-state, architecture, agentic-loop, tool-use, implementation-status, planning]
context: global
last_updated: 2026-03-21
summary: "Tracks what multi-step reasoning implements vs the TRD (levels 0–7). Levels 1–5 are implemented on the OpenAI Agents SDK path (including multi-agent handoffs); levels 6–7 are not."
---

# Multi-Step Reasoning — Current State

> This document compares the target design in the Multi-Step Reasoning TRD with the code that exists today. Implementation lives in `src/harle/orchestrator/` (agentic loop, Runner, planning, max_turns) and `src/harle/tools/` (tool registry, vault, web search, Trello). It describes what is implemented, what is partial, and what is missing, and what each missing part would unlock.

Reference TRD: [Multi-Step Reasoning — Design & Incremental Implementation Plan](../../trd/architecture/multi_step_reasoning.md). See also [Orchestrator TRD](../../trd/architecture/orchestrator.md) and [Tools TRD](../../trd/architecture/tools.md).

---

## Overall Status

**Levels 1–5 are implemented for the OpenAI Agents SDK path.** The orchestrator uses the OpenAI Agents SDK `Runner` with per-role `Agent` objects (instructions from Context Assembler, tools filtered by role from the registry), `max_turns` from config (default 10) **across the entire multi-agent run**, and run logging. The tool-calling loop (ReAct-style) works: the LLM can call dataset tools, web search, and Trello during a run and see results in subsequent turns. **Level 3 (plan-then-execute)** adds a heuristic complexity classifier; for **complex** requests it runs a **planning agent** (same tools as execution, separate `max_turns` budget) that may call tools before emitting a numbered plan; the validated plan is injected into execution instructions; optional `REVISED PLAN:` blocks in the final answer are parsed for vault logging. **Level 4 (reflection and self-critique)** runs after execution when triggers match: `orchestrator/reflection.py` (`should_reflect`, `run_reflection`, `run_improvement`, `apply_reflection_pipeline`), optional improvement pass (at most one) with the starting role’s tools in multi-agent mode, fail-open JSON parsing, vault `## Reflection` section, DB columns `reflection_triggered` / `reflection_improved`, `RunResponse` fields, and config keys `HARLE_REFLECTION_*` plus `HARLE_THINK_TOOL_ENABLED`. The **think** tool (`tools/think/`) is a no-op scratchpad registered via `build_tool_registry(..., think_tool_enabled=...)`. **Level 5 (multi-agent handoffs)** is implemented: `orchestrator/router.py` selects the starting role; `orchestrator/agents.py` builds a handoff graph (Researcher, Secretary, Specialist, Writer) with SDK `handoff()` and structured `HandoffReason`; `ContextAssembler.load_role_prompt()` supplies P0-only instructions for non-starting roles; handoffs are logged to the vault (`## Handoffs`) and `runs.handoffs` (JSON). **Levels 6–7 are not implemented:** adaptive strategy selection or parallel execution. Streaming during multi-step runs is not implemented. **Existing PostgreSQL databases** may need `ALTER TABLE runs ADD COLUMN handoffs JSONB` (nullable) if the schema predates Level 5; earlier nullable columns (`reflection_*`) may also be missing on old installs.

---

## Implementation Snapshot

| TRD area | Current status | Notes |
|----------|----------------|-------|
| Level 0: Baseline (single LLM call) | Superseded | Legacy provider path still exists when no OpenAI key; primary path is Level 1+. |
| Level 1: Basic tool-calling loop | Implemented | Agents SDK `Runner.run_sync`, `Agent` with instructions + tools, `max_turns` (config `max_iterations`), run logging per run; vault + dataset tools. |
| Level 2: External tools | Implemented | Web search and Trello modules in tool registry; tool allowlist and constraints in tools layer; default `max_iterations=10`. Approval infrastructure exists on tools; orchestrator does not pause for approval in request path. |
| Level 3: Plan-then-Execute | Implemented | `orchestrator/planner.py`: `classify_complexity` (heuristics), `generate_plan` (planning `Agent` + tools + `HARLE_PLANNING_MAX_TURNS`), `validate_plan`, injection via `format_plan_for_injection` plus `sdk_result.build_planning_tool_context_section` (planning tool outputs for execution), `extract_plan_revisions` for logs. `orchestrator/runner_execution.py` orchestrates planning then execution. Config: `HARLE_PLANNING_ENABLED`, `HARLE_PLANNING_MAX_TURNS`, `HARLE_PLANNED_MAX_TURNS`; planning model comes from the planner tier (`HARLE_MODEL_PLANNER`). Simple requests skip planning. Failure modes: fall back to Level 2 (no extra user-visible error). |
| Level 4: Reflection and self-critique | Implemented | `reflection.py` + `runner_execution.py` post-execution pipeline; triggers (OR: tool count, keywords, `routing_method==planned`, role); reflection `Agent` (`max_turns=1`, no tools); improvement `Agent` reuses execution tools; `ThinkToolModule` + factory; `HARLE_REFLECTION_*`, `HARLE_THINK_TOOL_ENABLED`. Existing DBs: add nullable `reflection_triggered`, `reflection_improved` on `runs` if upgrading. |
| Level 5: Multi-agent handoffs | Implemented | `orchestrator/router.py`, `orchestrator/agents.py`, `runner_execution.py`: SDK handoffs, per-role tools, `max_turns` across the run; vault + DB handoff logging. |
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
- **Planning agent:** `generate_plan` runs a `planner` Agent with the same tools as execution, `HARLE_PLANNING_MAX_TURNS` (default 5), using the planner tier model (`HARLE_MODEL_PLANNER`).
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

### 5. Level 5: Multi-agent handoffs

- **Router:** `orchestrator/router.py` — explicit `as <role>:` override and keyword routing to researcher, secretary, specialist, or writer; default **assistant** (generic Harle assistant). Specialist keywords target dataset/prompts/agent logs/system improvement — **not** the word “Harle” alone (avoids misrouting vocative phrasing like “Harle, summarize …”). **Continuing multi-turn chats** reuse `conversations.agent_role` (no fresh keyword routing on every message) unless the user uses `as <role>:`, which updates the stored role.
- **Agents:** `orchestrator/agents.py` — `KNOWN_ROLES`, `HANDOFF_GRAPH` (complete: every role may hand off to every other role), `build_execution_agents()` with SDK `handoff(..., input_type=HandoffReason)`; fixed-point wiring so circular targets reference live `Agent` instances. Per-role tool module lists default in `orchestrator/role_tool_modules.py` and can be overridden via JSON (`HARLE_ROLE_TOOL_MODULES_PATH` or `<dataset>/role_tool_modules.json`).
- **Execution:** `runner_execution.run_agent_execution` accepts per-role `role_instructions`, `multi_agent`, `handoff_records_out`, `routing_method_from_router`; `max_turns` applies to the whole run.
- **Context:** `ContextAssembler.load_role_prompt()` for P0-only text for non-starting roles; starting role uses full `assemble()` output.
- **Logging:** `HandoffRecord` in state; vault `## Handoffs` via `run_logger`; `runs.handoffs` JSON; `RunResponse` / `RunDetail` `handoffs` field.
- **Tests:** `tests/unit/test_router.py`, `tests/unit/test_agents.py`.

### 6. Harle-specific design (implemented parts)

- **Context once before loop:** Context Assembler runs once; its output feeds both planning and execution base instructions. No mid-loop context reassembly.
- **Tool results appendable:** Handled by the SDK; no custom logic required.
- **Thinking step:** System prompt includes an instruction to briefly state what is known, what is needed, and why calling a tool, to maintain reasoning coherence; optional `think` tool for scratchpad traces.

---

## What Is Only Partially Implemented

### 1. Guardrails

**Implemented:** `max_turns` (SDK), tool-layer constraints and allowlist.  
**Missing:** Per-run timeout, token-budget cap with optional pause, output validation (empty/repetition/artifact check). Orchestrator does not enforce TRD Layer 3 config (timeout, token budget cap, cost threshold).

### 2. Tool allowlist per agent role

**Implemented for the OpenAI path:** `orchestrator/role_tool_modules.py` (defaults + optional JSON) maps each role to tool modules; `ToolRegistry.get_module_tool_names` and per-role instruction building restrict tools and skills per agent. The legacy echo provider path does not use tools.

### 3. Approval flow

Tools can declare `requires_approval`; the orchestrator does not pause the run, return an approval request to the client, or resume after approval. So Level 2 “approval flow for write tools” infrastructure exists in the tools layer but is not wired in the request path.

---

## What Is Not Implemented Yet

### 1. Level 6: Adaptive strategy selection

**Missing:** Strategy selector (rules + optional LLM) that chooses direct / planned / reflective / multi-agent (or combinations) per request; per-role strategy config in prompt frontmatter; user override (e.g. `--strategy=planned`); cost-aware selection or warning.

**What this would unlock:** Simple tasks staying fast and cheap; complex tasks automatically getting planning and/or reflection; user override when the default strategy is wrong.

### 2. Level 7: Parallel execution and advanced orchestration

**Missing:** Parallel tool calls (e.g. multiple tools in one turn via async); parallel agent execution; branch-and-merge for exploratory tasks; progressive streaming of partial results; adaptive concurrency limits in config.

**What this would unlock:** Faster multi-source tasks (parallel web + dataset + Trello); higher quality on open-ended research by exploring multiple angles; better UX with progressive results instead of one long wait.

### 3. Streaming during multi-step runs

**Missing:** SSE or equivalent so the user sees tool-call notifications (“Searching Trello…”), intermediate status (“Found 23 cards, analyzing…”), and final result streaming.

**What this would unlock:** No “blank screen for 30 seconds”; better perceived performance and clarity during long runs.

---

## Key Deviations From The TRD

### Router scope

The TRD describes workflow-template matching and an LLM fallback for routing. The implementation provides explicit override (`as <role>:`) and keyword rules only (no workflow templates, no LLM classifier).

### Agent Runner in orchestrator package

The TRD’s “HarleAgentRunner” and wrapper responsibilities are implemented across `orchestrator/orchestrator_service.py`, `orchestrator/execution.py`, `orchestrator/chat.py`, `orchestrator/finalize.py`, `orchestrator/service.py` (public re-exports), `orchestrator/runner_execution.py`, and `orchestrator/planner.py` rather than a dedicated `agents/` package. Cost tracking is not implemented; run logging is present but not the full TRD execution detail (per-tool-call timing, token/cost per turn).

### No mandatory “approve plan before run”

The TRD lists optional user approval of the plan; that is not implemented in the HTTP path.

---

## Current Assessment

Multi-step reasoning is **usable at Levels 1–5** on the OpenAI path: the agentic loop, per-role tools, multi-agent handoffs with logging, tool use (vault, web search, Trello, optional `think`), plan-then-execute for complex requests, **reflection and optional improvement pass** when triggers match, max_turns across the full run, and run logging (reflection + handoffs metadata). The remaining gaps are **strategy selection** (Level 6), **parallel execution** (Level 7), and **streaming** during runs.
