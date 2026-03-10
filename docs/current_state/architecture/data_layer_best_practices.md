---
title: "Data Layer Best Practices — Current State"
tags: [data-layer, best-practices, current-state, retrieval, chunking, memory, implementation-status]
context: global
last_updated: 2026-03-10
summary: "Tracks implementation status of research-backed recommendations from the Data Layer Best Practices TRD and what each missing part would unlock."
---

# Data Layer Best Practices — Current State

> This document maps the recommendations in the Data Layer Best Practices TRD to the current implementation. It describes what is implemented, what is partial, and what is missing, and what each missing part would unlock.

Reference TRD: [Data Layer Best Practices for Harle](../../trd/architecture/data_layer_best_practices.md). Companion implementation TRD: [Harle Data Layer — Architecture & Functionality](../../trd/architecture/data.md). See also [Data Layer — Current State](./data.md) and [Search Algorithm — Current State](./search.md).

---

## Overall Status

The codebase aligns with **some** of the best-practices recommendations: frontmatter and context scope are used; context assembly uses a token budget and P0/P1 priority; run logs and runs table exist; the Indexer mirrors the vault with hash-based sync. **Missing or partial:** Lost-in-the-middle ordering (high priority at start/end) is only partly reflected; no chunking or contextual chunk enrichment; no hybrid/semantic retrieval yet; no three-tier memory integration in search; no auto-generated metadata (summary, key_entities, questions_answered); no memory confidence evolution or save_memory tool; and no explicit relevance scoring formula or reranking.

---

## Implementation Snapshot

| TRD section / recommendation | Current status | Notes |
|------------------------------|----------------|-------|
| §2 How to Structure Markdown Files | Partially implemented | Frontmatter (title, tags, context) parsed and used. Heading hierarchy and file-length sweet spot are conventions only; no enforcement. Writing-style guidance is docs-only. |
| §3 PostgreSQL vs. Files split | Implemented | Files as source of truth; file_index mirrors metadata; runs/artifacts/memories/conversations/embeddings in DB; logs in vault + runs row. |
| §4 Context Assembly: order (lost in the middle) | Partially implemented | P0 (prompts, policies) first; P1 search results; user request last. No explicit “supporting results in middle, conversation + request at end” ordering; no memories/prior runs in assembly yet. |
| §4 Context Assembly: token budget | Implemented | Context assembler uses context_window and input_ratio (~80% input, ~20% output); P0 always included, P1 until budget exhausted. |
| §4 Context Assembly: relevance scoring | Not implemented | No weighted formula (search_relevance + metadata_match + recency + source_priority + memory_confidence + prior_run_success). |
| §5 Chunking strategy | Not implemented | No section-level chunking at H2; no cascading metadata; no contextual summary prepended to chunks; no chunker module. |
| §6 Retrieval: hybrid search | Not implemented | Phase 1 keyword only; no BM25 + pgvector, no RRF, no reranking. See search.md. |
| §6 Metadata pre-filter (scope, tags, P0) | Partially implemented | Context-scope filter only; no tag overlap, no P0 injection. See search.md. |
| §7 Memory: three-tier (working/episodic/semantic) | Partially implemented | Working: conversation in context. Episodic: memories table exists; not queried by search/assembler. Semantic: vault + file_index; no embeddings. |
| §7 Memory: confidence, evolution, save_memory | Not implemented | No confidence updates; no memory evolution; no agent save_memory tool. |
| §7 Memory: summarize old conversation | Partially implemented | Conversation history can be included; no multi-resolution summarization of older turns. |
| §8 Metadata: required frontmatter | Partially implemented | title, tags, context supported; priority, summary, last_updated in frontmatter optional; not enforced. |
| §8 Auto-generated metadata | Not implemented | No LLM summary, key_entities, or questions_answered; token_count is heuristic; content_hash present. |
| §9 Failure-mode mitigations | Partially implemented | Token budget and P0/P1 reduce over-retrieval; no deduplication by content hash; no explicit lost-in-the-middle ordering. |
| §11 Actionable recommendations (file authoring) | Convention / docs | Docs and cursor rules encourage frontmatter, headings, length; not enforced by code. |
| §11 Actionable recommendations (data layer) | Partially implemented | Hybrid search and contextual summaries not implemented; ordering and budget partially there. |

---

## What Is Implemented

### 1. PostgreSQL vs. files split (§3)

The split matches the TRD: human-authored content in the vault (prompts, policies, workflows, knowledge, examples); run metadata and conversation state in PostgreSQL; logs as Markdown in vault with corresponding runs row (result_path, context_path). file_index mirrors vault metadata.

### 2. Token-budgeted context assembly (§4.3)

Context assembler uses a fixed context window and input ratio (default ~80% input, ~20% reserved for model output). P0 (prompts, policies) is always included; P1 (search results) is added until the budget is exhausted. This aligns with the TRD’s hard token budget and priority-based allocation.

### 3. Frontmatter and scope (§2, §8)

Dataset reader and indexer parse YAML frontmatter; title, tags, context, and last_updated are used. Context scope is used for filtering in search and for run logging. This supports the “metadata as force multiplier” and scope-isolation recommendations.

### 4. Run logs and runs table (§3, TRD data.md)

Run Logger writes result and optional context files to `logs/YYYY/MM/` with frontmatter; orchestrator persists run metadata and paths in the runs table. This supports auditability and “open by path” as in the TRD.

---

## What Is Only Partially Implemented

### 1. Lost-in-the-middle ordering (§4.1, §4.2)

TRD recommends: system prompt + policies at start, top search results next, supporting results and prior runs/memories in the middle, conversation + user request at the end. Current assembler places P0 first and user request last but does not explicitly place “supporting” results in the middle or include memories/prior runs, and does not reserve the end slot for conversation + request only. **Unlock:** Better model attention on critical content and on the actual request.

### 2. Memory architecture (§7)

Memories table exists and can store preferences/decisions; search and context assembler do not yet query memories or include them in context. No confidence scoring, evolution, or save_memory tool. **Unlock:** Personalized context (preferences, past decisions) and fewer repeated questions.

### 3. Metadata pre-filter and retrieval (§6)

Only context-scope filter is applied; no tag overlap, P0-always-included, or hybrid retrieval. See search.md. **Unlock:** Smaller candidate set, better recall, and semantic/conceptual match.

### 4. Metadata and tagging (§8)

Required/recommended frontmatter fields are supported but not enforced. No auto-generated summary, key_entities, or questions_answered. **Unlock:** Better retrieval and multi-hop query performance without reading full files.

### 5. Conversation summarization (§7)

Older conversation turns can be included in context; there is no multi-resolution summarization (summarize older turns, keep recent verbatim) as in RMM/MemGPT. **Unlock:** Longer conversations within token budget without losing important history.

---

## What Is Not Implemented Yet

### 1. Chunking strategy (§5)

**Missing:** Section-level chunking at H2 boundaries; cascading metadata (e.g. Document > Section > Subsection); contextual summary prepended to each chunk (Anthropic-style); chunker module and chunk-aware indexing/retrieval for long files.

**What this would unlock:** Relevant sections from long files instead of whole-file retrieval; fewer orphaned chunks and better relevance.

### 2. Context relevance scoring formula (§4.4)

**Missing:** Explicit combination of search_relevance, metadata_match, recency, source_priority, memory_confidence, prior_run_success with configurable weights.

**What this would unlock:** Consistent, tunable ranking and inclusion decisions in the assembler.

### 3. Hybrid search and reranking (§6)

**Missing:** BM25 + pgvector pipeline, Reciprocal Rank Fusion, optional reranking phase. See search.md.

**What this would unlock:** Conceptual and paraphrase match; better behaviour on large or diverse datasets.

### 4. Auto-generated metadata (§8.4)

**Missing:** LLM-generated summary, key_entities, and questions_answered per file; wiring into indexer so file_index (or equivalent) stores them.

**What this would unlock:** Stronger metadata pre-filter and question-style retrieval without full content scan.

### 5. Memory confidence and evolution (§7)

**Missing:** Confidence scores on memories that increase with use and decrease with corrections; memory evolution (new memory triggers search for related memories and possible update/merge); agent-facing save_memory tool.

**What this would unlock:** Fewer stale or contradictory preferences; agent-driven persistence of important facts.

### 6. Failure-mode mitigations (§9)

**Missing:** Explicit placement of high-priority content at start and end of context; deduplication by content hash; optional reranking to reduce orphaned-chunk and over-retrieval issues.

**What this would unlock:** More robust behaviour with long context and many candidates.

---

## Key Deviations From The TRD

- **Context order:** Assembler does not implement the full “lost in the middle” order (supporting results in middle, conversation + request at end); it focuses on P0 then P1 and user request last.
- **Memory:** Memories table is not yet used by search or context assembly; no save_memory tool or confidence/evolution logic.
- **Chunking:** No chunking layer; long files are treated as single units, contrary to the recommended section-level chunking and contextual enrichment.

---

## Current Assessment

The codebase **partially** reflects the best-practices TRD: token budgeting, P0/P1 assembly, frontmatter, and the files-vs-DB split are in place. The largest gaps are **chunking and contextual enrichment**, **hybrid/semantic retrieval**, **memory integration** (query and save), **auto-generated metadata**, and **explicit lost-in-the-middle ordering and relevance scoring**. Implementing these would bring behaviour in line with the research-backed recommendations and improve relevance and personalization at scale.
