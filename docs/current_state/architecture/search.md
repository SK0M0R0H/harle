---
title: "Harle Search Algorithm — Current State"
tags: [search, current-state, architecture, whoosh, retrieval, implementation-status]
context: global
last_updated: 2026-03-11
summary: "Tracks what the Search Algorithm implements vs the TRD (search.md and data.md), and what each missing part would unlock."
---

# Harle Search Algorithm — Current State

> This document compares the target design in the Search Algorithm TRD with the code in `src/harle/search`. It describes what is implemented, what is partial, and what is missing, and what each missing part would unlock.

Reference TRD: [Harle Search Algorithm — Architecture & Functionality](../../trd/architecture/search.md). See also [Data Layer](../../trd/architecture/data.md) §3 for the high-level Search Algorithm summary. Research-backed retrieval and assembly recommendations: [Data Layer Best Practices](../../trd/architecture/data_layer_best_practices.md).

---

## Overall Status

The Search Algorithm is in **Phase 1 only**. The codebase implements simple keyword search over the indexed dataset: tokenize query, load all file-index entries (filtered by context), read each file from disk, score by term matching (title 3×, tag 2×, content 0.5× capped), sort and return top N. This matches the TRD’s Phase 1 description and works for small datasets (<100 files) with no extra dependencies beyond PostgreSQL.

Phase 2 (Whoosh full-text, query expansion, metadata pre-filtering, ranking and fusion, memory/history lookup) is **not implemented**: `query_expander.py`, `whoosh_index.py`, and `ranker.py` are stubs. The public interface is a subset of the TRD: callers get `list[SearchResult]` only; there is no `SearchResponse` with memories, prior runs, or query metadata. Chunking, semantic search (Phase 3), and search-related config/error-handling from the TRD are also not implemented.

Per **Data Layer Best Practices**: there is no hybrid/semantic retrieval (BM25 + pgvector, RRF, reranking); no three-tier memory integration in search (memories not queried); no explicit relevance scoring formula (search_relevance + metadata_match + recency + source_priority + memory_confidence + prior_run_success) or reranking.

---

## Implementation Snapshot

| TRD area | Current status | Notes |
|----------|----------------|-------|
| Phase 1: Simple keyword search | Implemented | `engine.py`: tokenize, get candidates by context, load content from disk, score (title/tag/content weights), sort, return top N. → Best practices §6 (keyword only; hybrid not implemented). |
| SearchQuery / SearchResult types | Implemented | `types.py`: query, context, max_results; file_path, title, score, context, tags, snippet. |
| Context-based candidate filter | Partially implemented | `db/file_index.get_all_entries(session, context=...)` filters by context only. No tag overlap, no P0 injection, no `deleted_at` or global-context handling. → Best practices §6 (metadata pre-filter). |
| Step 1: Query expansion | Not implemented | `query_expander.py` is a stub. No tokenize/normalize, role terms, tag vocabulary, or stemming. |
| Step 2: Metadata pre-filter (full) | Not implemented | No tag overlap (`tags && ARRAY[]`), no P0-always-included, no global context in scope. → Best practices §6 (metadata pre-filter). |
| Step 3: Whoosh full-text (BM25) | Not implemented | `whoosh_index.py` is a stub. No index build/update/query, no field boosts. → Best practices §6 (hybrid search). |
| Step 4: Metadata enrichment | Partially implemented | Results carry title, tags, context, snippet from engine. No token_count, summary, last_modified from DB in SearchResult. |
| Step 5: Memory and history lookup | Not implemented | No memories or prior-runs queries; no MemoryResult / PriorRunResult. → Best practices §7 (memory in search). |
| Step 6: Ranking and fusion | Not implemented | `ranker.py` is a stub. No RRF, no source priority, no deduplication. → Best practices §4.4 (relevance scoring), §9 (failure-mode mitigations). |
| Whoosh index management | Not implemented | No index build during sync, no incremental update, no rebuild on missing/corrupt. → Best practices §6. |
| Chunking strategy | Not implemented | No `chunker.py`; no section-level chunking or contextual enrichment. → Best practices §5. |
| Phase 3: Semantic search (pgvector) | Not implemented | Not started. → Best practices §6 (hybrid: pgvector). |
| SearchResponse / QueryMetadata | Not implemented | Callers get `list[SearchResult]` only. No file_results + memory_results + prior_runs + query_metadata. |
| Search config (config.yaml) | Not implemented | No `search.*` keys used; engine uses hardcoded weights and no whoosh_index_path. |
| TRD error handling | Partially implemented | Missing file skipped; encoding error skipped. No Whoosh rebuild, no PG-unreachable fallback, no timeout. → Best practices §9. |
| Integration (Context Assembler) | Partially implemented | Assembler calls `SearchEngine.search(query)` and gets a list of results; interface is simpler than TRD’s SearchResponse. |

### Best practices (§) alignment

| Best practices § | Current status | Notes |
|------------------|----------------|-------|
| §4.4 Context Assembly: relevance scoring | Not implemented | No weighted formula (search_relevance + metadata_match + recency + source_priority + memory_confidence + prior_run_success). |
| §5 Chunking strategy | Not implemented | No section-level chunking; no contextual enrichment; no chunker; retrieval is whole-file. |
| §6 Retrieval: hybrid search | Not implemented | Phase 1 keyword only; no BM25 + pgvector, no RRF, no reranking. |
| §6 Metadata pre-filter (scope, tags, P0) | Partially implemented | Context-scope filter only; no tag overlap, no P0-always-included, no global in scope. |
| §7 Memory in search | Not implemented | Memories table not queried; no MemoryResult; three-tier memory not integrated in search. |
| §9 Failure-mode mitigations | Not implemented | No deduplication by content hash in ranking; no reranking to reduce over-retrieval/orphaned chunks. |

---

## What Is Implemented

### 1. Phase 1 keyword search pipeline

`src/harle/search/engine.py` implements the TRD’s Phase 1 flow:

- **Tokenize:** `_tokenize(query.query)` — split on whitespace, lowercase, drop very short words.
- **Candidates:** `get_all_entries(session, context=query.context)` — all file_index rows (optionally filtered by context).
- **Score:** For each candidate, read file from disk; `_compute_score(terms, title, tags, content)` with title weight 3.0, tag 2.0, content 0.5 per term capped at 3.0.
- **Snippet:** `_extract_snippet(content, terms)` — short excerpt around first match.
- **Output:** Sort by score descending, slice to `query.max_results`, return `list[SearchResult]`.

This matches the TRD’s “Simple Keyword Search (current — implemented)” description: zero dependencies beyond PostgreSQL, good for datasets under ~100 files, with O(n) disk I/O and naive scoring.

### 2. Stable query and result types

`types.py` defines:

- **SearchQuery:** `query`, `context`, `max_results` — used by the engine and by callers (e.g. Context Assembler, vault tools).
- **SearchResult:** `file_path`, `title`, `score`, `context`, `tags`, `snippet` — sufficient for Phase 1 and for the current Context Assembler to consume.

These form the stable public interface; the TRD states that `SearchEngine.search(query) → list[SearchResult]` remains unchanged across Phase 2/3 migrations.

### 3. Context scope filtering

The engine passes `query.context` to `get_all_entries`. So when the orchestrator requests work or personal context, only files for that context are considered. This is the minimal form of the TRD’s “scope isolation” in the metadata pre-filter step.

### 4. Package layout and stubs for Phase 2

The TRD’s project structure is reflected: `engine.py`, `query_expander.py`, `whoosh_index.py`, `ranker.py`, `types.py`, `__init__.py`. The three non-engine modules are present as stubs with docstrings describing their future role, which keeps the migration path clear.

---

## What Is Only Partially Implemented

### 1. Metadata pre-filter (Step 2)

TRD Step 2 and Best Practices §6 specify:

- Scope: `(context = :context OR context = 'global' OR context IS NULL)`
- Tag overlap: `tags && ARRAY[:matched_tags]` (or skip if no tags matched)
- Exclude deleted: `deleted_at IS NULL`
- Optional: always include P0 files (prompts, policies)

Current behaviour:

- Only equality filter on `context` in `get_all_entries`; no “global” or NULL, so cross-context policies are not included.
- No tag-based filter.
- No `deleted_at` filter in the search path (indexer may set it elsewhere).
- No P0 injection.

So the “metadata pre-filter” exists only as context-scope filtering; the rest would unlock a much smaller candidate set (e.g. 30–100 files from 500+) before any content scoring.

### 2. Result shape and enrichment (Step 4)

SearchResult today has no `token_count`, `summary`, or `source`. The TRD uses these for token-budget planning and for the Context Assembler to decide inclusion without reading full content. The assembler can still work with the current shape but cannot do budget-aware packing or quick relevance checks from summaries.

### 3. Error handling

Engine skips missing files and files that fail to read (e.g. encoding). The TRD additionally describes: Whoosh index missing → rebuild; Whoosh corrupted → delete and rebuild; PostgreSQL unreachable → fall back to Whoosh-only; search timeout → cancel and return partial results. None of these are implemented, so behaviour in failure modes is narrower than the TRD.

### 4. Context Assembler interface

The assembler receives a list of search results only. The TRD’s full contract is `SearchResponse` (file_results, memory_results, prior_runs, query_metadata). So the integration works for Phase 1 but does not yet expose memories, prior runs, or expansion/timing metadata.

---

## What Is Not Implemented Yet

### 1. Query expansion (Step 1)

**Missing:** `query_expander.py` implementation: tokenize/normalize, stopword removal, domain/role terms, tag vocabulary matching, stemming for Whoosh, and an `ExpandedQuery` (whoosh_terms, tag_filters, role_terms, context_filter, raw_query).

**What this would unlock:** Better recall without sacrificing precision; smaller, more relevant candidate set when combined with tag pre-filter; role-aware search (e.g. secretary always considering workflow/task terms); foundation for Phase 2 Whoosh queries.

### 2. Full metadata pre-filter (Step 2)

**Missing:** PostgreSQL query that applies context (including global), tag overlap, deleted_at, and optional P0 injection; candidate set of ~30–100 files instead of all files in context.

**What this would unlock:** Sub-50ms candidate retrieval; Whoosh only needs to score a small set; less disk I/O and better scalability.

### 3. Whoosh full-text search and hybrid retrieval (Step 3; Best Practices §6)

**Missing:** `whoosh_index.py`: schema (path, title, tags, content, context, modified), index build/update during sync, query with MultifieldParser and filter by candidate paths, BM25 with title/tag boosts. No storage of content in the index (content loaded from vault when needed). Best Practices §6: BM25 + pgvector pipeline, Reciprocal Rank Fusion, optional reranking phase.

**What this would unlock:** No file I/O at query time; sub-50ms full-text search; stemming and field boosts; scalable search for 100–1,000+ files; conceptual and paraphrase match for large or diverse datasets.

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

### Return type is list[SearchResult] only

The TRD specifies a rich `SearchResponse` (file_results, memory_results, prior_runs, query_metadata). The implementation returns only a list of file results. This is an intentional simplification for Phase 1; extending the return type will be required for Phase 2 (memories, prior runs, metadata).

### Context filter does not include global

TRD says files with `context = 'global'` (or NULL) should be candidates in both work and personal. `get_all_entries` only filters by equality on context, so global-scope files are not currently included when a specific context is requested.

### No search config yet

Weights and limits are hardcoded in the engine. The TRD describes a full `search:` section in config and env overrides; that is left for Phase 2.

### chunker.py not present

TRD project structure mentions `chunker.py` as “(future)”. The repo has no chunker module yet; that is consistent with the TRD but worth noting for the implementation snapshot.

### Best Practices: relevance scoring and memory

Data Layer Best Practices §4.4 recommends an explicit weighted relevance formula for context assembly; §7 recommends memory integration in search (memories queried and included in context). Neither is implemented yet.

---

## Current Assessment

The Search Algorithm is **Phase 1 complete and Phase 2 not started**.

**Strengths:**

- Phase 1 keyword search is implemented and used by the Context Assembler and vault tools.
- Public types (SearchQuery, SearchResult) are in place and match current needs.
- Stubs for query_expander, whoosh_index, and ranker preserve the TRD structure and migration path.

**Gaps that matter most for the next step:**

- **Whoosh index and engine wiring:** Without Whoosh and the full 6-step pipeline, search does not scale beyond small datasets and does not use tag/pre-filter or ranking.
- **Query expansion and metadata pre-filter:** These directly reduce the candidate set and improve recall, and are prerequisites for effective Whoosh use.
- **SearchResponse and memory/prior-run lookup:** Needed for the TRD’s full context-assembly story (memories, prior runs, query metadata).

The next meaningful milestone is **Phase 2**: implement Whoosh index lifecycle and query, query expansion, full metadata pre-filter, ranker (RRF + weights), then optionally add memory/history lookup and the full SearchResponse so the Context Assembler can consume the full TRD contract. Implementing these would also align with the Data Layer Best Practices TRD (hybrid retrieval §6, memory in search §7, relevance scoring §4.4, reranking §9).
