---
title: "Harle Search Algorithm — Current State"
tags: [search, current-state, architecture, whoosh, retrieval, implementation-status]
context: global
last_updated: 2026-03-20
summary: "Tracks what the Search Algorithm implements vs the TRD (search.md and data.md), and what each missing part would unlock."
---

# Harle Search Algorithm — Current State

> This document compares the target design in the Search Algorithm TRD with the code in `src/harle/search`. It describes what is implemented, what is partial, and what is missing, and what each missing part would unlock.

Reference TRD: [Harle Search Algorithm — Architecture & Functionality](../../trd/architecture/search.md). See also [Data Layer](../../trd/architecture/data.md) §3 for the high-level Search Algorithm summary. Research-backed retrieval and assembly recommendations: [Data Layer Best Practices](../../trd/architecture/data_layer_best_practices.md).

---

## Overall Status

The Search Algorithm supports **Phase 1 (keyword) and Phase 2 (Whoosh)**. The default engine is **Whoosh**; set `search.engine: "keyword"` to use Phase 1. Phase 1: tokenize query, load file_index entries by context, read files from disk, score by term matching, return top N. Phase 2: query expansion (tokenize, stem, tag vocabulary, role terms), metadata pre-filter (context + global, tag overlap, P0 injection), Whoosh BM25 search over candidates, metadata enrichment, memory and prior-run lookup, weighted ranking (BM25 + tag match + recency + source priority + prior-run bonus), and `SearchResponse` (file_results, memory_results, prior_runs, query_metadata). Whoosh index is built from scratch on init/reindex when engine is whoosh and updated incrementally during sync.

**Not implemented:** Phase 3 (pgvector semantic search, hybrid RRF, reranking), `deleted_at` filter on file_index, search timeout, and PostgreSQL-unreachable fallback. **Implemented:** `indexing/chunker.py`, chunk-aware Whoosh (multi-doc per file, `file_path` filter), `SearchResult.chunk_index` / `heading_path`, ranker cap `max_chunks_per_file_in_results`, context-assembler chunk load + excerpt hint. LLM per-chunk summaries are not implemented (heuristic context block only). Per **Data Layer Best Practices**: full hybrid (BM25 + pgvector) and reranking are not implemented; memory and prior-run lookup are implemented and included in the response.

---

## Implementation Snapshot

| TRD area | Current status | Notes |
|----------|----------------|-------|
| Phase 1: Simple keyword search | Implemented | `engine.py`: tokenize, get candidates by context, load content from disk, score (title/tag/content weights), sort; returns `SearchResponse` with `file_results`. |
| Phase 2: Whoosh pipeline | Implemented | Engine branch when `search.engine: whoosh`: expand → pre-filter → Whoosh search → enrich → memory/prior-run → rank; returns `SearchResponse`. |
| SearchQuery / SearchResult types | Implemented | `types.py`: SearchQuery; SearchResult (+ token_count, summary, source, last_modified, chunk_index, heading_path). |
| Step 1: Query expansion | Implemented | `query_expander.py`: tokenize, stopwords, stemming (Whoosh), tag vocabulary match, role terms; `ExpandedQuery`. |
| Step 2: Metadata pre-filter (full) | Implemented | `get_candidates_for_search`: context + global/NULL, tag overlap, P0 (prompts/policies) always included. No `deleted_at` (schema has none). |
| Step 3: Whoosh full-text (BM25) | Implemented | `whoosh_index.py`: schema (path, file_path, chunk_index, heading_path, title, tags, content, context, modified), chunk-aware build/update, `remove_documents_by_file_path`, search with `file_path` candidate filter; returns `WhooshSearchHit`. |
| Step 4: Metadata enrichment | Implemented | `get_entries_by_paths`; SearchResult has token_count, summary, last_modified; ranker and engine populate them. |
| Step 5: Memory and history lookup | Implemented | `memories.search_memories`, `runs.search_similar_runs`; MemoryResult, PriorRunResult in SearchResponse. → Best practices §7. |
| Step 6: Ranking and fusion | Implemented | `ranker.py`: normalized BM25 + tag_match + recency + source_priority + prior_run_bonus; per-chunk keys; cap chunks per file; configurable weights. → Best practices §4.4. |
| Whoosh index management | Implemented | Build on init/reindex when engine=whoosh; incremental update/remove in indexer sync; full rebuild when on-disk schema is stale (indexer, bootstrap ensure, Phase 2); rebuild on missing/corrupt search in engine. |
| Chunking strategy | Implemented | `indexing/chunker.py` + `get_chunking_config()`; H2 sections (workflows, long knowledge), paragraphs (logs), whole-file (prompts/policies/examples, short knowledge); TRD §5.3 context block at index time. → Best practices §5. |
| Phase 3: Semantic search (pgvector) | Not implemented | Not started. → Best practices §6 (hybrid: pgvector). |
| SearchResponse / QueryMetadata | Implemented | file_results, memory_results, prior_runs, query_metadata; Context Assembler and API use `response.file_results`. |
| Search config (config.yaml) | Implemented | `get_search_config()`: engine, max_results, whoosh_index_path, weights, expansion options; env HARLE_SEARCH_ENGINE, HARLE_WHOOSH_INDEX_PATH. |
| TRD error handling | Partially implemented | Whoosh missing/corrupt → rebuild; missing file skipped. No PG-unreachable fallback, no timeout. → Best practices §9. |
| Integration (Context Assembler) | Implemented | Assembler uses `SearchResponse.file_results`; API and vault tools use `response.file_results`. |

### Best practices (§) alignment

| Best practices § | Current status | Notes |
|------------------|----------------|-------|
| §4.4 Context Assembly: relevance scoring | Implemented | Six-term weighted formula in ranker (search_relevance/bm25 + metadata_match/tag_match + recency + source_priority + memory_confidence + prior_run_success); `memory_confidence` is currently stubbed to 0.0 for file-only ranking. |
| §5 Chunking strategy | Implemented | Section/paragraph chunking, cascading paths, index-time enrichment; assembler re-chunk for P1. |
| §6 Retrieval: hybrid search | Partially implemented | BM25 (Whoosh) implemented; pgvector and RRF for hybrid not yet. |
| §6 Metadata pre-filter (scope, tags, P0) | Implemented | get_candidates_for_search with context/global, tag overlap, P0 injection. |
| §7 Memory in search | Implemented | search_memories, search_similar_runs; MemoryResult, PriorRunResult in response. |
| §9 Failure-mode mitigations | Partially implemented | Deduplication by path in ranker; Whoosh rebuild on corrupt; no reranking. |

---

## What Is Implemented

### 1. Phase 1 and Phase 2 engine

`engine.py` supports both pipelines. **Default:** `search.engine` is `"whoosh"` (Phase 2): expand (query_expander), `get_candidates_for_search`, Whoosh search (with rebuild on missing/corrupt), `get_entries_by_paths` enrichment, `search_memories` and `search_similar_runs`, rank, then `SearchResponse` with all four result lists and `QueryMetadata`. **Opt-in Phase 1:** set `search.engine: "keyword"` for tokenize, `get_all_entries`, load content from disk, `_compute_score`, sort, return `SearchResponse(file_results=..., query_metadata=..., memory_results=[], prior_runs=[])`.

### 2. Types and SearchResponse

`types.py`: **SearchQuery** (query, context, max_results, agent_role). **SearchResult** (file_path, title, score, context, tags, snippet, token_count, summary, source, last_modified, chunk_index, heading_path). **ExpandedQuery**, **QueryMetadata**, **MemoryResult**, **PriorRunResult**, **SearchResponse**. Callers use `response.file_results`; memories and prior runs are available for context assembly.

### 3. Query expansion, pre-filter, Whoosh, ranker

- **query_expander.py:** Tokenize, stopwords, Whoosh stemming, tag vocabulary match, optional role terms; returns `ExpandedQuery`.
- **file_index:** `get_all_tags`, `get_candidates_for_search` (context + global, tag overlap, P0 injection), `get_entries_by_paths`.
- **whoosh_index.py:** Schema (incl. chunk fields), `build_from_scratch`, `update_document` / `write_file_to_index`, `remove_documents_by_file_path`, `search` → `list[WhooshSearchHit]`, candidate filter on `file_path`.
- **ranker.py:** Input `list[WhooshSearchHit]`; normalized BM25 + tag_match + recency + source_priority + memory_confidence + prior_run_bonus; cap chunks per file; returns `list[SearchResult]`.

### 4. Memory and prior-run lookup

`db/memories.py`: `search_memories` (full-text on content, context_scope, confidence). `db/runs.py`: `search_similar_runs` (full-text on user_request/result_summary, context_scope, status=completed). Results mapped to `MemoryResult` and `PriorRunResult` in the engine.

### 5. Config and indexer–Whoosh wiring

`config.py`: `get_search_config()` (`search` YAML + env overrides); `get_chunking_config()` (`chunking` YAML: enabled, knowledge_token_threshold, contextual_enrichment, paragraph_max_tokens, max_chunks_per_file_in_results). Indexer sync uses chunk-aware Whoosh updates when `whoosh_index_path` is set. Bootstrap builds Whoosh on init/reindex when engine is whoosh and ensures index exists.

---

## What Is Only Partially Implemented

### 1. Error handling

Whoosh index missing or corrupt triggers rebuild. Missing files are skipped. The TRD also describes: PostgreSQL unreachable → fall back to Whoosh-only; search timeout (e.g. 500 ms) → cancel and return partial results. These are not implemented.

### 2. Context Assembler use of memories/prior runs

SearchResponse includes `memory_results` and `prior_runs`; the Context Assembler currently uses only `file_results`. Including memories and prior runs in the assembled context (e.g. a “Memories” / “Prior runs” section) is a small follow-up.

---

## What Is Not Implemented Yet

### 1. Phase 3: Semantic search (pgvector; Best Practices §6)

**Missing:** Embeddings table usage for query; pgvector similarity search; fusion of semantic and Whoosh results (RRF); optional reranking.

**What this would unlock:** Conceptual and paraphrase matching; full hybrid retrieval as in Best Practices §6.

### 2. Chunking: LLM contextual summaries

**Missing:** Optional LLM-generated one-line summary per chunk (Anthropic-style); current implementation uses heading path + first sentence/line heuristics in the indexed context block.

**What this would unlock:** Stronger reduction of orphaned-chunk failures on ambiguous passages.

### 3. Context Assembler: memories and prior runs in prompt text

**Missing:** `SearchResponse` already includes `memory_results` and `prior_runs`; assembler still injects only `file_results` into the system prompt.

**What this would unlock:** Personalized and run-history context without extra tool rounds.

### 4. Ranking: RRF across retrievers

**Missing:** Reciprocal Rank Fusion across retrievers.

**What this would unlock:** Stable fusion when Phase 3 adds a second ranked list.

### 5. TRD-level error handling

**Missing:** PostgreSQL unreachable → Whoosh-only fallback; search timeout; partial-result behaviour as in the Search TRD.

**What this would unlock:** More predictable behaviour under infra failure.

---

## Key Deviations From The TRD

### deleted_at not filtered

TRD pre-filter mentions `deleted_at IS NULL`. The `file_index` schema has no `deleted_at` column; the filter is omitted.

### Context Assembler uses only file_results for prompt body

Memories and prior runs are returned in `SearchResponse` but are not yet formatted into the assembled context text (see “What Is Not Implemented Yet”).

### TRD `chunker.py` path

Implementation lives at `src/harle/indexing/chunker.py` (not `src/harle/search/chunker.py` as in some TRD diagrams).

---

## Current Assessment

The Search Algorithm is **Phase 1 and Phase 2 implemented**, with **chunk-aware Whoosh** and **chunk-aware context assembly** for P1. Engine is selectable via `search.engine` (keyword or whoosh). Whoosh pipeline: query expansion, metadata pre-filter, BM25 over chunk documents, enrichment by vault file path, memory/prior-run lookup, weighted ranking with per-file chunk cap, and `SearchResponse`. Indexer and bootstrap keep the Whoosh index in sync (chunk rebuild per changed file).

**Strengths:**

- Phase 1 and Phase 2 pipelines; `get_search_config` and `get_chunking_config`.
- Chunk indexing and retrieval aligned with Data Layer Best Practices §5 (except LLM chunk summaries).
- Full SearchResponse; stable `WhooshSearchHit` → ranker → `SearchResult` contract.

**Possible next steps:**

- Phase 3: embeddings, pgvector, RRF with Whoosh, optional reranking.
- Assembler sections for memory_results / prior_runs; search timeout and PG-unreachable fallback.
- Optional LLM contextual summary per chunk at index time.
