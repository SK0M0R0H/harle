---
title: "Harle Orchestrator — Current State"
tags: [orchestrator, current-state, architecture, fastapi, context-assembly, implementation-status]
context: global
last_updated: 2026-03-21
summary: "Tracks what the Orchestrator implements vs the TRD, and what each missing part would unlock."
---

# Harle Orchestrator — Current State

> This document compares the target design in the Orchestrator TRD with the code that exists today. The orchestrator pipeline is implemented across `src/harle/api/`, `src/harle/orchestrator/`, `src/harle/context/`, and `src/harle/logging/`. **Router** and **multi-agent** logic live under `orchestrator/router.py` and `orchestrator/agents.py` (not separate top-level packages). There is no `clarifier/` package.

Reference TRD: [Harle Orchestrator — Architecture & Functionality](../../trd/architecture/orchestrator.md)

---

## Overall Status

The Orchestrator is **partially implemented**. The request lifecycle works end-to-end: HTTP API accepts **`POST /chat` only** for user-initiated work (database required); one-shot tasks use a new conversation with a single exchange. **Routing:** `orchestrator/router.py` selects the starting agent role (explicit `as <role>:` or keyword rules; default **assistant**). The Context Assembler builds a token-budgeted system prompt (P0 + P1 + P4) for that role. The Agent Runner executes via the OpenAI Agents SDK with **per-role tools and handoffs** when the dataset-backed assembler is available, or a single agent otherwise; legacy echo provider remains a single call without tools. The Run Logger writes to the vault and PostgreSQL, including optional **`## Handoffs`** and `runs.handoffs`. **`GET /run/{run_id}`** returns run metadata including `handoffs` when present. **Missing** are: the Clarifier, workflow-template + LLM routing fallbacks, richer run logging in the full TRD JSON shape, SSE streaming, approval flow in the request path, and several TRD guardrails. Config covers a subset of the TRD (no timeout, token budget cap, or approval settings).

---

## Implementation Snapshot

| TRD area | Current status | Notes |
|----------|----------------|-------|
| 1. HTTP API (FastAPI) | Implemented | `api/routes.py`: **POST /chat** (user tasks; requires DB), GET /run/{id}, GET /health. Request/response models in `api/models.py`. Additional endpoints: /init, /reindex, /search. |
| 2. Router | Partially implemented | `orchestrator/router.py`: explicit `as <role>:` and keyword routing to researcher, secretary, specialist, writer (default **assistant**). No workflow-template match or LLM fallback (per TRD). |
| 3. Clarifier | Not implemented | No `clarifier/` package. No ambiguity check, no clarification questions, no round-trip before execution. |
| 4. Context Assembler | Implemented | `context/assembler.py`: P0 (prompts + policies), P1 (dataset search), P4 (conversation history). 80/20 budget, tiktoken. No P2 (external data), P3 (prior runs, memories). |
| 5. Agent Runner | Partially implemented | Execution in `orchestrator/orchestrator_service.py` + `execution.py` / `chat.py` / `finalize.py` + `runner_execution.py` + `agents.py` (`service.py` re-exports): Agents SDK Runner when OpenAI key set, else echo provider. Multi-agent handoffs (Level 5) with per-role tools from `agents.ROLE_TOOL_MODULES`; optional Level 3 planning agent (`planner`) with full tool set; `max_turns` applies across the multi-agent run. Config: `HARLE_PLANNING_*`, `HARLE_PLANNED_MAX_TURNS`. No timeout/token-budget guardrails or output validation in orchestrator. |
| 6. Tool Module Layer | Implemented | See current-state tools.md. Registry, skills, constraints; vault and web search modules. Approval attributes exist on tools; orchestrator does not pause for approval in the request path. |
| 7. Run Logger | Partially implemented | `logging/run_logger.py`: vault logs (result + optional context). `## Handoffs` section when handoffs occurred. `db/runs.create_run`: includes `handoffs` JSON array. No full TRD clarification/routing/context_assembled/execution/approval_actions structure. |
| Request lifecycle | Partially implemented | Single **chat** path: create/load conversation → **route** → assemble → execute → persist messages → log → return. No clarifier step. |
| Conversation mode | Implemented | All user messages go through chat; one-shot = new conversation + single exchange. `db/conversations`: create_conversation, add_message, get_recent_messages. `conversation_history` passed to assembler (P4). |
| SSE streaming | Not implemented | No Server-Sent Events for streaming responses. |
| Configuration | Partially implemented | `config.py` Settings: host, port, LLM provider/model, dataset path, DB URL, max_iterations, run_log_store_context, Level 3 planning (`HARLE_PLANNING_ENABLED`, `HARLE_PLANNING_MODEL`, `HARLE_PLANNING_MAX_TURNS`, `HARLE_PLANNED_MAX_TURNS`). No timeout_seconds, max_tokens_per_run, approval.*, search.max_context_pages, etc. |
| Error handling | Partially implemented | Some HTTP 503/404; no LLM retry/backoff, token-budget pause, or TRD error table. |
| TRD project structure | Partially implemented | api/, context/, logging/ exist; orchestrator/ includes `router.py`, `agents.py`, `orchestrator_service.py`, `execution.py`, `chat.py`, `finalize.py`, `service.py` (re-exports), `planner.py`, `runner_execution.py`, `reflection.py`, `sdk_result.py`. No clarifier/ package. Search used via engine directly, not search/client.py. |

---

## What Is Implemented

### 1. HTTP API and request/response shape

- **Endpoints:** POST `/chat` (only path for user-initiated work; returns 503 if DB not configured), GET `/run/{run_id}`, GET `/health`, plus POST `/init`, POST `/reindex`, GET `/search`.
- **RunRequest:** `message`, `context` (work/personal), `conversation_id`.
- **RunResponse:** `run_id`, `status`, `result`, `context`, `agent`, `conversation_id`, `tools_called`, `turns_used`, reflection fields, optional `handoffs`.
- **RunDetail:** run metadata for GET /run/{id} (includes `handoffs` when stored).

FastAPI is used; validation and docs align with the TRD’s “first version” API.

### 2. Context Assembler (P0, P1, P4)

- **P0 (mandatory):** Loads prompts and policies from the vault; filters by context (work/personal/global); when `agent_role` is set, keeps only the matching prompt file (e.g. prompts/secretary.md for role secretary) plus all policies.
- **P1 (critical):** Calls the search engine with the user message and context; formats search results into the system prompt until the token budget is reached; excludes paths already in P0.
- **P4 (background):** For every chat turn, recent conversation history is loaded from the DB (when continuing) and appended, trimmed to fit the remaining budget.
- **Budget:** Configurable context window (default 128k) and input ratio (default 80%); token counting via tiktoken.

This matches the TRD’s priority-based packing and 80/20 rule. P2 (external data) and P3 (prior runs, memories) are not yet wired.

### 3. Agent Runner (core loop)

- When `OPENAI_API_KEY` is set and provider is OpenAI, the orchestrator uses the **OpenAI Agents SDK**: per-role `Agent` graphs with handoffs (`orchestrator/agents.py`) when `ToolRegistry` and `ContextAssembler` are both available; otherwise a single agent. Instructions combine system prompt (or P0-only for handoff targets) with per-role tool skills and `max_turns` from config across the whole run.
- When no API key (or non-OpenAI provider), a **legacy provider** (e.g. EchoProvider) is used for a single generate call.
- Tool names and turn count are extracted from the SDK result and returned in `RunResponse` and persisted in `runs`.

So the agentic loop, tool use, multi-turn reasoning, and multi-agent handoffs are in place; the TRD’s separate “guardrails” module is not (logic lives in `orchestrator/orchestrator_service.py`, `execution.py`, `chat.py`, `finalize.py`, `runner_execution.py`, `agents.py`, and `planner.py` for Level 3; `service.py` re-exports the public API).

### 4. Run Logger (vault + PostgreSQL)

- **Vault:** `log_run_to_vault` writes `logs/YYYY/MM/<run_id>_result.md` (and optionally `_context.md`) with YAML frontmatter and Markdown body, per TRD logs directory design.
- **PostgreSQL:** `create_run` inserts into `runs` including optional `handoffs` JSON. `routing_method` is set from the router and/or planner (`direct`, `keyword_match`, `default`, `explicit_override`, or `planned`).

### 5. Conversation mode

- **OrchestratorService.chat()** is the only entry for processing a user message (no separate `run()`).
- New conversation: `create_conversation` with conversation_id, context_scope, agent_role.
- Continuing: `get_conversation`, `get_recent_messages`; messages are appended after each exchange via `add_message` (user and assistant); `touch_conversation` updates timestamps.
- `conversation_history` is passed into the Context Assembler for P4 inclusion.

### 6. Tool integration

- The orchestrator receives a `ToolRegistry`; it calls `list_all_tools()`, `get_agent_tools(...)`, and `get_skills_for_tools(...)`.
- Instructions include tool skills and a short “thinking before tools” instruction. Tools are passed to the SDK Agent; execution goes through the registry (constraints and permissions exist in the tools layer; see tools current-state doc).

### 7. Debug tracing (Phase 1)

- `chat()` is wrapped in `etrace.span` root span **`handle_chat`** with `run_id` attributes. STEP-level entries are emitted for context assembly and agent execution completion. See [execution tracing current-state](../execution_tracing.md) for the full execution tracing module status.

---

## What Is Only Partially Implemented

### 1. Agent Runner and guardrails

- **Implemented:** Runner with per-role tools (when multi-agent path active), handoffs, max_turns across the run.
- **Missing:** Dedicated top-level `agents/` package (TRD layout). No timeout, no token-budget guardrail, no output validation (empty/repetition/artifact check) in orchestrator.

### 2. Run Logger content

- **Implemented:** Persistence to vault and `runs` table with the fields above.
- **Missing:** TRD’s full log shape: `clarification` (needed, questions, answers), `routing` (agent, method, confidence), `context_assembled` (prompt_file, policies_loaded, dataset_search_results, prior_runs_referenced, total_tokens_in_context), `execution` (iterations, tool_calls array with input/output_summary/duration_ms, total_tokens_used, estimated_cost_usd), `approval_actions`. Those would require either additional columns/JSON in the DB or a separate log document.

### 3. API response vs TRD

- `RunResponse` includes `agent` and optional `handoffs`. TRD example `clarification_needed` is not implemented.

### 4. Configuration

- Settings cover: host, port, LLM provider/model, dataset path, DB URL, max_iterations, run_log_store_context. Missing from TRD example: timeout_seconds, max_tokens_per_run, max_conversation_turns, search.max_results / max_context_pages, approval.require_for_write / auto_approve_read / work_context_strict, and dataset/indexer sections in the TRD layout.

### 5. Error handling

- Some failures return HTTP 503/404 with clear messages. The TRD’s error table (LLM retry/backoff, garbage output validation, tool failure handling, timeout, token budget exceeded, search empty) is only partially reflected; e.g. no retries, no token-budget pause, no “no matching documents” note in context.

---

## What Is Not Implemented Yet

### 1. Router extensions (workflow + LLM)

**Missing:** Workflow template match against the vault and LLM fallback when keyword rules are ambiguous (TRD layered routing steps 3–4).

**What this would unlock:** Better routing on edge cases without expanding keyword lists indefinitely.

### 2. Clarifier (is the request clear enough?)

**Missing:** A `clarifier/` module that checks ambiguity (workflow match or LLM evaluation), returns 1–3 questions when needed, and waits for user answers before running the agent. No `--no-clarify` or “skip when follow-up in conversation” logic.

**What this would unlock:** Fewer wasted runs on vague requests; “handle vague goals” as in the project requirements; a dataset of clarified requests for improving routing and templates.

### 3. SSE streaming

**Missing:** Server-Sent Events for streaming LLM output so the CLI (or other clients) can show partial results in real time.

**What this would unlock:** Better UX for long answers (e.g. research reports) without waiting for the full response.

### 4. Approval flow in the request path

**Missing:** When a write/delete tool is invoked in `propose` mode, the orchestrator does not pause the run, return an approval request to the client, and resume after user approval. Tool-layer permissions and `requires_approval` exist; the request path does not yet implement the round-trip.

**What this would unlock:** Safe write/delete from the agent with explicit user confirmation, as in the TRD.

### 5. Full run log structure (TRD shape)

**Missing:** Storing or exposing clarification, routing method/confidence, context_assembled details, per-tool-call execution detail, and approval_actions in the form described in the TRD.

**What this would unlock:** Full audit trail for debugging and Specialist agent use; cost and quality analysis; clear “why this agent” and “what was in context” answers.

### 6. Guardrails (timeout, token budget, output validation)

**Missing:** Per-run timeout; token-budget cap with optional “continue?” pause; output validation (non-empty, not repetition of input, no tool-call artifacts in final text).

**What this would unlock:** Protection against runaway cost and infinite loops; higher quality and safer responses.

### 7. TRD config sections

**Missing:** config.example.yaml and Settings for limits (timeout_seconds, max_tokens_per_run, max_conversation_turns), search (max_results, max_context_pages), approval (require_for_write, auto_approve_read, work_context_strict), and dataset/indexer as in the TRD.

**What this would unlock:** Tuning and safety without code changes; alignment with the TRD configuration story.

---

## Key Deviations From The TRD

### Router and clarifier packaging

The TRD shows top-level `router/` and `clarifier/` packages. Routing lives in `orchestrator/router.py`; there is still no clarifier module.

### Agent execution inside the orchestrator package

The TRD project structure shows a top-level `agents/` package. Multi-agent definitions and handoffs live in `orchestrator/agents.py` alongside `runner_execution.py`; there is no separate `agents/` package at `src/harle/agents/`.

### Search usage

The TRD mentions a “Search Client” and project structure shows `search/client.py`. The codebase uses `harle.search.engine.SearchEngine` and `harle.search.types.SearchQuery` directly from the Context Assembler; there is no separate client wrapper.

### Run response and log shape

`RunResponse` includes `agent` and `handoffs` (when present). Stored run data still does not include the TRD’s full nested clarification, routing confidence, context_assembled, execution, and approval_actions structures.

---

## Current Assessment

The Orchestrator is **usable for multi-role runs** (routing + handoffs), one-shot and multi-turn chat, context assembly, per-role tools, and logging including handoff metadata. The main gaps are **clarification**, **approval flow** in the request path, **router extensions** (workflow + LLM), and **richer logging and guardrails** (timeout, token cap, output validation, full TRD log shape).

The next meaningful milestones would be: (1) **Clarifier** — ambiguity check and optional question round-trip; (2) **Approval flow** — wire tool-layer approval into the API; (3) **Guardrails** — timeout, token cap, output validation.
