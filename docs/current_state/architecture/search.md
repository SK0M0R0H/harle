---
title: "Harle Search Algorithm — Current State"
tags: [search, current-state, architecture, whoosh, retrieval, implementation-status]
context: global
last_updated: 2026-03-17
summary: "Tracks what the Search Algorithm implements vs the TRD (search.md and data.md), and what each missing part would unlock."
---

# Harle Search Algorithm — Current State

> This document compares the target design in the Search Algorithm TRD with the code in `src/harle/search`. It describes what is implemented, what is partial, and what is missing, and what each missing part would unlock.

Reference TRD: [Harle Search Algorithm — Architecture & Functionality](../../trd/architecture/search.md). See also [Data Layer](../../trd/architecture/data.md) §3 for the high-level Search Algorithm summary. Research-backed retrieval and assembly recommendations: [Data Layer Best Practices](../../trd/architecture/data_layer_best_practices.md).

---

## Overall Status

The Search Algorithm supports **Phase 1 (keyword) and Phase 2 (Whoosh)**. The default engine is **Whoosh**; set `search.engine: "keyword"` to use Phase 1. Phase 1: tokenize query, load file_index entries by context, read files from disk, score by term matching, return top N. Phase 2: query expansion (tokenize, stem, tag vocabulary, role terms), metadata pre-filter (context + global, tag overlap, P0 injection), Whoosh BM25 search over candidates, metadata enrichment, memory and prior-run lookup, weighted ranking (BM25 + tag match + recency + source priority + prior-run bonus), and `SearchResponse` (file_results, memory_results, prior_runs, query_metadata). Whoosh index is built from scratch on init/reindex when engine is whoosh and updated incrementally during sync.

**Not implemented:** Chunking (`chunker.py`), Phase 3 (pgvector semantic search, hybrid RRF, reranking), `deleted_at` filter on file_index, search timeout, and PostgreSQL-unreachable fallback. Per **Data Layer Best Practices**: hybrid (BM25 + pgvector) and reranking are not implemented; memory and prior-run lookup are implemented and included in the response.

---

## Implementation Snapshot

| TRD area | Current status | Notes |
|----------|----------------|-------|
| Phase 1: Simple keyword search | Implemented | `engine.py`: tokenize, get candidates by context, load content from disk, score (title/tag/content weights), sort; returns `SearchResponse` with `file_results`. |
| Phase 2: Whoosh pipeline | Implemented | Engine branch when `search.engine: whoosh`: expand → pre-filter → Whoosh search → enrich → memory/prior-run → rank; returns `SearchResponse`. |
| SearchQuery / SearchResult types | Implemented | `types.py`: SearchQuery (query, context, max_results, agent_role); SearchResult (+ token_count, summary, source, last_modified). |
| Step 1: Query expansion | Implemented | `query_expander.py`: tokenize, stopwords, stemming (Whoosh), tag vocabulary match, role terms; `ExpandedQuery`. |
| Step 2: Metadata pre-filter (full) | Implemented | `get_candidates_for_search`: context + global/NULL, tag overlap, P0 (prompts/policies) always included. No `deleted_at` (schema has none). |
| Step 3: Whoosh full-text (BM25) | Implemented | `whoosh_index.py`: schema (path, title, tags, content, context, modified), build_from_scratch, update/remove, search with candidate filter. |
| Step 4: Metadata enrichment | Implemented | `get_entries_by_paths`; SearchResult has token_count, summary, last_modified; ranker and engine populate them. |
| Step 5: Memory and history lookup | Implemented | `memories.search_memories`, `runs.search_similar_runs`; MemoryResult, PriorRunResult in SearchResponse. → Best practices §7. |
| Step 6: Ranking and fusion | Implemented | `ranker.py`: normalized BM25 + tag_match + recency + source_priority + prior_run_bonus; dedupe by path; configurable weights. → Best practices §4.4. |
| Whoosh index management | Implemented | Build on init/reindex when engine=whoosh; incremental update/remove in indexer sync; rebuild on missing/corrupt in engine. |
| Chunking strategy | Not implemented | No `chunker.py`; no section-level chunking. → Best practices §5. |
| Phase 3: Semantic search (pgvector) | Not implemented | Not started. → Best practices §6 (hybrid: pgvector). |
| SearchResponse / QueryMetadata | Implemented | file_results, memory_results, prior_runs, query_metadata; Context Assembler and API use `response.file_results`. |
| Search config (config.yaml) | Implemented | `get_search_config()`: engine, max_results, whoosh_index_path, weights, expansion options; env HARLE_SEARCH_ENGINE, HARLE_WHOOSH_INDEX_PATH. |
| TRD error handling | Partially implemented | Whoosh missing/corrupt → rebuild; missing file skipped. No PG-unreachable fallback, no timeout. → Best practices §9. |
| Integration (Context Assembler) | Implemented | Assembler uses `SearchResponse.file_results`; API and vault tools use `response.file_results`. |

### Best practices (§) alignment

| Best practices § | Current status | Notes |
|------------------|----------------|-------|
| §4.4 Context Assembly: relevance scoring | Implemented | Weighted formula in ranker (bm25 + tag_match + recency + source_priority + prior_run). |
| §5 Chunking strategy | Not implemented | No section-level chunking; retrieval is whole-file. |
| §6 Retrieval: hybrid search | Partially implemented | BM25 (Whoosh) implemented; pgvector and RRF for hybrid not yet. |
| §6 Metadata pre-filter (scope, tags, P0) | Implemented | get_candidates_for_search with context/global, tag overlap, P0 injection. |
| §7 Memory in search | Implemented | search_memories, search_similar_runs; MemoryResult, PriorRunResult in response. |
| §9 Failure-mode mitigations | Partially implemented | Deduplication by path in ranker; Whoosh rebuild on corrupt; no reranking. |

---

## What Is Implemented

### 1. Phase 1 and Phase 2 engine

`engine.py` supports both pipelines. **Default:** `search.engine` is `"whoosh"` (Phase 2): expand (query_expander), `get_candidates_for_search`, Whoosh search (with rebuild on missing/corrupt), `get_entries_by_paths` enrichment, `search_memories` and `search_similar_runs`, rank, then `SearchResponse` with all four result lists and `QueryMetadata`. **Opt-in Phase 1:** set `search.engine: "keyword"` for tokenize, `get_all_entries`, load content from disk, `_compute_score`, sort, return `SearchResponse(file_results=..., query_metadata=..., memory_results=[], prior_runs=[])`.

### 2. Types and SearchResponse

`types.py`: **SearchQuery** (query, context, max_results, agent_role). **SearchResult** (file_path, title, score, context, tags, snippet, token_count, summary, source, last_modified). **ExpandedQuery**, **QueryMetadata**, **MemoryResult**, **PriorRunResult**, **SearchResponse**. Callers use `response.file_results`; memories and prior runs are available for context assembly.

### 3. Query expansion, pre-filter, Whoosh, ranker

- **query_expander.py:** Tokenize, stopwords, Whoosh stemming, tag vocabulary match, optional role terms; returns `ExpandedQuery`.
- **file_index:** `get_all_tags`, `get_candidates_for_search` (context + global, tag overlap, P0 injection), `get_entries_by_paths`.
- **whoosh_index.py:** Schema, `build_from_scratch`, `update_document`, `remove_document`, `search` with candidate-path filter.
- **ranker.py:** Normalized BM25 + tag_match + recency + source_priority + prior_run_bonus; dedupe by path; returns `list[SearchResult]`.

### 4. Memory and prior-run lookup

`db/memories.py`: `search_memories` (full-text on content, context_scope, confidence). `db/runs.py`: `search_similar_runs` (full-text on user_request/result_summary, context_scope, status=completed). Results mapped to `MemoryResult` and `PriorRunResult` in the engine.

### 5. Config and indexer–Whoosh wiring

`config.py`: `get_search_config()` reads `search` from YAML, env overrides `HARLE_SEARCH_ENGINE`, `HARLE_WHOOSH_INDEX_PATH`; returns `SearchConfig` with engine, whoosh_index_path, weights, expansion options. Indexer accepts optional `whoosh_index_path`; sync updates/removes Whoosh documents for changed/deleted files. Bootstrap builds Whoosh on init/reindex when engine is whoosh and ensures index exists.

---

## What Is Only Partially Implemented

### 1. Error handling

Whoosh index missing or corrupt triggers rebuild. Missing files are skipped. The TRD also describes: PostgreSQL unreachable → fall back to Whoosh-only; search timeout (e.g. 500 ms) → cancel and return partial results. These are not implemented.

### 2. Context Assembler use of memories/prior runs

SearchResponse includes `memory_results` and `prior_runs`; the Context Assembler currently uses only `file_results`. Including memories and prior runs in the assembled context (e.g. a “Memories” / “Prior runs” section) is a small follow-up.

---

## What Is Not Implemented Yet

### 1. Chunking strategy (Best Practices §5)

**Missing:** `chunker.py` (or equivalent); section-level chunking at H2 boundaries; cascading metadata; optional contextual enrichment; chunk-aware indexing and retrieval for files > ~2,500 tokens.

**What this would unlock:** Accurate retrieval for long files; better use of context window; alignment with Best Practices §5.

### 2. Phase 3: Semantic search (pgvector; Best Practices §6)

**Missing:** Embeddings table usage; embedding API for index/query; pgvector similarity search; fusion of semantic and Whoosh results; optional reranking.

**What this would unlock:** Conceptual and paraphrase matching when keyword search fails; hybrid (BM25 + pgvector) as in Best Practices §6.

### 4. Metadata enrichment (Step 4) and result types

**Missing:** Loading token_count, summary, last_modified (and optionally char_count) from file_index for top results; adding these and `source` to SearchResult (or equivalent). Optional: SearchResponse, QueryMetadata, MemoryResult, PriorRunResult.

**What this would unlock:** Token-budget-aware context assembly; quick relevance checks via summaries; recency and source used in ranking.

### 5. Memory and history lookup (Step 5; Best Practices §7)

**Missing:** Queries to `memories` and `runs` (context-scoped, confidence/status filters, full-text on content/request/summary); returning MemoryResult and PriorRunResult in the search response. Best Practices §7: three-tier memory (working/episodic/semantic) not integrated in search; memories table exists but is not queried.

**What this would unlock:** Personalized context (preferences, past decisions) and prior run context so the agent can avoid repeating mistakes and build on past work.

### 6. Ranking and fusion (Step 6; Best Practices §4.4, §9)

**Missing:** `ranker.py`: Reciprocal Rank Fusion of BM25 and metadata signals; source priority weights (prompts/policies P0, workflows P1, etc.); recency and tag-match scoring; deduplication by file_path; configurable weights (bm25_weight, tag_match_weight, etc.). Best Practices §4.4: no explicit relevance scoring formula (search_relevance + metadata_match + recency + source_priority + memory_confidence + prior_run_success); §9: optional reranking to reduce over-retrieval and orphaned-chunk issues.

**What this would unlock:** A single ranked list that combines relevance, recency, and source priority; stable behaviour across score scales via RRF; consistent, tunable ranking and inclusion decisions in the assembler.

### 7. Whoosh index management

**Missing:** Building the Whoosh index during sync (when file is new or content_hash changed); incremental update per file; index path from config; rebuild on missing/corrupt index (startup or `harle index rebuild`).

**What this would unlock:** Index always in sync with the vault; no full scan at query time; predictable behaviour when the index is missing or damaged.

### 8. Chunking strategy (Best Practices §5)

**Missing:** `chunker.py` (or equivalent); section-level chunking at H2 boundaries; cascading metadata; optional contextual enrichment; chunk-aware indexing and retrieval for files > ~2,500 tokens.

**What this would unlock:** Accurate retrieval for long files; better use of context window by selecting relevant sections instead of whole files; alignment with Best Practices §5 (section-level chunking, contextual summary per chunk).

### 9. Search configuration

**Missing:** Reading `search.*` from config (engine, max_results, min_score, whoosh_index_path, title_boost, tag_boost, ranking weights, memory/prior_run limits, expansion/chunking/semantic/reranking options); environment overrides (e.g. HARLE_WHOOSH_INDEX_PATH, HARLE_SEARCH_ENGINE).

**What this would unlock:** Tuning without code changes; switching engine (keyword/whoosh/hybrid) and behaviour per deployment.

### 10. Phase 3: Semantic search (pgvector; Best Practices §6)

**Missing:** Embeddings table usage; embedding API for index/query; pgvector similarity search; fusion of semantic and Whoosh results; optional reranking.

**What this would unlock:** Conceptual and paraphrase matching when keyword search fails (“data protection” ↔ “privacy compliance”); better behaviour for large or conceptually diverse datasets; hybrid (BM25 + pgvector) as in Best Practices §6.

### 11. TRD-level error handling

**Missing:** Whoosh missing/corrupt → rebuild; PostgreSQL unreachable → Whoosh-only fallback; timeout on search; clear logging and user-facing messages as in the TRD table.

**What this would unlock:** Robust behaviour when the index or database is unavailable; predictable recovery and operator visibility.

---

## Key Deviations From The TRD

### deleted_at not filtered

TRD pre-filter mentions `deleted_at IS NULL`. The `file_index` schema has no `deleted_at` column; the filter is omitted.

### chunker.py not present

TRD project structure mentions `chunker.py` as "(future)". The repo has no chunker module yet.

### Context Assembler uses only file_results

Memories and prior runs are returned in `SearchResponse` but are not yet included in the assembled context text; that can be a follow-up.

### chunker.py not present

TRD project structure mentions `chunker.py` as “(future)”. The repo has no chunker module yet; that is consistent with the TRD but worth noting for the implementation snapshot.


---

## Current Assessment

The Search Algorithm is **Phase 1 and Phase 2 implemented**. Engine is selectable via `search.engine` (keyword or whoosh). Whoosh pipeline: query expansion, metadata pre-filter, BM25 search, enrichment, memory/prior-run lookup, weighted ranking, and SearchResponse. Indexer and bootstrap keep the Whoosh index in sync.

**Strengths:**

- Phase 1 and Phase 2 pipelines; config-driven engine selection.
- Full SearchResponse (file_results, memory_results, prior_runs, query_metadata); Context Assembler and API use file_results.
- Search config (get_search_config), Whoosh index lifecycle (build, incremental update, rebuild on corrupt).

**Possible next steps:**

- Include memory_results and prior_runs in the assembled context (e.g. a short section).
- Phase 3: pgvector semantic search, hybrid RRF, optional reranking.
- Chunking for long files; search timeout and PG-unreachable fallback.
