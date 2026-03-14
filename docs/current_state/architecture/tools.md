---
title: "Harle Tool Module Layer — Current State"
tags: [tools, current-state, architecture, implementation-status, registry, skills, security]
context: global
last_updated: 2026-03-14
summary: "Tracks what the Tool Module Layer implements vs the TRD, and what each missing part would unlock."
---

# Harle Tool Module Layer — Current State

> This document compares the target design in the Tool Module Layer TRD with the code in `src/harle/tools`. It summarises what is implemented, what is partial, and what is missing, and what each missing part would unlock.

Reference TRD: [Tool Module Layer — Architecture & Functionality](../../trd/architecture/tools.md)

---

## Overall Status

The Tool Module Layer is **substantially implemented** for core infrastructure and four real modules (vault, web search, Trello, Notion). The registry, permissions, constraints, sandbox, and skills system exist and are tested. Connections Layer integration is in place for Trello and Notion. Gaps are mainly: config-driven module loading, additional modules (scripts), per-request tool selection and approval flow wiring, and MCP.

---

## Implementation Snapshot

| TRD area | Current status | Notes |
|----------|----------------|------|
| BaseToolModule | Implemented | `base.py`: name, description, initialize, shutdown, get_tools, default_constraints, health_check. |
| Tool Registry | Implemented | `registry.py`: register_module, get_agent_tools, get_skills_for_tools, list_all_tools, shutdown_all, constraint merge, validate_tool_inputs, check_tool_permission. |
| Permissions | Implemented | `permissions.py`: OperationMode (read_only/propose/auto), fn.permission, fn.requires_approval, check_permission. |
| Constraints (Layer 3) | Implemented | `constraints.py`: ConstraintConfig, from_dict, merge, allowed_commands, blocked_patterns, paths, hosts, max_input_length, validate_inputs. |
| Sandbox (Layer 4) | Implemented | `sandbox.py`: SandboxConfig, run_sandboxed, timeout, memory, output size, subprocess limits. |
| Skills system | Implemented | `skills.py`: vault override then built-in, SkillLoaderConfig, load_module_skills, token budget, LoadedSkill. |
| Orchestrator wiring | Partially implemented | Registry is built and passed in; tools and skills are injected. Tool set is all tools, not a per-agent subset; approval gate not invoked before execution. |
| Config-driven loading | Not implemented | Modules are registered in `factory.py` by hardcoded rules (env/deps), not from `config.yaml` `tool_modules`. |
| Connections Layer in modules | Implemented | `BaseToolModule.initialize(config, connections)` accepts ConnectionRegistry; Trello, Notion, and Web Search modules use shared connections. |
| Vault module | Partially implemented | Read-only: `dataset_search`, `dataset_read_file`. No create_note, update_note, search_notes as in TRD. |
| Web Search module | Implemented | `search_web`, `search_news`, `fetch_page`; own client; skills loaded (e.g. research). |
| Trello module | Implemented | `trello/`: TrelloModule, trello_list_boards, trello_list_cards. Read-only via shared TrelloConnection. |
| Scripts module | Not implemented | No `scripts/` module (run_script, list_scripts). |
| Notion module | Implemented | `notion/`: NotionModule with notion_search, notion_read_page, notion_get_database, notion_query_database. Read-only via shared NotionConnection. |
| Twitter | Not implemented | Not present. |
| Approval flow in request path | Not implemented | Permission checks exist but orchestrator does not pause for user approval on write/delete. |
| Run Logger constraint/audit | Not verified | TRD Layer 5: log constraint results and full call details; not confirmed in this pass. |
| config.example.yaml tool_modules | Partial | Short comment only; no full tool_modules with constraints, skills, mode per module. |
| MCP (export/import) | Not implemented | No mcp_provider.py or mcp_export.py. |
| Tests | Implemented | test_tools.py, test_tools_skills.py, test_tools_vault.py, test_tools_security.py, test_tools_web_search.py. |

---

## What Is Implemented

### 1. BaseToolModule and registry

- **BaseToolModule** in `base.py`: `name`, `description`, `initialize(config)`, `shutdown()`, `get_tools()`, `default_constraints()`, `health_check()`. Matches TRD except `initialize` does not take a `ConnectionRegistry` (see deviations).
- **ToolRegistry** in `registry.py`: registers modules with mode, constraints (merged with module defaults), and skill names; indexes tools; builds cached `FunctionTool` objects via SDK introspection; provides `get_agent_tools`, `get_skills_for_tools`, `list_all_tools`, `list_modules`, `shutdown_all`, `check_tool_permission`, `validate_tool_inputs`, `get_module_constraints`.

### 2. Permissions

- **permissions.py**: `OperationMode` (read_only, propose, auto), `get_tool_permission`, `get_requires_approval`, `check_permission`. Tools set `permission` and `requires_approval` as function attributes; registry exposes `check_tool_permission(tool_name)`.

### 3. Security: constraints and sandbox

- **constraints.py**: `ConstraintConfig` with `from_dict`, `merge` (field-level override), and validation for allowed_commands, blocked_patterns, allowed_paths, blocked_paths, allowed_hosts, max_input_length. `ConstraintViolation` and `validate_inputs` used by the registry before execution.
- **sandbox.py**: `SandboxConfig`, `run_sandboxed` with timeout, memory limit, output size limit, subprocess limit, working directory. Ready for a scripts module.

### 4. Skills

- **skills.py**: `SkillLoaderConfig` (user_skills_dir, max_tokens_per_module), resolution order vault → built-in, `load_module_skills`, `LoadedSkill`, token truncation. Registry loads skills per module at registration and returns them via `get_skills_for_tools`.

### 5. Modules in use

- **Vault**: `VaultModule` with `dataset_search` and `dataset_read_file`; receives search_engine and dataset_reader from factory; read-only; no skills registered in factory.
- **Web Search**: `WebSearchModule` with `search_web`, `search_news`, `fetch_page`; uses shared TavilyConnection via `connections.get("tavily")`; skills `["research"]` registered.
- **Trello**: `TrelloModule` with `trello_list_boards` and `trello_list_cards`; uses shared TrelloConnection via `connections.get("trello")`; skills `["read_sequence"]` registered.
- **Notion**: `NotionModule` with `notion_search`, `notion_read_page`, `notion_get_database`, `notion_query_database`; uses shared NotionConnection via `connections.get("notion")`; skills `["usage"]` registered. Two-step property resolution for database queries. All tools read-only.
- **Dummy**: test module with read/create/delete and permission attributes.

### 6. Factory and orchestrator

- **factory.py**: `build_connections()` creates a shared `ConnectionRegistry` from env vars (Tavily, Trello, Notion). `build_tool_registry(search_engine=..., dataset_reader=..., connections=...)` registers vault when dataset backends exist, web_search when Tavily is configured, trello when Trello credentials are set, notion when `NOTION_API_TOKEN` is set. Registry is built without reading `config.yaml` `tool_modules` or `tool_skills`.
- **Orchestrator**: receives `tool_registry`, uses `list_all_tools()` and `get_agent_tools(all_tool_names)`, `get_skills_for_tools(all_tool_names)` so all registered tools and their skills are given to the agent.

### 7. Tests

- Unit tests cover registry, permissions, constraints, sandbox, skills, vault tools, web search module. No integration test confirmed for full request-path tool execution in this pass.

---

## What Is Partially Implemented

### BaseToolModule and Connections

TRD specifies `initialize(self, config, connections: ConnectionRegistry | None = None)`. Current signature is `initialize(self, config: dict)`. So the **Connections Layer** (shared API clients per service) is not used: web_search uses its own client; there is no `connections.get("tavily")` or `connections.get("trello")`.

### Config-driven module loading

TRD: Orchestrator reads `config.yaml` → `tool_modules`; for each enabled module, import class, call `initialize(config, connections)`, `health_check()`, then `register_module`. Current: `build_tool_registry` is hardcoded to vault (when backends present) and web_search (when `TAVILY_API_KEY` set). No `tool_modules` section drives which modules load or their config (mode, skills, constraints).

### Orchestrator tool selection and approval

TRD: per request, Orchestrator selects a subset of tools (e.g. from agent prompt tools-allowlist, request context, cap 5–15). Current: orchestrator passes **all** registered tools to the agent. TRD: for tools with `requires_approval` in propose mode, pause and show user "Approve? [y/n]". Current: `check_tool_permission` exists but is not invoked in the request path to block or pause execution; approval flow is not wired.

### Vault module scope

TRD vault tools include read_note, create_note, update_note, search_notes (and conventions skill). Current vault exposes only `dataset_search` and `dataset_read_file` (read-only dataset access). So vault is a useful subset but not the full CRUD + search surface described in the TRD.

### config.example.yaml

TRD and “Phase 7” describe a full `tool_modules` example with per-module enabled, connection, mode, skills, constraints. Current example has only a short comment under “Tool modules”; no full structure.

---

## What Is Not Implemented

### 1. Connections Layer — config-driven

- **Missing:** Reading connections from `config.yaml` instead of environment variables. The Connections Layer is functional but env-var-based.
- **Unlocks:** Credential management and rotation via config; per-connection rate limits.

### 2. Config-driven tool module loading

- **Missing:** Reading `tool_modules` (and optionally `connections`, `tool_skills`) from config; iterating enabled modules; importing module class by name; calling initialize with config and connections; health_check; register_module with config-derived mode, constraints, skill_names; using `tool_skills.user_skills_dir` in SkillLoaderConfig.
- **Unlocks:** Enable/disable and configure modules without code changes; different deployments with different module sets; vault skill overrides and token budgets from config.

### 3. Per-request tool selection

- **Missing:** Logic that selects a subset of tools per run (e.g. from agent prompt tools-allowlist, request content, and a low cap like 5–15 tools) and calls `get_agent_tools(selected_names)` and `get_skills_for_tools(selected_names)`.
- **Unlocks:** Smaller, relevant tool sets per agent/request; lower token use and clearer behaviour; support for “Secretary vs Researcher” tool sets.

### 4. Approval flow in the request path

- **Missing:** Before executing a tool call, orchestrator/agent runner calls `check_tool_permission`; when `needs_approval` is true and mode is propose, pause and present the planned call to the user; only execute after approval (or skip).
- **Unlocks:** Safe use of write/delete tools; user control over destructive or sensitive operations as in the TRD.

### 5. Scripts module

- **Missing:** `scripts/module.py`, `scripts/tools.py` (run_script, list_scripts), `scripts/skills/safety.md`; registration with default_constraints and sandbox execution; constraint checks and run_sandboxed in the execution path.
- **Unlocks:** Execution of user scripts from the agent with bounded risk (allowlists, blocked patterns, time/memory limits).

### 6. Vault module write tools

- **Missing:** create_note, update_note (and possibly search_notes if different from dataset_search) with path constraints and permissions.
- **Unlocks:** Agent ability to create/update vault content under constraints and approval.

### 7. Run Logger audit (Layer 5)

- **Missing (or not confirmed):** Logging each tool call with tool name, module, inputs, constraint check results, approval status, output summary, duration, resource usage.
- **Unlocks:** Audit trail for safety and debugging; basis for “Specialist analyzes tool logs” use case.

### 8. config.example.yaml tool_modules and tool_skills

- **Missing:** Full `tool_modules` with at least vault, web_search, scripts (when added), with enabled, mode, skills, constraints; `tool_skills` with user_skills_dir and max_tokens_per_module.
- **Unlocks:** Clear, copy-paste defaults and secure constraint examples for new deployments.

### 9. MCP compatibility (Phase 8)

- **Missing:** `mcp_provider.py` (consume external MCP servers as tools), `mcp_export.py` (expose Harle modules as MCP server).
- **Unlocks:** Use of external MCP tools (e.g. GitHub) and use of Harle tools from Cursor/Claude.

---

## Key Deviations From the TRD

- **Connections:** Connections Layer is implemented and used by Trello, Notion, and Web Search modules. However, it is env-var-driven, not config-driven as in the TRD.
- **Module discovery:** Registration is hardcoded in the factory by env/deps; TRD describes config-driven discovery from `tool_modules`.
- **Tool set:** All registered tools are passed to every request; TRD describes a selected subset per agent/request.
- **Approval:** Permission and needs_approval are implemented at the registry level but are not used in the execution path to gate or pause tool calls.
- **Vault tools:** Only read-only dataset tools exist; TRD also describes create_note, update_note, search_notes and a conventions skill.

---

## Current Assessment

The Tool Module Layer has a **solid core**: base, registry, permissions, constraints, sandbox, and skills are in place and tested, and four modules (vault read-only, web search, Trello, Notion) are wired through the factory into the orchestrator with shared connections. The main gaps are **configuration and integration**: config-driven loading, per-request tool selection, approval flow in the request path, scripts module, and MCP. Completing config.example.yaml would align the implementation with the TRD’s phased plan and unlock the remaining scenarios.
