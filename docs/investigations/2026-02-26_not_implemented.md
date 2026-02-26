---
title: "Not-Implemented Features — Gap Analysis Across Documentation"
tags: [investigation, gap-analysis, roadmap, implementation-status, planning]
context: global
last_updated: 2026-02-26
summary: "Catalogues all proposed, designed, or planned features found in docs/ that are not yet implemented in the codebase, grouped by direction with per-item priorities."
---

# Not-Implemented Features — Gap Analysis

> Audit date: 2026-02-26. This document catalogues features, designs, and plans described in `docs/` that have no working implementation in the codebase. Findings are grouped by direction. Each item has its own priority (1 = top, 5 = lowest) with a rationale.

---

## How priorities were assigned

| Priority | Meaning |
|----------|---------|
| **1** | Blocks core value or has a broken reference in code. Without this, the system fails at its primary job or has a code-level defect. |
| **2** | Enables the stated "Big Goal" or provides a major quality improvement. High impact, clear path to implement. |
| **3** | Important for production quality, safety, or usability. Needed eventually but doesn't block current development. |
| **4** | Optimisation or second-order improvement. Depends on earlier work being done first, or provides incremental gains. |
| **5** | Long-term vision, far-future, or explicitly deferred. Nice-to-have with no current demand. |

---

## Direction 1: Search & Retrieval Improvements

The current search engine (`src/harle/search/engine.py`) is a basic keyword scorer that reads the file index on every query. Three core search modules are stubs (`ranker.py`, `query_expander.py`, `whoosh_index.py`). Better retrieval is the foundation everything else builds on.

### 1.1 Whoosh Full-Text Search (BM25)

**Priority: 1** — Foundational upgrade; the naive keyword scorer is the single biggest retrieval bottleneck.

`search/whoosh_index.py` is a stub. The plan is to replace the naive keyword scorer with a Whoosh inverted index using BM25 scoring and field-level boosts (title 2×, tags 1.5×). This would dramatically improve recall and ranking quality over the current approach.

Sources: [main_challenges.md](../trd/main_challenges.md), [data.md](../trd/architecture/data.md)

### 1.2 Query Expansion

**Priority: 1** — Documented as a concrete retrieval failure; follow-up questions are broken today.

`search/query_expander.py` is a stub. Designed to enrich search queries with synonyms, role-specific terms, and terms derived from conversation history. Without it, follow-up questions fail when they don't repeat keywords from earlier turns.

Sources: [main_challenges.md](../trd/main_challenges.md), [2026-02-19.md](./2026-02-19.md)

### 1.3 Conversation-Aware Retrieval

**Priority: 1** — Documented as a concrete bug; every multi-turn session is degraded.

The search engine receives only the current user message — no conversation history. Follow-up questions like "when will it be possible?" fail because the system can't derive topic context from prior turns. This was documented as a concrete retrieval failure.

Sources: [2026-02-19.md](./2026-02-19.md), [agent_history_hallucination.md](../research/agent_history_hallucination.md)

### 1.4 Multi-Source Result Ranking (RRF)

**Priority: 2** — Needed as soon as Whoosh or pgvector lands; prerequisite for hybrid search.

`search/ranker.py` is a stub. Reciprocal Rank Fusion is designed to combine rankings from multiple retrievers (keyword, semantic, metadata) into a single sorted list. Needed as soon as a second retriever (Whoosh or pgvector) is added.

Sources: [main_challenges.md](../trd/main_challenges.md), [openclaw_analysis.md](../research/openclaw_analysis.md)

### 1.5 Semantic Search (pgvector)

**Priority: 2** — Large impact but requires embedding infrastructure; complements keyword search.

The `embeddings` table is designed in `data.md` and `db/embeddings.py` is a stub. Planned as a vector-based retriever complementing keyword search. Required for handling queries where user and document share no keywords.

Sources: [data.md](../trd/architecture/data.md), [main_challenges.md](../trd/main_challenges.md), [2026-02-19.md](./2026-02-19.md)

### 1.6 Contextual Chunk Enrichment

**Priority: 2** — Proven −49% retrieval failures (Anthropic research); high-value, moderate effort.

Chunks should be enriched with heading paths, context summaries, and metadata before indexing. Based on Anthropic's research (−49% retrieval failures). Not implemented — the indexer stores raw content without enrichment.

Sources: [main_challenges.md](../trd/main_challenges.md), [data_layer_best_practices.md](../trd/architecture/data_layer_best_practices.md)

### 1.7 Reranking Step

**Priority: 3** — Precision improvement; meaningful only after core retrieval pipeline works.

A cross-encoder or lightweight LLM re-scoring of top ~20 candidates before final selection. Designed to improve precision after the initial retrieval pass.

Sources: [main_challenges.md](../trd/main_challenges.md), [openclaw_analysis.md](../research/openclaw_analysis.md)

### 1.8 Section-Level Chunking

**Priority: 3** — Matters more as the dataset grows; current small dataset is manageable as whole files.

Files over 2,000 tokens should be chunked at H2 boundaries with cascading heading metadata. Currently, files are indexed as whole units.

Source: [main_challenges.md](../trd/main_challenges.md)

### 1.9 Context-Position Optimization

**Priority: 3** — Optimisation that requires P2/P3 context tiers to exist first.

Exploit the U-shaped attention pattern: place P0 (prompts, policies) at the beginning and P3/P4 (memories, conversation) at the end of the context window. The Context Assembler packs by priority tier but doesn't optimize for position.

Sources: [main_challenges.md](../trd/main_challenges.md), [agent_history_hallucination.md](../research/agent_history_hallucination.md)

### 1.10 Adaptive Relevance Thresholds

**Priority: 4** — Fine-tuning; the fixed threshold works acceptably for the current dataset size.

Dynamic minimum relevance score based on dataset size and query characteristics. Currently, all results above a fixed threshold are included.

Source: [main_challenges.md](../trd/main_challenges.md)

### 1.11 Accurate Token Counting in Indexer

**Priority: 4** — Minor accuracy gain; the `len // 4` estimate is acceptable for now.

The indexer estimates tokens with `len(raw_content) // 4` instead of using `tiktoken`. This affects budget calculations and chunk sizing.

Source: [main_challenges.md](../trd/main_challenges.md)

---

## Direction 2: Agent Roles & Routing

The "Big Goal" in `current_goal.md` is to have three agent roles — Researcher, Secretary, Specialist. None exist yet. The orchestrator currently makes a single-path LLM call with no routing or role selection.

### 2.1 Router (Agent Routing Logic)

**Priority: 1** — Gateway to all multi-agent functionality; everything in this direction depends on it.

Designed as a layered system: explicit user override → context-based rules → keyword matching → LLM fallback. No routing logic exists — every request goes through the same path.

Source: [orchestrator.md](../trd/architecture/orchestrator.md)

### 2.2 Clarifier

**Priority: 3** — Improves interaction quality but the system functions without it.

Ambiguity detection module that asks 1–3 targeted questions before proceeding when the user's intent is unclear. Designed with LLM-based evaluation and workflow template matching. Not implemented.

Source: [orchestrator.md](../trd/architecture/orchestrator.md)

### 2.3 Researcher Role

**Priority: 2** — One of the three stated "Big Goal" roles; provides structured research output.

Uses company-related dataset materials and internet search, returns structured reports as files. Defined as a primary agent role.

Source: [current_goal.md](../trd/current_goal.md)

### 2.4 Secretary Role

**Priority: 2** — The general-purpose role; most immediately useful of the three.

Uses the full dataset, internet search, Trello integration; updates dataset; works via multi-turn chat. The general-purpose assistant role.

Source: [current_goal.md](../trd/current_goal.md)

### 2.5 Specialist Role

**Priority: 3** — Self-maintenance role; less urgent than Researcher/Secretary since the system is small.

Monitors agent logs, maintains the dataset (versioning, quality, cleanup), does internet search for self-improvement. The system's self-maintenance agent.

Source: [current_goal.md](../trd/current_goal.md)

### 2.6 Multi-Agent Handoffs (Level 5)

**Priority: 4** — Depends on all roles existing first; complex coordination not needed early.

One agent hands off to another mid-execution with conversation context carryover. Requires agent definitions from vault, handoff declarations, and Router integration. Part of the multi-step reasoning roadmap but not yet implemented.

Source: [multi_step_reasoning.md](../trd/architecture/multi_step_reasoning.md)

---

## Direction 3: Memory & Conversation Management

The system currently has no working memory layer and no conversation summarisation. `db/memories.py` is a stub. Without memory management, the system can't learn user preferences, accumulates stale data, and is vulnerable to hallucination from old context.

### 3.1 Memories CRUD

**Priority: 2** — Blocks all memory-dependent features; the schema exists but no code reads or writes.

`db/memories.py` is a stub. The schema includes confidence scores and provenance (`source_run_id`), but no code reads or writes memories. This blocks all memory-dependent features.

Source: [main_challenges.md](../trd/main_challenges.md)

### 3.2 Context Assembly P2/P3 Tiers

**Priority: 2** — Key for richer context; P2 (external data) and P3 (memories) are missing from assembly.

The Context Assembler implements P0 (prompts/policies), P1 (search results), and P4 (conversation history). P2 (external data from tools) and P3 (memories, prior runs) are documented but not yet wired.

Source: [orchestrator.md](../trd/architecture/orchestrator.md), [main_challenges.md](../trd/main_challenges.md)

### 3.3 Conversation Summary Generation

**Priority: 2** — Prevents hallucination drift in long sessions; the field exists but isn't computed.

The `conversations` table has a `summary` field but no mechanism to compute or refresh it. Designed as periodic summarisation every N turns with meta-summaries every M summaries.

Sources: [main_challenges.md](../trd/main_challenges.md), [agent_history_hallucination.md](../research/agent_history_hallucination.md)

### 3.4 Memory Lifecycle Management (Hot/Warm/Cold)

**Priority: 4** — Optimisation over working memories; needs the CRUD layer (3.1) first.

Three-tier architecture: hot (<24h, full detail), warm (1–30 days, summarised), cold (>30 days, consolidated). Prevents unbounded memory growth and keeps retrieval relevant.

Sources: [main_challenges.md](../trd/main_challenges.md), [agent_history_hallucination.md](../research/agent_history_hallucination.md)

### 3.5 Conflict Detection

**Priority: 3** — Important for answer accuracy but needs retrieval improvements (Direction 1) first.

Compare retrieved context chunks for contradictions before injecting them into the prompt. Currently the Context Assembler packs results by priority without checking for conflicts.

Sources: [main_challenges.md](../trd/main_challenges.md), [agent_history_hallucination.md](../research/agent_history_hallucination.md)

### 3.6 Verification Before Persisting Agent Outputs

**Priority: 3** — Safety layer for write operations; needs write tools (Direction 5) to be active first.

Self-consistency or NLI-based checks against existing data before writing agent outputs to memory or dataset. No automated consistency checking exists.

Sources: [main_challenges.md](../trd/main_challenges.md), [agent_history_hallucination.md](../research/agent_history_hallucination.md)

### 3.7 Temporal Decay for Memory Recency

**Priority: 4** — Search optimisation; not critical while the dataset is small and mostly current.

Apply exponential decay to search results based on age, with exemptions for "evergreen" files like prompts and policies. Keeps recent information weighted higher.

Source: [openclaw_analysis.md](../research/openclaw_analysis.md)

---

## Direction 4: Data Pipeline & Dataset Quality

Dataset quality directly affects retrieval quality. Several maintenance features — auto-generated metadata, sync, validation — are designed but not built. `dataset/sync.py` and `indexing/summarizer.py` are stubs.

### 4.1 Auto-Generated Metadata Pipeline

**Priority: 2** — Significantly improves search via richer index fields; the stub is ready.

`indexing/summarizer.py` is a stub. Planned to use an LLM (e.g., GPT-4o-mini) to generate summaries, key entities, and "questions answered" fields during indexing. This metadata improves both search relevance and context assembly.

Sources: [main_challenges.md](../trd/main_challenges.md), [data.md](../trd/architecture/data.md)

### 4.2 Git-Based Dataset Sync

**Priority: 2** — Required for multi-device use and server deployment.

`dataset/sync.py` is a stub. The server should pull the latest dataset on startup and at regular intervals. Currently, the dataset is only read from the local filesystem without sync.

Sources: [main_challenges.md](../trd/main_challenges.md), [data.md](../trd/architecture/data.md)

### 4.3 Dataset Quality Assessment Tool

**Priority: 3** — Useful maintenance tool; part of the Specialist role's responsibilities.

A tool that reports missing frontmatter, missing tags, oversized files, duplicates, and stale dates. Designed as part of the Specialist role's responsibilities.

Source: [main_challenges.md](../trd/main_challenges.md)

### 4.4 Dataset Writer with Approval Logic

**Priority: 3** — Safety for write operations; current writer only handles logs.

`dataset/writer.py` currently only writes log files. The full design includes approval policies: auto-approve for `logs/`, require confirmation for other directories, always require confirmation for `prompts/` and `policies/`.

Source: [main_challenges.md](../trd/main_challenges.md)

### 4.5 File Format Validation

**Priority: 4** — Nice-to-have; manual discipline works at current dataset size.

Rules for dataset files are documented in `data_layer_best_practices.md` but no validation code enforces them. Files can violate conventions without any automated check.

Source: [main_challenges.md](../trd/main_challenges.md)

### 4.6 Ingestion Pipelines

**Priority: 4** — Depends on external integrations (Trello, email) being built first.

Convert external sources (Trello exports, email summaries, bookmarks) into structured Markdown for the dataset. Part of the broader integration vision.

Source: [main_challenges.md](../trd/main_challenges.md)

### 4.7 Tagging Assistance

**Priority: 4** — Convenience feature; small dataset is manageable with manual tagging.

Auto-suggest tags for new files based on content and existing tag vocabulary. Designed to keep the tagging system consistent as the dataset grows.

Source: [main_challenges.md](../trd/main_challenges.md)

---

## Direction 5: Tool Modules & Integrations

The tool infrastructure (base, registry, permissions, constraints, sandbox) is implemented. Web search works via Tavily. But most planned tool modules are missing. Without Vault and Trello modules, the Secretary and Researcher roles can't function as designed.

### 5.1 Vault Tool Module

**Priority: 1** — Referenced in `tools/factory.py` but missing; the import would fail at runtime. A code-level defect.

Designed to provide `read_note`, `create_note`, `update_note`, `search_notes` tools for interacting with the dataset. The factory tries to register it but the module directory doesn't exist.

Source: [tools.md](../trd/architecture/tools.md)

### 5.2 Trello Module

**Priority: 2** — Required for the Secretary role's task management capabilities.

`search_cards`, `create_card`, `move_card` tools. Required for the Secretary role's task management capabilities. Not implemented.

Source: [tools.md](../trd/architecture/tools.md)

### 5.3 Scripts Module

**Priority: 3** — Useful for automation; security sandbox already exists to support it.

`run_script`, `list_scripts` tools with security sandbox enforcement. Must not be built before the security layer (which is implemented).

Source: [tools.md](../trd/architecture/tools.md)

### 5.4 GitHub Module

**Priority: 3** — Listed as high-priority in overview; useful for code-related workflows.

Planned as a high-priority integration for code-related workflows. Not implemented.

Source: [overview.md](../trd/architecture/overview.md)

### 5.5 Tool Approval Flow

**Priority: 2** — Critical safety gate before enabling any write tools in production.

The permission model supports read_only/propose/auto modes, but the approval gate — pausing execution for user confirmation on write actions — is not wired into the orchestrator loop.

Source: [tools.md](../trd/architecture/tools.md)

### 5.6 Notion, Twitter, Calendar Modules

**Priority: 5** — Explicitly deferred; no current demand.

Listed as planned modules with `enabled: false` in config examples. Part of the broader integration roadmap.

Sources: [tools.md](../trd/architecture/tools.md), [information_sources.md](../trd/information_sources.md)

### 5.7 MCP Compatibility

**Priority: 5** — Optional interoperability enhancement; not required for Harle to function.

Both import (consume external MCP servers) and export (expose Harle modules as MCP servers) are designed as optional Phase 8. Enhances interoperability with tools like Cursor and Claude.

Source: [tools.md](../trd/architecture/tools.md)

---

## Direction 6: Security & Safety

The tool permission model, constraint engine, and execution sandbox are implemented. However, several security features required for production deployment are missing — from input sanitisation to credential management to network-level access controls.

### 6.1 Input Sanitisation for External Data

**Priority: 2** — Prompt injection is a real risk today since web search is already active.

Strip or escape prompt-injection patterns from web search results, Trello card content, and other external data before including in prompts. No sanitisation layer exists.

Sources: [main_challenges.md](../trd/main_challenges.md), [openclaw_analysis.md](../research/openclaw_analysis.md)

### 6.2 API Authentication and Rate Limiting

**Priority: 3** — Required before any network exposure beyond localhost.

No auth tokens or rate limiting on Orchestrator endpoints. Anyone with network access can call the API.

Source: [main_challenges.md](../trd/main_challenges.md)

### 6.3 Credential Management

**Priority: 3** — Needed before deployment; API keys in plain config are a known risk.

API keys are in plain config files. Designed to move to a secrets backend.

Source: [main_challenges.md](../trd/main_challenges.md)

### 6.4 Tailscale-Only Access Enforcement

**Priority: 3** — Deployment concern; bind to Tailscale interface only.

Bind the Orchestrator to the Tailscale interface only; reject requests from non-Tailscale IPs.

Source: [main_challenges.md](../trd/main_challenges.md)

### 6.5 Dependency Pinning and Vulnerability Scanning

**Priority: 4** — Good hygiene but not blocking development.

No locked dependency versions (`pip-compile`, `go.sum`) and no automated vulnerability scanning.

Source: [main_challenges.md](../trd/main_challenges.md)

### 6.6 PostgreSQL Hardening

**Priority: 4** — Deployment concern; local dev uses default config safely enough.

Enforce password auth, restrict listen addresses, use a dedicated database user with minimal privileges.

Source: [main_challenges.md](../trd/main_challenges.md)

### 6.7 Tool-Call Intent Verification

**Priority: 4** — Advanced safety; needs the agentic loop and tool ecosystem to mature first.

Cross-check tool calls against the user's actual request to detect unintended or manipulated tool usage.

Source: [main_challenges.md](../trd/main_challenges.md)

### 6.8 Memory Poisoning Detection

**Priority: 5** — Requires working memory system first; theoretical risk at this stage.

Flag disproportionately influential memory entries that could skew agent behaviour.

Source: [main_challenges.md](../trd/main_challenges.md)

---

## Direction 7: Testing & CI/CD

Unit tests exist for several modules, but there is no CI/CD pipeline, no coverage tracking, no semantic evaluation, and no E2E tests. The full testing strategy is documented but marked as a 6-week implementation plan with nothing started.

### 7.1 CI/CD Pipeline (GitHub Actions)

**Priority: 2** — Foundational for quality enforcement; everything in this direction depends on it.

No `.github/workflows/` directory exists. Designed to run lint + unit tests on every push, integration tests on PR, nightly E2E/semantic eval.

Source: [testing_strategy.md](../trd/testing_strategy.md)

### 7.2 Linting and Type-Checking Automation

**Priority: 2** — Quick win; ruff + mypy catch bugs early with minimal setup.

No automated `ruff` or `mypy` checks in CI. Config files for these tools may exist but aren't enforced.

Source: [testing_strategy.md](../trd/testing_strategy.md)

### 7.3 Coverage Tracking

**Priority: 3** — Useful for maintaining test discipline as the codebase grows.

Not configured. Designed to enforce a minimum coverage threshold (70%) on PRs via `pytest-cov` and Codecov.

Source: [testing_strategy.md](../trd/testing_strategy.md)

### 7.4 Semantic / LLM Evaluation Tests

**Priority: 4** — Complex setup; needs golden datasets and stable prompts first.

Not implemented. Planned using DeepEval (answer relevancy, faithfulness, hallucination metrics) and Promptfoo (prompt regression).

Source: [testing_strategy.md](../trd/testing_strategy.md)

### 7.5 E2E Tests

**Priority: 4** — Requires a stable system with Docker Compose test environment.

Not implemented. Full-pipeline tests from CLI to Orchestrator to LLM to Tools, with a Docker Compose test environment.

Source: [testing_strategy.md](../trd/testing_strategy.md)

### 7.6 Go CLI Tests

**Priority: 3** — The CLI exists but is entirely untested.

No tests exist for the Go CLI codebase.

Source: [testing_strategy.md](../trd/testing_strategy.md)

### 7.7 API Contract Tests

**Priority: 3** — Prevents silent drift between CLI and Orchestrator API.

No validation that CLI and Orchestrator API schemas stay compatible.

Source: [testing_strategy.md](../trd/testing_strategy.md)

### 7.8 Prompt Regression Testing

**Priority: 4** — Needs golden datasets and promptfoo setup; valuable once prompts stabilise.

No golden datasets or automated regression testing for prompts. Changes to prompts/policies go untested.

Source: [testing_strategy.md](../trd/testing_strategy.md)

---

## Direction 8: Advanced Orchestration & Reasoning

Levels 1 (basic tool-calling loop) and 2 (external tools) are implemented. Levels 3–7 of the multi-step reasoning roadmap are designed but not built. These are powerful capabilities but depend on the agent role infrastructure (Direction 2) being in place first.

### 8.1 Plan-then-Execute (Level 3)

**Priority: 3** — Next natural reasoning level; provides measurable quality improvement for complex tasks.

Task complexity classifier triggers a planning LLM call before execution. Includes plan revision mid-execution and optional two-model optimisation (strong planner, cheap executor).

Source: [multi_step_reasoning.md](../trd/architecture/multi_step_reasoning.md)

### 8.2 Reflection and Self-Critique (Level 4)

**Priority: 4** — Quality improvement; meaningful only after Level 3 works well.

A reflection trigger that invokes a separate LLM call to evaluate the agent's own output, with an improvement loop (max 1 cycle). Optional dedicated `think` tool.

Source: [multi_step_reasoning.md](../trd/architecture/multi_step_reasoning.md)

### 8.3 Adaptive Strategy Selection (Level 6)

**Priority: 5** — Requires all prior reasoning levels; meta-level optimisation.

A strategy selector (rules + optional LLM) choosing the reasoning strategy per request. Includes per-role configuration and user override via `--strategy` flag.

Source: [multi_step_reasoning.md](../trd/architecture/multi_step_reasoning.md)

### 8.4 Parallel Execution (Level 7)

**Priority: 5** — Performance optimisation; independent of reasoning levels but low urgency.

Parallel tool calls via `asyncio.gather()`, parallel agent execution, branch-and-merge for exploratory tasks. An optimisation over the earlier levels.

Source: [multi_step_reasoning.md](../trd/architecture/multi_step_reasoning.md)

### 8.5 Cost Tracking Per Turn/Run

**Priority: 3** — Important for budget awareness as usage grows; moderate effort.

Token counting per turn, cumulative cost per run. Designed as part of the Agent Runner wrapper.

Source: [multi_step_reasoning.md](../trd/architecture/multi_step_reasoning.md)

### 8.6 Streaming Support (SSE)

**Priority: 3** — Significant UX improvement; eliminates blank-screen waits during multi-step runs.

Server-Sent Events for real-time response streaming. Prevents the "blank screen for 30 seconds" problem during multi-step runs.

Source: [orchestrator.md](../trd/architecture/orchestrator.md)

---

## Direction 9: CLI & User Experience

The Go CLI exists but lacks tests and several designed features. UX guardrails (drift warnings, confidence indicators) are fully designed in the hallucination research but not implemented.

### 9.1 Session Management (Resume)

**Priority: 3** — Important for multi-turn workflows; needs server-side session persistence.

`harle --resume` to pick up a previous session. Requires server-side session persistence in PostgreSQL.

Source: [cli.md](../trd/architecture/cli.md)

### 9.2 CLI Authentication

**Priority: 3** — Needed for deployment and multi-user scenarios.

`harle auth login/logout` flow with API key → session token exchange.

Source: [cli.md](../trd/architecture/cli.md)

### 9.3 Slash Commands

**Priority: 3** — Significant UX improvement for interactive chat sessions.

`/quit`, `/new`, `/context`, `/role`, `/history`, `/cost`, `/save`, `/retry`, `/status`, `/help` — interactive commands for the chat session.

Source: [cli.md](../trd/architecture/cli.md)

### 9.4 Topic-Drift Warning

**Priority: 4** — Anti-hallucination UX; needs conversation management (Direction 3) first.

Detect drastic topic shifts within a session and suggest starting fresh. Prevents hallucination from accumulating irrelevant context.

Source: [agent_history_hallucination.md](../research/agent_history_hallucination.md)

### 9.5 Session Length Nudge

**Priority: 5** — Minor UX improvement; low urgency.

Non-blocking notice after a configurable turn count (e.g., 50) suggesting a fresh session for better accuracy.

Source: [agent_history_hallucination.md](../research/agent_history_hallucination.md)

### 9.6 Confidence Visibility

**Priority: 4** — Needs memory confidence scores (3.1) to exist first.

Show an indicator when the response relies on low-confidence memories or low-relevance context.

Source: [agent_history_hallucination.md](../research/agent_history_hallucination.md)

### 9.7 Future Interfaces

**Priority: 5** — Explicitly marked as "not in the first version."

Web chat UI, Telegram bot, Slack/Discord integration, mobile access. All explicitly marked as "not in the first version."

Source: [overview.md](../trd/architecture/overview.md)

---

## Direction 10: Infrastructure & Deployment

Deployment and distribution features are designed but not needed for local development. These become relevant when the system is ready for always-on operation.

### 10.1 VPS Deployment

**Priority: 3** — Needed for always-on access; listed as a near-term goal.

Deploy to a VPS for always-on access. Listed as a near-term goal after core functionality works.

Source: [overview.md](../trd/architecture/overview.md)

### 10.2 Open-Source Model Migration

**Priority: 4** — OpenAI works well for now; the provider abstraction exists for future migration.

Migration from OpenAI to self-hosted models (vLLM, Ollama, llama.cpp). The provider abstraction exists but fallback chains and model switching aren't built.

Sources: [overview.md](../trd/architecture/overview.md), [openclaw_analysis.md](../research/openclaw_analysis.md)

### 10.3 CLI Build & Distribution

**Priority: 4** — Manual build works; automated cross-compilation is a deployment concern.

CI cross-compilation for the Go CLI, version embedding. Future: Homebrew tap, APT repository.

Source: [cli.md](../trd/architecture/cli.md)

### 10.4 Production Monitoring / Drift Detection

**Priority: 5** — Requires production deployment first; theoretical need at this stage.

Monitoring for quality drift in production. No observability infrastructure exists.

Source: [testing_strategy.md](../trd/testing_strategy.md)

---

## Summary Table

| ID | Item | P | Direction |
|----|------|---|-----------|
| 1.1 | Whoosh Full-Text Search (BM25) | **1** | Search & Retrieval |
| 1.2 | Query Expansion | **1** | Search & Retrieval |
| 1.3 | Conversation-Aware Retrieval | **1** | Search & Retrieval |
| 2.1 | Router (Agent Routing Logic) | **1** | Agent Roles & Routing |
| 5.1 | Vault Tool Module | **1** | Tool Modules |
| 1.4 | Multi-Source Result Ranking (RRF) | **2** | Search & Retrieval |
| 1.5 | Semantic Search (pgvector) | **2** | Search & Retrieval |
| 1.6 | Contextual Chunk Enrichment | **2** | Search & Retrieval |
| 2.3 | Researcher Role | **2** | Agent Roles & Routing |
| 2.4 | Secretary Role | **2** | Agent Roles & Routing |
| 3.1 | Memories CRUD | **2** | Memory & Conversation |
| 3.2 | Context Assembly P2/P3 Tiers | **2** | Memory & Conversation |
| 3.3 | Conversation Summary Generation | **2** | Memory & Conversation |
| 4.1 | Auto-Generated Metadata Pipeline | **2** | Data Pipeline |
| 4.2 | Git-Based Dataset Sync | **2** | Data Pipeline |
| 5.2 | Trello Module | **2** | Tool Modules |
| 5.5 | Tool Approval Flow | **2** | Tool Modules |
| 6.1 | Input Sanitisation | **2** | Security |
| 7.1 | CI/CD Pipeline | **2** | Testing & CI/CD |
| 7.2 | Linting Automation | **2** | Testing & CI/CD |
| 1.7 | Reranking Step | **3** | Search & Retrieval |
| 1.8 | Section-Level Chunking | **3** | Search & Retrieval |
| 1.9 | Context-Position Optimization | **3** | Search & Retrieval |
| 2.2 | Clarifier | **3** | Agent Roles & Routing |
| 2.5 | Specialist Role | **3** | Agent Roles & Routing |
| 3.5 | Conflict Detection | **3** | Memory & Conversation |
| 3.6 | Verification Before Persisting | **3** | Memory & Conversation |
| 4.3 | Dataset Quality Assessment | **3** | Data Pipeline |
| 4.4 | Dataset Writer with Approval | **3** | Data Pipeline |
| 5.3 | Scripts Module | **3** | Tool Modules |
| 5.4 | GitHub Module | **3** | Tool Modules |
| 6.2 | API Auth and Rate Limiting | **3** | Security |
| 6.3 | Credential Management | **3** | Security |
| 6.4 | Tailscale-Only Access | **3** | Security |
| 7.3 | Coverage Tracking | **3** | Testing & CI/CD |
| 7.6 | Go CLI Tests | **3** | Testing & CI/CD |
| 7.7 | API Contract Tests | **3** | Testing & CI/CD |
| 8.1 | Plan-then-Execute (Level 3) | **3** | Orchestration |
| 8.5 | Cost Tracking | **3** | Orchestration |
| 8.6 | Streaming (SSE) | **3** | Orchestration |
| 9.1 | Session Resume | **3** | CLI & UX |
| 9.2 | CLI Authentication | **3** | CLI & UX |
| 9.3 | Slash Commands | **3** | CLI & UX |
| 10.1 | VPS Deployment | **3** | Infrastructure |
| 1.10 | Adaptive Relevance Thresholds | **4** | Search & Retrieval |
| 1.11 | Accurate Token Counting | **4** | Search & Retrieval |
| 2.6 | Multi-Agent Handoffs | **4** | Agent Roles & Routing |
| 3.4 | Memory Lifecycle (Hot/Warm/Cold) | **4** | Memory & Conversation |
| 3.7 | Temporal Decay | **4** | Memory & Conversation |
| 4.5 | File Format Validation | **4** | Data Pipeline |
| 4.6 | Ingestion Pipelines | **4** | Data Pipeline |
| 4.7 | Tagging Assistance | **4** | Data Pipeline |
| 6.5 | Dependency Pinning | **4** | Security |
| 6.6 | PostgreSQL Hardening | **4** | Security |
| 6.7 | Tool-Call Intent Verification | **4** | Security |
| 7.4 | Semantic / LLM Eval Tests | **4** | Testing & CI/CD |
| 7.5 | E2E Tests | **4** | Testing & CI/CD |
| 7.8 | Prompt Regression Testing | **4** | Testing & CI/CD |
| 8.2 | Reflection (Level 4) | **4** | Orchestration |
| 9.4 | Topic-Drift Warning | **4** | CLI & UX |
| 9.6 | Confidence Visibility | **4** | CLI & UX |
| 10.2 | Open-Source Model Migration | **4** | Infrastructure |
| 10.3 | CLI Build & Distribution | **4** | Infrastructure |
| 5.6 | Notion, Twitter, Calendar | **5** | Tool Modules |
| 5.7 | MCP Compatibility | **5** | Tool Modules |
| 6.8 | Memory Poisoning Detection | **5** | Security |
| 8.3 | Adaptive Strategy (Level 6) | **5** | Orchestration |
| 8.4 | Parallel Execution (Level 7) | **5** | Orchestration |
| 9.5 | Session Length Nudge | **5** | CLI & UX |
| 9.7 | Future Interfaces | **5** | CLI & UX |
| 10.4 | Production Monitoring | **5** | Infrastructure |

### Priority distribution

| Priority | Count |
|----------|-------|
| **1** — Blocks core value | 5 |
| **2** — Big Goal / major improvement | 15 |
| **3** — Production quality | 24 |
| **4** — Optimisation / second-order | 19 |
| **5** — Long-term / deferred | 8 |
| **Total** | **71** |
