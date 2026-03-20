---
title: "Harle Data Layer — Current State"
tags: [data-layer, current-state, architecture, dataset, indexer, search, implementation-status]
context: global
last_updated: 2026-03-20
summary: "Tracks what the Data Layer (User Dataset, Indexer, Search) implements vs the TRD, and what each missing part would unlock."
---

# Harle Data Layer — Current State

> This document compares the target design in the Data Layer TRD with the code in `src/harle/dataset`, `src/harle/db`, `src/harle/indexing`, and `src/harle/search`. It describes what is implemented, what is partial, and what is missing, and what each missing part would unlock.

Reference TRD: [Harle Data Layer — Architecture & Functionality](../../trd/architecture/data.md). Research-backed recommendations: [Data Layer Best Practices](../../trd/architecture/data_layer_best_practices.md). For the Search Algorithm in detail, see [Search Algorithm — Current State](./search.md).

---

## Overall Status

The Data Layer is **partially implemented**. The fundamental principle (data external to the repo) is respected via config and env vars. The **User Dataset** has a working reader, writer, frontmatter parser, and sync convention; the **Indexer** has the full six-table schema, hash-based sync for `file_index`, **tiktoken `token_count`**, and optional **chunk-aware Whoosh** updates when `whoosh_index_path` is set; the **Run Logger** writes result and optional context files to `logs/YYYY/MM/` and records runs in the DB. The **Search Algorithm** supports Phase 1 (keyword) and Phase 2 (Whoosh with **chunking**); Phase 3 (pgvector / hybrid RRF) is not implemented. LLM auto-summary for `file_index.summary` is not wired.

From the **Data Layer Best Practices** TRD: token budgeting, explicit §4.2 context ordering (top/supporting split + end-positioned conversation history), frontmatter, the files-vs-DB split, **chunking** (`indexing/chunker.py`), **chunk-aware Whoosh indexing**, and **contextual enrichment at index time** (prepended metadata block per §5.3) are in place. Gaps include hybrid/semantic retrieval (pgvector), memory/prior-run retrieval integration, and auto-generated LLM summaries.

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
| Indexer: sync pipeline | Partially implemented | `indexing/indexer.py`: walk dataset, hash-based change detection, update/insert/delete file_index; Whoosh incremental update via chunk-aware `update_document` when `whoosh_index_path` set; full Whoosh `build_from_scratch` when the on-disk Whoosh schema does not match the current schema (avoids partial index after upgrades). No summary generation. → Best practices §6, §11 (data layer). |
| Indexer: token_count | Implemented | `count_tokens` (tiktoken) on `raw_content` for `file_index.token_count`. → Best practices §8. |
| Indexer: summary generation | Not implemented | `indexing/summarizer.py` is a stub; file_index.summary not populated. → Best practices §8 (auto-generated metadata). |
| Indexer: Whoosh index in sync | Implemented | Sync replaces all Whoosh docs for a changed file (`remove_documents_by_file_path` + chunk writes). See search.md. → Best practices §6. |
| Run Logger → vault + DB | Implemented | `logging/run_logger.py` writes to vault; orchestrator calls `log_run_to_vault` and `db.runs.create_run` with result_path/context_path. → Best practices §3. |
| Search Algorithm | Partially implemented | Phase 1 keyword + Phase 2 Whoosh; chunk-aware Phase 2. See [search.md](./search.md). → Best practices §6 (hybrid when pgvector added), §4.4 (relevance). |
| Config (dataset/indexer/search) | Partially implemented | `config.py`: paths, `get_search_config()`, `get_chunking_config()`; many TRD `dataset.*` / `indexer.*` keys still absent. |
| TRD error handling | Partially implemented | Reader handles missing path; indexer deletes missing files from file_index. No Whoosh rebuild, no DB-unreachable fallback. → Best practices §9. |

### Best practices (§) alignment

| Best practices § | Current status | Notes |
|------------------|----------------|-------|
| §2 How to structure Markdown files | Partially implemented | Frontmatter (title, tags, context) parsed and used. Heading hierarchy and file-length sweet spot are conventions only; no enforcement. |
| §3 PostgreSQL vs. files split | Implemented | Files as source of truth; file_index mirrors metadata; runs/artifacts/memories/conversations/embeddings in DB; logs in vault + runs row. |
| §4 Context Assembly: order (lost in the middle) | Implemented | Assembler now uses explicit order: P0, top search results, supporting search results, prior-run slot, memory slot, conversation history; user request remains last as the user-role message. |
| §4 Context Assembly: token budget | Implemented | Context assembler uses context_window and input_ratio; P0 always included, P1 until budget exhausted. |
| §4 Context Assembly: relevance scoring | Implemented | Weighted ranker in Phase 2 uses the six-term formula (search_relevance + metadata_match + recency + source_priority + memory_confidence + prior_run_success); `memory_confidence` is currently stubbed to 0.0 for file-only ranking. See [search.md](./search.md). |
| §5 Chunking strategy | Implemented | `indexing/chunker.py`: prompts/policies/examples + short knowledge whole-file; workflows + long knowledge H2 sections with cascading `heading_path`; logs paragraph chunks; context block prepended for BM25; Whoosh multi-doc per file; assembler re-chunks for P1. LLM per-chunk summary not implemented. |
| §6 Retrieval: hybrid search | Partially implemented | BM25 (Whoosh) + chunking; no pgvector, RRF, or reranking. See [search.md](./search.md). |
| §6 Metadata pre-filter (scope, tags, P0) | Implemented | See [search.md](./search.md): context + global, tag overlap, P0 prompts/policies. |
| §7 Memory: three-tier (working/episodic/semantic) | Partially implemented | Working: conversation in context. Episodic: memories table exists; not queried by search/assembler. Semantic: vault + file_index; no embeddings. |
| §7 Memory: confidence, evolution, save_memory | Not implemented | No confidence updates; no memory evolution; no agent save_memory tool. |
| §7 Memory: summarize old conversation | Partially implemented | Conversation history can be included; no multi-resolution summarization of older turns. |
| §8 Metadata: required frontmatter | Partially implemented | title, tags, context supported; priority, summary, last_updated optional; not enforced. |
| §8 Auto-generated metadata | Partially implemented | `token_count` via tiktoken; content_hash present; no LLM summary, key_entities, or questions_answered. |
| §9 Failure-mode mitigations | Partially implemented | Token budget and explicit start/middle/end ordering mitigate lost-in-the-middle; no deduplication by content hash; no reranking. |
| §11 Actionable (file authoring) | Convention / docs | Docs and cursor rules encourage frontmatter, headings, length; not enforced by code. |
| §11 Actionable (data layer) | Partially implemented | Chunking and index-time context blocks implemented; explicit assembly ordering implemented; pgvector hybrid and LLM summaries not implemented. |

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

### 6. Search Algorithm (Phase 1 and Phase 2)

- Phase 1 keyword and Phase 2 Whoosh search are implemented; default engine is Whoosh. Chunk-aware retrieval returns `SearchResult.chunk_index` / `heading_path` when applicable. See [search.md](./search.md).

### 7. Chunking and contextual enrichment (Best Practices §5)

- **`indexing/chunker.py`:** File-type rules (whole vs H2 vs paragraph), cascading `heading_path`, optional context block for indexing.
- **Whoosh:** Multiple documents per file when chunked (`path` = `file_path` or `file_path#n`); `file_path` stored for candidate filter and deletion.
- **Context assembler:** Re-runs the chunker on the vault file for chunk hits and adds an excerpt hint with path for full-file reads.

---

## What Is Only Partially Implemented

### 1. Indexer sync: no LLM summary

TRD sync step 3 includes **generate/update summary (LLM)**. Current behaviour: file_index and Whoosh stay in sync; **no** call to the summarizer; `file_index.summary` is usually empty.

### 2. Config (dataset / indexer extras)

TRD describes `dataset.sync_interval_seconds`, `dataset.sync_on_request`, `dataset.file_extensions`, `dataset.ignore_patterns`, `indexer.summary_model`, `indexer.auto_summarize`, etc. Core paths plus `search.*` and `chunking.*` are loaded; many TRD keys remain unused. **Unlock:** Full TRD-aligned tuning without code changes.

### 3. Agent write controls

Dataset writer has path-based approval (logs/ vs rest). The full TRD flow (work vs personal, approval gate in orchestrator/tools) is partially present; see tools and orchestrator current-state docs. **Unlock:** Safe agent writes to knowledge/ and workflows/ with explicit user approval.

### 4. Error handling

Missing file: row removed from file_index. TRD also describes Whoosh rebuild on missing/corrupt, DB-unreachable fallback, file encoding errors (skip and log). Only part of this is implemented.

### 5. Memory and metadata (Best Practices §7, §8)

- **Memory (§7):** Memories table exists and can store preferences/decisions; assembler has a dedicated memory slot in the middle section, but search does not yet populate `memory_results` in normal flow. No confidence scoring, evolution, or save_memory tool. **Unlock:** Personalized context and fewer repeated questions.
- **Metadata and tagging (§8):** Required/recommended frontmatter (title, tags, context) are supported but not enforced; priority, summary, last_updated in frontmatter are optional. No auto-generated summary, key_entities, or questions_answered. **Unlock:** Better retrieval and multi-hop query performance without reading full files.

---

## What Is Not Implemented Yet

### 1. Dataset sync (Git / periodic)

**Missing:** `dataset/sync.py` or equivalent: Git pull (or Syncthing) and/or periodic re-sync of the vault; trigger sync on startup or before request when configured.

**What this would unlock:** Server always using the latest vault content without manual pull; multi-machine consistency.

### 2. Summary generation and auto-generated metadata (Best Practices §8.4)

**Missing:** Implementation of `indexing/summarizer.py` (LLM call for one-sentence summary per file) and wiring into the indexer so that new/changed files get `file_index.summary` populated. Best Practices §8.4 also recommends LLM-generated key_entities and questions_answered per file in file_index (or equivalent).

**What this would unlock:** Better search relevance and token-budget decisions without reading full file content; stronger metadata pre-filter and question-style retrieval without full content scan.

### 3. Full config for dataset and indexer (remaining TRD keys)

**Missing:** Several `dataset.*` / `indexer.*` keys from the TRD; env overrides for all.

**What this would unlock:** Per-deployment tuning (e.g. auto_summarize, sync_interval) without code changes.

### 4. Artifacts and memories in the run flow (Best Practices §7)

**Missing:** Run Logger (or a dedicated path) persisting large outputs into `artifacts` and linking to runs; creation/update of `memories` from agent/user actions. Tables exist; integration with orchestrator and tools is not complete. Best Practices §7 also specifies: confidence scores on memories (increase with use, decrease with corrections); memory evolution (new memory triggers search for related memories and possible update/merge); agent-facing save_memory tool.

**What this would unlock:** Queryable history of reports/artifacts; preference and decision recall in context assembly; fewer stale or contradictory preferences; agent-driven persistence of important facts.

### 5. Search Phase 3 (Best Practices §6)

**Missing:** pgvector semantic search, hybrid RRF, optional reranking. Phase 2 Whoosh + chunking is implemented; see [search.md](./search.md).

**What this would unlock:** Conceptual / paraphrase matching; full hybrid retrieval as in Best Practices §6.

### 6. Failure-mode mitigations (Best Practices §9)

**Missing:** Deduplication by content hash in assembly; optional reranking to reduce orphaned-chunk and over-retrieval issues.

**What this would unlock:** More robust behaviour with long context and many candidates.

---

## Key Deviations From The TRD

- **Sync process:** TRD says “mark deleted” for missing files; implementation **deletes** the row. There is no `deleted_at` column on file_index, so behaviour is “remove row” rather than soft-delete.
- **Token count:** `file_index.token_count` uses tiktoken on full `raw_content`; chunking thresholds use body token counts via the same helper.
- **Project structure:** TRD lists `dataset/sync.py` for Git pull and change detection. The file exists but is a stub; no Git pull or periodic sync is implemented.

**From Data Layer Best Practices:**

- **Context order:** Explicit start/middle/end ordering is implemented; prior-run and memory slots are present but currently populated only when upstream retrieval provides `prior_runs` / `memory_results`.
- **Memory:** Memories table is not yet used by search or context assembly; no save_memory tool or confidence/evolution logic.
- **Chunking:** Implemented for Whoosh + assembler; LLM-generated per-chunk summaries (Anthropic-style) are not implemented—context block uses heading path and first sentence/line heuristics.

---

## Current Assessment

The Data Layer has a **solid base**: external data principle, dataset reader/writer, frontmatter, logs layout, full Indexer schema, hash-based file_index sync, Run Logger, **tiktoken token_count**, **chunk-aware Whoosh indexing**, and **section/chunk retrieval** for long workflows/knowledge and paragraph chunks for logs. Main gaps remain **sync automation** (Git/periodic), **LLM summary generation**, **Phase 3 semantic/hybrid search**, **memory integration in context assembly**, and **full TRD config surface**. Search details are in [search.md](./search.md).
