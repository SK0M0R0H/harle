---
title: "Harle Orchestrator — Current State"
tags: [orchestrator, current-state, architecture, fastapi, context-assembly, implementation-status]
context: global
last_updated: 2026-03-07
summary: "Tracks what the Orchestrator implements vs the TRD, and what each missing part would unlock."
---

# Harle Orchestrator — Current State

> This document compares the target design in the Orchestrator TRD with the code that exists today. The orchestrator pipeline is implemented across `src/harle/api/`, `src/harle/orchestrator/`, `src/harle/context/`, and `src/harle/logging/`, with no separate `router/`, `clarifier/`, or `agents/` packages.

Reference TRD: [Harle Orchestrator — Architecture & Functionality](../../trd/architecture/orchestrator.md)

---

## Overall Status

The Orchestrator is **partially implemented**. The request lifecycle works end-to-end: HTTP API accepts `/run` and `/chat`, the Context Assembler builds a token-budgeted system prompt (P0 + P1 + P4), the Agent Runner executes via the OpenAI Agents SDK (or legacy provider) with optional tools, and the Run Logger writes to the vault and PostgreSQL. **Missing** are: a dedicated Router (all requests use a fixed "researcher" role), the Clarifier (no ambiguity check or clarification questions), richer run logging (no clarification/routing/execution detail in the TRD shape), SSE streaming, approval flow in the request path, and several TRD guardrails and error-handling behaviours. Config covers a subset of the TRD (no timeout, token budget cap, or approval settings).

---

## Implementation Snapshot

| TRD area | Current status | Notes |
|----------|----------------|-------|
| 1. HTTP API (FastAPI) | Implemented | `api/routes.py`: POST /run, POST /chat, GET /run/{id}, GET /health. Request/response models in `api/models.py`. Additional endpoints: /init, /reindex, /search. |
| 2. Router | Not implemented | No `router/` package. Agent role is fixed as `DEFAULT_AGENT_ROLE = "researcher"`. No explicit override, context-based rules, workflow template match, or LLM fallback. |
| 3. Clarifier | Not implemented | No `clarifier/` package. No ambiguity check, no clarification questions, no round-trip before execution. |
| 4. Context Assembler | Implemented | `context/assembler.py`: P0 (prompts + policies), P1 (dataset search), P4 (conversation history). 80/20 budget, tiktoken. No P2 (external data), P3 (prior runs, memories). |
| 5. Agent Runner | Partially implemented | Execution in `orchestrator/service.py`: Agents SDK Runner when OpenAI key set, else echo provider. Single role, tools from registry, max_turns. No separate `agents/` package, no handoffs, no timeout/token-budget guardrails, no output validation. |
| 6. Tool Module Layer | Implemented | See current-state tools.md. Registry, skills, constraints; vault and web search modules. Approval attributes exist on tools; orchestrator does not pause for approval in the request path. |
| 7. Run Logger | Partially implemented | `logging/run_logger.py`: vault logs (result + optional context). `db/runs.create_run`: run_id, request, context, agent, status, files_used, tools_called, result_summary, paths, duration. No TRD-style clarification/routing/context_assembled/execution/approval_actions structure. |
| Request lifecycle | Partially implemented | run + chat flow: assemble → execute → log → return. No router or clarifier steps. |
| Conversation mode | Implemented | `db/conversations`: create_conversation, add_message, get_recent_messages. Chat path passes conversation_history to assembler. |
| SSE streaming | Not implemented | No Server-Sent Events for streaming responses. |
| Configuration | Partially implemented | `config.py` Settings: host, port, LLM provider/model, dataset path, DB URL, max_iterations, run_log_store_context. No timeout_seconds, max_tokens_per_run, approval.*, search.max_context_pages, etc. |
| Error handling | Partially implemented | Some HTTP 503/404; no LLM retry/backoff, token-budget pause, or TRD error table. |
| TRD project structure | Partially implemented | api/, context/, logging/ exist; orchestrator/ has service only. No router/, clarifier/, agents/ (runner/definitions/guardrails). Search used via engine directly, not search/client.py. |

---

## What Is Implemented

### 1. HTTP API and request/response shape

- **Endpoints:** POST `/run`, POST `/chat`, GET `/run/{run_id}`, GET `/health`, plus POST `/init`, POST `/reindex`, GET `/search`.
- **RunRequest:** `message`, `context` (work/personal), `conversation_id`.
- **RunResponse:** `run_id`, `status`, `result`, `context`, `conversation_id`, `tools_called`, `turns_used`.
- **RunDetail:** run metadata for GET /run/{id} (run_id, timestamp, user_request, context_scope, agent, status, routing_method, files_used, tools_called, result_summary, result_path, context_path, conversation_id, duration_ms).

FastAPI is used; validation and docs align with the TRD’s “first version” API.

### 2. Context Assembler (P0, P1, P4)

- **P0 (mandatory):** Loads prompts and policies from the vault; filters by context (work/personal/global); when `agent_role` is set, keeps only the matching prompt file (e.g. prompts/secretary.md for role secretary) plus all policies.
- **P1 (critical):** Calls the search engine with the user message and context; formats search results into the system prompt until the token budget is reached; excludes paths already in P0.
- **P4 (background):** In the chat path, recent conversation history is loaded from the DB and appended, trimmed to fit the remaining budget.
- **Budget:** Configurable context window (default 128k) and input ratio (default 80%); token counting via tiktoken.

This matches the TRD’s priority-based packing and 80/20 rule. P2 (external data) and P3 (prior runs, memories) are not yet wired.

### 3. Agent Runner (core loop)

- When `OPENAI_API_KEY` is set and provider is OpenAI, the orchestrator uses the **OpenAI Agents SDK**: `Agent` + `Runner.run_sync` with instructions (system prompt + tool skills + thinking instruction), tools from the registry, and `max_turns` from config.
- When no API key (or non-OpenAI provider), a **legacy provider** (e.g. EchoProvider) is used for a single generate call.
- Tool names and turn count are extracted from the SDK result and returned in `RunResponse` and persisted in `runs`.

So the agentic loop, tool use, and multi-turn reasoning are in place; the TRD’s separate “Agent Runner” and “guardrails” modules are not (logic lives in `orchestrator/service.py`).

### 4. Run Logger (vault + PostgreSQL)

- **Vault:** `log_run_to_vault` writes `logs/YYYY/MM/<run_id>_result.md` (and optionally `_context.md`) with YAML frontmatter and Markdown body, per TRD logs directory design.
- **PostgreSQL:** `create_run` inserts into `runs` with run_id, timestamp, user_request, context_scope, agent, status, files_used, tools_called, model_used, result_summary, result_path, context_path, conversation_id, duration_ms. `routing_method` is supported by the schema but currently always `None`.

### 5. Conversation mode

- New conversation: `create_conversation` with conversation_id, context_scope, agent_role.
- Continuing: `get_conversation`, `get_recent_messages`; messages are appended after each exchange via `add_message` (user and assistant); `touch_conversation` updates timestamps.
- The chat path passes `conversation_history` into the Context Assembler for P4 inclusion.

### 6. Tool integration

- The orchestrator receives a `ToolRegistry`; it calls `list_all_tools()`, `get_agent_tools(...)`, and `get_skills_for_tools(...)`.
- Instructions include tool skills and a short “thinking before tools” instruction. Tools are passed to the SDK Agent; execution goes through the registry (constraints and permissions exist in the tools layer; see tools current-state doc).

---

## What Is Only Partially Implemented

### 1. Agent Runner and guardrails

- **Implemented:** Runner with tools, max_turns (max iterations).
- **Missing:** Dedicated `agents/` package (runner, definitions, guardrails). No handoffs, no timeout, no token-budget guardrail, no output validation (empty/repetition/artifact check). Tool allowlist is effectively “all registered tools” rather than per-role allowlist from the prompt file.

### 2. Run Logger content

- **Implemented:** Persistence to vault and `runs` table with the fields above.
- **Missing:** TRD’s full log shape: `clarification` (needed, questions, answers), `routing` (agent, method, confidence), `context_assembled` (prompt_file, policies_loaded, dataset_search_results, prior_runs_referenced, total_tokens_in_context), `execution` (iterations, tool_calls array with input/output_summary/duration_ms, total_tokens_used, estimated_cost_usd), `approval_actions`. Those would require either additional columns/JSON in the DB or a separate log document.

### 3. API response vs TRD

- RunResponse has `tools_called` and `turns_used` but not `agent` or `clarification_needed`. TRD example response includes `agent` and `clarification_needed`.

### 4. Configuration

- Settings cover: host, port, LLM provider/model, dataset path, DB URL, max_iterations, run_log_store_context. Missing from TRD example: timeout_seconds, max_tokens_per_run, max_conversation_turns, search.max_results / max_context_pages, approval.require_for_write / auto_approve_read / work_context_strict, and dataset/indexer sections in the TRD layout.

### 5. Error handling

- Some failures return HTTP 503/404 with clear messages. The TRD’s error table (LLM retry/backoff, garbage output validation, tool failure handling, timeout, token budget exceeded, search empty) is only partially reflected; e.g. no retries, no token-budget pause, no “no matching documents” note in context.

---

## What Is Not Implemented Yet

### 1. Router (which agent handles this?)

**Missing:** A `router/` module that decides agent role: explicit override (e.g. “as researcher: …”), context-based keyword rules (Trello/tasks → secretary, research/report → researcher, dataset/prompts → specialist), workflow template match against the vault, and LLM fallback when rules are ambiguous.

**What this would unlock:** Correct role selection (secretary, researcher, specialist) instead of a single default; better use of role-specific prompts and tools; predictable, explainable routing.

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

### 7. Handoffs (multi-agent)

**Missing:** One agent handing off to another mid-run (e.g. Secretary → Researcher → back to Secretary). SDK support may exist; it is not wired in the orchestrator.

**What this would unlock:** Composite tasks that span roles without a single mega-agent.

### 8. Per-agent tool allowlist from vault

**Missing:** Loading the active agent’s allowed tools from its prompt file (or a linked config) and passing only those to the Runner. Currently all registered tools are passed.

**What this would unlock:** Stricter “Researcher cannot write to Trello” enforcement at the orchestrator level, matching the TRD.

### 9. TRD config sections

**Missing:** config.example.yaml and Settings for limits (timeout_seconds, max_tokens_per_run, max_conversation_turns), search (max_results, max_context_pages), approval (require_for_write, auto_approve_read, work_context_strict), and dataset/indexer as in the TRD.

**What this would unlock:** Tuning and safety without code changes; alignment with the TRD configuration story.

---

## Key Deviations From The TRD

### No router or clarifier packages

The TRD describes separate Router and Clarifier modules. The codebase has no `router/` or `clarifier/`; every request uses a fixed agent role and proceeds without clarification.

### Agent execution inside orchestrator/service.py

The TRD project structure shows `agents/runner.py`, `agents/definitions.py`, `agents/guardrails.py`. The implementation uses the OpenAI Agents SDK from within `orchestrator/service.py`; there is no separate `agents/` package. Role “definitions” (which prompt to load) are effectively handled by the Context Assembler’s P0 loading and role filter.

### Search usage

The TRD mentions a “Search Client” and project structure shows `search/client.py`. The codebase uses `harle.search.engine.SearchEngine` and `harle.search.types.SearchQuery` directly from the Context Assembler; there is no separate client wrapper.

### Run response and log shape

RunResponse omits `agent` and `clarification_needed`. Stored run data does not include the TRD’s nested clarification, routing, context_assembled, execution, and approval_actions structures.

### Single agent role

The TRD defines Secretary, Researcher, Specialist with different triggers. The implementation uses a single default role (`researcher`); routing is not implemented.

---

## Current Assessment

The Orchestrator is **usable for single-role, one-shot and multi-turn runs** with context assembly, tool use, and logging. The main gaps are **routing** (so the right agent runs), **clarification** (so vague requests are refined before execution), **approval flow** (so write/delete tools pause for user confirmation), and **richer logging and guardrails** (timeout, token cap, output validation, full TRD log shape).

The next meaningful milestones would be: (1) **Router** — implement role selection so secretary/researcher/specialist are used by rule or workflow; (2) **Clarifier** — add ambiguity check and optional question round-trip; (3) **Approval flow** — wire tool-layer `needs_approval` into the API so the client can approve/deny and the run resumes accordingly.
