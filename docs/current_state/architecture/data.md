---
title: "Harle Data Layer — Current State"
tags: [data-layer, current-state, architecture, dataset, indexer, search, implementation-status]
context: global
last_updated: 2026-03-11
summary: "Tracks what the Data Layer (User Dataset, Indexer, Search) implements vs the TRD, and what each missing part would unlock."
---

# Harle Data Layer — Current State

> This document compares the target design in the Data Layer TRD with the code in `src/harle/dataset`, `src/harle/db`, `src/harle/indexing`, and `src/harle/search`. It describes what is implemented, what is partial, and what is missing, and what each missing part would unlock.

Reference TRD: [Harle Data Layer — Architecture & Functionality](../../trd/architecture/data.md). Research-backed recommendations: [Data Layer Best Practices](../../trd/architecture/data_layer_best_practices.md). For the Search Algorithm in detail, see [Search Algorithm — Current State](./search.md).

---

## Overall Status

The Data Layer is **partially implemented**. The fundamental principle (data external to the repo) is respected via config and env vars. The **User Dataset** has a working reader, writer, frontmatter parser, and sync convention; the **Indexer** has the full six-table schema and hash-based sync for `file_index`; the **Run Logger** writes result and optional context files to `logs/YYYY/MM/` and records runs in the DB with `result_path`/`context_path`. The **Search Algorithm** is Phase 1 only (keyword search); Phase 2 (Whoosh, query expansion, full metadata pre-filter, ranking) and Phase 3 (semantic) are not implemented. Auto-summary and Whoosh index updates during sync are not wired; config for dataset/indexer/search is minimal.

From the **Data Layer Best Practices** TRD: token budgeting, P0/P1 assembly, frontmatter, and the files-vs-DB split are in place. Gaps include chunking and contextual enrichment, hybrid/semantic retrieval, memory integration (query and save), auto-generated metadata, explicit lost-in-the-middle ordering and relevance scoring in context assembly.

---

## Implementation Snapshot

| TRD area | Current status | Notes |
|----------|----------------|-------|
| Fundamental principle: data external | Implemented | `config`: `HARLE_DATASET_PATH`, `DATABASE_URL`; vault and DB are external; `config.example.yaml` template in repo. → Best practices §3. |
| User Dataset: reader | Implemented | `dataset/reader.py`: list_files, read_file, read_all; frontmatter via `frontmatter.py`; DatasetFile with title, tags, context, content. → Best practices §2, §8. |
| User Dataset: frontmatter | Implemented | `dataset/frontmatter.py`: parse YAML frontmatter; title, tags, context, last_updated supported. → Best practices §2 (how to structure Markdown files), §8 (required frontmatter). |
| User Dataset: writer | Implemented | `dataset/writer.py`: write_log_file; path under `logs/` with approval policy (logs/ auto-approve; others require approval). → Best practices §3. |
| User Dataset: directory structure | Convention only | prompts/, policies/, workflows/, knowledge/, examples/, logs/ are documented and used; not enforced by code. → Best practices §11 (file authoring). |
| User Dataset: logs format | Implemented | `logging/run_logger.py`: `logs/YYYY/MM/<run_id>_result.md`, `_context.md`; YAML frontmatter (run_id, timestamp, agent, status, context_scope). → Best practices §3. |
| User Dataset: agent write controls | Partially implemented | Writer has path checks; tools/orchestrator approval flow for non-logs writes not fully wired (see tools current-state). |
| User Dataset: sync (Git / external) | Not implemented | No `dataset/sync.py` Git pull or periodic sync in app; user/manual or external process. |
| Indexer: file_index table | Implemented | `db/models.py` FileIndex: file_path, title, tags, context, content_hash, char_count, token_count, summary, last_modified, last_indexed, created_at. → Best practices §3, §8. |
| Indexer: runs table | Implemented | Run model with run_id, timestamp, user_request, context_scope, agent, status, files_used, tools_called, model/tokens/cost, result_summary, result_path, context_path, conversation_id. → Best practices §3. |
| Indexer: artifacts table | Implemented | Artifact model; CRUD in `db/artifacts.py`. Not yet used by Run Logger for large outputs. |
| Indexer: memories table | Implemented | Memory model with category, content, context_scope, source_run_id, confidence, active, updated_at. → Best practices §7 (three-tier, confidence, save_memory). |
| Indexer: conversations + messages | Implemented | Conversation and Message models; CRUD in `db/conversations.py`. → Best practices §7 (summarize old conversation). |
| Indexer: embeddings table | Implemented (stub) | Embedding model; embedding column as Text (pgvector later); no indexing or query. → Best practices §6 (semantic), §7 (semantic memory). |
| Indexer: sync pipeline | Partially implemented | `indexing/indexer.py`: walk dataset, hash-based change detection, update/insert/delete file_index. No Whoosh update, no summary generation. → Best practices §6, §11 (data layer). |
| Indexer: token_count | Partially implemented | Set as `len(raw_content) // 4`; TRD suggests tiktoken; summarizer not called. → Best practices §8 (token_count heuristic). |
| Indexer: summary generation | Not implemented | `indexing/summarizer.py` is a stub; file_index.summary not populated. → Best practices §8 (auto-generated metadata). |
| Indexer: Whoosh index in sync | Not implemented | Whoosh not built/updated during indexer sync; see search.md. → Best practices §6 (hybrid search). |
| Run Logger → vault + DB | Implemented | `logging/run_logger.py` writes to vault; orchestrator calls `log_run_to_vault` and `db.runs.create_run` with result_path/context_path. → Best practices §3. |
| Search Algorithm | Partially implemented | Phase 1 keyword search only; see [search.md](./search.md) for full snapshot. → Best practices §6 (hybrid, pre-filter), §4.4 (relevance). |
| Config (dataset/indexer/search) | Partially implemented | `config.py` has HARLE_DATASET_PATH, DATABASE_URL; no sync_interval, sync_on_request, search.*, indexer.summary_model, etc. |
| TRD error handling | Partially implemented | Reader handles missing path; indexer deletes missing files from file_index. No Whoosh rebuild, no DB-unreachable fallback. → Best practices §9. |

### Best practices (§) alignment

| Best practices § | Current status | Notes |
|------------------|----------------|-------|
| §2 How to structure Markdown files | Partially implemented | Frontmatter (title, tags, context) parsed and used. Heading hierarchy and file-length sweet spot are conventions only; no enforcement. |
| §3 PostgreSQL vs. files split | Implemented | Files as source of truth; file_index mirrors metadata; runs/artifacts/memories/conversations/embeddings in DB; logs in vault + runs row. |
| §4 Context Assembly: order (lost in the middle) | Partially implemented | P0 first, user request last; no explicit “supporting results in middle, conversation + request at end”; no memories/prior runs in assembly. |
| §4 Context Assembly: token budget | Implemented | Context assembler uses context_window and input_ratio; P0 always included, P1 until budget exhausted. |
| §4 Context Assembly: relevance scoring | Not implemented | No weighted formula (search_relevance + metadata_match + recency + source_priority + memory_confidence + prior_run_success). See [search.md](./search.md). |
| §5 Chunking strategy | Not implemented | No section-level chunking at H2; no cascading metadata; no contextual summary prepended to chunks; no chunker module. |
| §6 Retrieval: hybrid search | Not implemented | Phase 1 keyword only; no BM25 + pgvector, RRF, or reranking. See [search.md](./search.md). |
| §6 Metadata pre-filter (scope, tags, P0) | Partially implemented | Context-scope filter only; no tag overlap, no P0 injection. See [search.md](./search.md). |
| §7 Memory: three-tier (working/episodic/semantic) | Partially implemented | Working: conversation in context. Episodic: memories table exists; not queried by search/assembler. Semantic: vault + file_index; no embeddings. |
| §7 Memory: confidence, evolution, save_memory | Not implemented | No confidence updates; no memory evolution; no agent save_memory tool. |
| §7 Memory: summarize old conversation | Partially implemented | Conversation history can be included; no multi-resolution summarization of older turns. |
| §8 Metadata: required frontmatter | Partially implemented | title, tags, context supported; priority, summary, last_updated optional; not enforced. |
| §8 Auto-generated metadata | Not implemented | No LLM summary, key_entities, or questions_answered; token_count is heuristic; content_hash present. |
| §9 Failure-mode mitigations | Partially implemented | Token budget and P0/P1 reduce over-retrieval; no deduplication by content hash; no explicit lost-in-the-middle ordering. |
| §11 Actionable (file authoring) | Convention / docs | Docs and cursor rules encourage frontmatter, headings, length; not enforced by code. |
| §11 Actionable (data layer) | Partially implemented | Hybrid search and contextual summaries not implemented; ordering and budget partially there. |

---

## What Is Implemented

### 1. Fundamental principle and config (§3)

- Dataset path and database URL are read from config or environment (`HARLE_DATASET_PATH`, `DATABASE_URL`). The app does not store user data inside the code repo; vault and DB are external. This matches the Best Practices TRD: files as source of truth; file_index mirrors metadata; runs/artifacts/memories/conversations/embeddings in DB; logs in vault + runs row.

### 2. User Dataset: reader and frontmatter (§2, §8)

- **DatasetReader** lists `.md` files under the dataset path (excluding hidden dirs), reads files, and parses frontmatter. **DatasetFile** exposes relative_path, title, tags, context, content, raw_content.
- **Frontmatter** parser extracts YAML; title, tags, context, last_updated are used by the indexer and search. Context scope is used for filtering and run logging (“metadata as force multiplier”, scope isolation).

### 3. User Dataset: writer and logs (§3)

- **write_log_file** writes to vault-relative paths (e.g. `logs/2026/02/run_xyz_result.md`); approval policy: writes under `logs/` can auto-approve; other paths require approval.
- **Run Logger** builds result and optional context files with YAML frontmatter (run_id, timestamp, agent, status, context_scope) and body; returns result_path and context_path to the orchestrator, which persists them on the `runs` row. Supports auditability and “open by path” as in the Best Practices TRD.

### 4. Indexer: schema and file_index sync

- All six TRD tables exist in **db/models.py**: FileIndex, Run, Artifact, Memory, Conversation, Message, Embedding (embedding column as Text for now).
- **Indexer.sync()** walks the dataset via DatasetReader, computes content hash per file, compares with file_index; inserts new rows, updates changed rows (title, tags, context, content_hash, char_count, token_count, last_modified, last_indexed), and deletes rows for files that no longer exist. Hash-based change detection matches the TRD.

### 5. Run Logger and runs table

- Orchestrator records each run in the DB with run_id, user_request, context_scope, agent, status, files_used, tools_called, token/cost fields, result_summary, result_path, context_path, conversation_id. Log files are written under the vault `logs/` directory with date-based layout.

### 6. Search Algorithm (Phase 1)

- Phase 1 keyword search is implemented and used by the Context Assembler. See [search.md](./search.md) for details.

---

## What Is Only Partially Implemented

### 1. Indexer sync: no Whoosh, no summary

TRD sync step 3: re-index changed files → parse frontmatter, estimate tokens, **generate/update summary (LLM)**, **update Whoosh index**. Current behaviour: only file_index is updated; token_count is a rough `len//4`; no call to the summarizer; Whoosh is not built or updated during sync. So the indexer keeps file_index in sync with the vault but does not yet drive Whoosh or populate summaries.

### 2. Token count

TRD and best practices recommend tiktoken for token_count. Implementation uses a character-based heuristic. **Unlock:** Accurate token budgeting in the Context Assembler and indexer.

### 3. Config

TRD describes `dataset.sync_interval_seconds`, `dataset.sync_on_request`, `dataset.file_extensions`, `dataset.ignore_patterns`, `search.max_results`, `search.title_boost`, `indexer.summary_model`, `indexer.auto_summarize`, etc. Only dataset path and database URL are currently used from config/env. **Unlock:** Tuning and deployment options without code changes.

### 4. Agent write controls

Dataset writer has path-based approval (logs/ vs rest). The full TRD flow (work vs personal, approval gate in orchestrator/tools) is partially present; see tools and orchestrator current-state docs. **Unlock:** Safe agent writes to knowledge/ and workflows/ with explicit user approval.

### 5. Error handling

Missing file: row removed from file_index. TRD also describes Whoosh rebuild on missing/corrupt, DB-unreachable fallback, file encoding errors (skip and log). Only part of this is implemented.

### 6. Memory and metadata (Best Practices §7, §8)

- **Memory (§7):** Memories table exists and can store preferences/decisions; search and context assembler do not yet query memories or include them in context. No confidence scoring, evolution, or save_memory tool. **Unlock:** Personalized context and fewer repeated questions.
- **Metadata and tagging (§8):** Required/recommended frontmatter (title, tags, context) are supported but not enforced; priority, summary, last_updated in frontmatter are optional. No auto-generated summary, key_entities, or questions_answered. **Unlock:** Better retrieval and multi-hop query performance without reading full files.

---

## What Is Not Implemented Yet

### 1. Dataset sync (Git / periodic)

**Missing:** `dataset/sync.py` or equivalent: Git pull (or Syncthing) and/or periodic re-sync of the vault; trigger sync on startup or before request when configured.

**What this would unlock:** Server always using the latest vault content without manual pull; multi-machine consistency.

### 2. Summary generation and auto-generated metadata (Best Practices §8.4)

**Missing:** Implementation of `indexing/summarizer.py` (LLM call for one-sentence summary per file) and wiring into the indexer so that new/changed files get `file_index.summary` populated. Best Practices §8.4 also recommends LLM-generated key_entities and questions_answered per file in file_index (or equivalent).

**What this would unlock:** Better search relevance and token-budget decisions without reading full file content; stronger metadata pre-filter and question-style retrieval without full content scan.

### 3. Whoosh index build/update during sync

**Missing:** When the indexer adds or updates a file_index row, update the Whoosh index (build if missing, incremental update per file). Index path from config.

**What this would unlock:** Phase 2 search without full file scan; see search.md.

### 4. Full config for dataset, indexer, search

**Missing:** `config.example.yaml` and config loading for dataset.*, indexer.*, search.* as in the TRD Configuration section; env overrides where specified.

**What this would unlock:** Per-deployment tuning and feature toggles (e.g. auto_summarize, sync_interval, search weights).

### 5. Artifacts and memories in the run flow (Best Practices §7)

**Missing:** Run Logger (or a dedicated path) persisting large outputs into `artifacts` and linking to runs; creation/update of `memories` from agent/user actions. Tables exist; integration with orchestrator and tools is not complete. Best Practices §7 also specifies: confidence scores on memories (increase with use, decrease with corrections); memory evolution (new memory triggers search for related memories and possible update/merge); agent-facing save_memory tool.

**What this would unlock:** Queryable history of reports/artifacts; preference and decision recall in context assembly; fewer stale or contradictory preferences; agent-driven persistence of important facts.

### 6. Chunking strategy (Best Practices §5)

**Missing:** Section-level chunking at H2 boundaries; cascading metadata (Document > Section > Subsection); contextual summary prepended to each chunk (Anthropic-style); chunker module and chunk-aware indexing/retrieval for long files.

**What this would unlock:** Relevant sections from long files instead of whole-file retrieval; fewer orphaned chunks and better relevance.

### 7. Search Phase 2 and Phase 3 (Best Practices §6)

**Missing:** Whoosh pipeline, query expansion, metadata pre-filter, ranking/fusion, memory and prior-run lookup, then semantic search (pgvector). Best Practices §6: BM25 + pgvector, RRF, optional reranking. See [search.md](./search.md).

**What this would unlock:** Scalable retrieval for 100–1,000+ files; semantic and hybrid search for large or conceptually diverse datasets.

### 8. Failure-mode mitigations (Best Practices §9)

**Missing:** Explicit placement of high-priority content at start and end of context (lost-in-the-middle); deduplication by content hash in assembly; optional reranking to reduce orphaned-chunk and over-retrieval issues.

**What this would unlock:** More robust behaviour with long context and many candidates.

---

## Key Deviations From The TRD

- **Sync process:** TRD says “mark deleted” for missing files; implementation **deletes** the row. There is no `deleted_at` column on file_index, so behaviour is “remove row” rather than soft-delete.
- **Token count:** TRD implies tiktoken or similar; implementation uses character-based estimate.
- **Project structure:** TRD lists `dataset/sync.py` for Git pull and change detection. The file exists but is a stub; no Git pull or periodic sync is implemented.

**From Data Layer Best Practices:**

- **Context order:** Assembler does not implement the full “lost in the middle” order (supporting results in middle, conversation + request at end); it focuses on P0 then P1 and user request last.
- **Memory:** Memories table is not yet used by search or context assembly; no save_memory tool or confidence/evolution logic.
- **Chunking:** No chunking layer; long files are treated as single units, contrary to recommended section-level chunking and contextual enrichment.

---

## Current Assessment

The Data Layer has a **solid base**: external data principle, dataset reader/writer, frontmatter, logs layout, full Indexer schema, hash-based file_index sync, and Run Logger writing to vault and DB. The main gaps are **sync automation** (Git/periodic), **summary generation**, **Whoosh lifecycle in sync**, and **full config**. Implementing chunking, hybrid/semantic retrieval, memory integration, auto-generated metadata, explicit lost-in-the-middle ordering, and relevance scoring would bring behaviour in line with the Data Layer Best Practices TRD. Filling these would align with the TRD and unlock Phase 2 search and better context assembly. Search evolution is tracked in [search.md](./search.md).
