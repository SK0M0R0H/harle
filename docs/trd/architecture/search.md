---
title: "Harle Search Algorithm — Architecture & Functionality"
tags: [search, architecture, whoosh, pgvector, retrieval, ranking, query-expansion, bm25]
context: global
last_updated: 2026-03-02
summary: "Detailed design of the Search Algorithm — query expansion, metadata pre-filtering, full-text indexing, multi-source ranking, semantic search roadmap, chunking, and the evolution plan from simple keyword search to hybrid retrieval."
---

# Harle Search Algorithm — Architecture & Functionality

> The Search Algorithm is the bridge between your data and every agent response. It answers one question for every request: "Given what the user asked, which pieces of their data should the agent see?"

This document is the detailed technical reference for Harle's Search Algorithm. It covers the full retrieval pipeline — from receiving a raw user query to returning a ranked, token-budgeted set of results — the evolution plan from simple keyword search through Whoosh full-text search to hybrid retrieval with pgvector, the chunking strategy, configuration, error handling, and project structure.

For the high-level overview of the Data Layer (User Dataset, Indexer, Search Algorithm), see [data.md](./data.md).
For the Orchestrator (which consumes search results), see [orchestrator.md](./orchestrator.md).
For research-backed best practices underlying these design decisions, see [data_layer_best_practices.md](./data_layer_best_practices.md).

---

## Where the Search Algorithm Sits

```
                   ORCHESTRATOR
                        │
                   Context Assembler
                        │
                   asks: "what is relevant?"
                        │
                        ▼
               ┌─────────────────┐
               │ Search Algorithm │
               │                 │
               │  1. Expand query│
               │  2. Pre-filter  │─── PostgreSQL (file_index, memories, runs)
               │  3. Score       │─── Whoosh index (BM25 full-text)
               │  4. Enrich      │─── PostgreSQL (metadata, token counts)
               │  5. Rank & fuse │
               │  6. Return      │
               └────────┬────────┘
                        │
               ranked results + metadata
                        │
                        ▼
               Context Assembler
               loads file content, packs into
               token-budgeted context package
```

The Search Algorithm is **stateless** — it stores nothing. It reads from the Whoosh index (on disk), queries PostgreSQL, and returns results. The Context Assembler owns the token budget and decides what ultimately reaches the agent.

---

## The Core Problem

Language models have a limited context window. Your dataset can be far larger. The Search Algorithm reduces thousands of pages to the 5–10 most relevant ones.

```
Full dataset                 Search Algorithm             Agent sees
(1,000+ pages)               narrows it down              (5–10 pages)

┌──────────────┐                                     ┌──────────────┐
│ prompts/     │                                     │ secretary.md │
│ policies/    │     query: "stalled Trello tasks"   │ task-triage  │
│ workflows/   │ ──────────────────────────────────> │   .md        │
│ knowledge/   │         relevance ranking           │ approval-    │
│   500+ files │                                     │   rules.md   │
│ logs/        │                                     │ 2 prior runs │
│ examples/    │                                     └──────────────┘
└──────────────┘
```

This is not a web search engine. It solves a different problem — **context selection** for an LLM that must produce a personalized, high-quality response from your data. The requirements differ from web search:

| Web search | Harle search |
|---|---|
| Returns links | Returns file content + metadata |
| User picks the right result | System must pick the right results automatically |
| Relevance only | Relevance + priority + recency + token budget |
| Millions of documents | Hundreds to low thousands |
| Latency budget: seconds | Latency budget: <100ms |

---

## Evolution Plan: Three Phases

The Search Algorithm is designed to evolve in three phases. Each phase fully works on its own — later phases extend, not replace, earlier ones.

### Phase 1: Simple Keyword Search (current — implemented)

A baseline that works immediately for small datasets (<100 files). Iterates all indexed files, loads content from disk, and scores by case-insensitive term matching with field-weighted scoring.

```
User query
    │
    ▼
Tokenize into terms
    │
    ▼
Load all file_index entries (filtered by context)
    │
    ▼
For each file: load content, compute score
    Score = Σ(term_in_title × 3.0
            + term_in_tag × 2.0
            + min(term_count_in_content × 0.5, 3.0))
    │
    ▼
Sort by score, return top N
```

**Strengths:** Zero dependencies beyond PostgreSQL. Works out of the box. Good enough for datasets under 100 files.

**Limitations:** Reads every file on every query (O(n) disk I/O). No inverted index. No stemming or fuzzy matching. No query expansion. Scoring is naive.

### Phase 2: Whoosh Full-Text Search + Metadata Pre-Filtering (target — next)

Replaces file scanning with an inverted index. Adds metadata pre-filtering in PostgreSQL to narrow the candidate set before content search.

```
User query
    │
    ▼
Query expansion (extract + enrich terms)
    │
    ▼
Metadata pre-filter (PostgreSQL file_index)
    → context, tags, priority
    → candidate set: ~30–100 files
    │
    ▼
Whoosh BM25 search over candidates
    → field boosts: title 2x, tags 1.5x
    → ranked results with relevance scores
    │
    ▼
Metadata enrichment (token_count, summary, recency)
    │
    ▼
Memory + history lookup (PostgreSQL memories, runs)
    │
    ▼
Multi-source ranking (Reciprocal Rank Fusion)
    │
    ▼
Return top N results
```

**Strengths:** Sub-50ms queries regardless of dataset size. BM25 scoring with stemming. Field boosts. No file I/O at query time (only index lookups). Metadata pre-filtering dramatically reduces the search space.

### Phase 3: Hybrid Retrieval with Semantic Search (future)

Adds pgvector embeddings alongside Whoosh. Two retrieval channels run in parallel and results are fused.

```
User query
    │
    ▼
Query expansion
    │
    ▼
Metadata pre-filter (PostgreSQL)
    │
    ├──────────────────────────┐
    │                          │
    ▼                          ▼
Whoosh BM25               pgvector semantic
(keyword match)            (meaning match)
    │                          │
    └──────────┬───────────────┘
               │
               ▼
    Reciprocal Rank Fusion
               │
               ▼
    Optional reranking (cross-encoder or LLM)
               │
               ▼
    Token budget fitting
               │
               ▼
    Return top N results
```

**When to move to Phase 3:** When users report "I know I wrote about this but the agent didn't find it" — indicating vocabulary mismatch that keyword search cannot resolve. Expected trigger: dataset exceeds ~500 files or content becomes conceptually diverse.

---

## The Full Search Pipeline (Phase 2 — detailed design)

This section describes the target pipeline in detail. Each step is a separate module with a clear interface.

### Step 1: Query Expansion

**Module:** `search/query_expander.py`

**Purpose:** Transform a raw user request into a rich set of search terms that maximize recall without sacrificing precision.

**How it works:**

```
Input: "Find stalled tasks in Trello and suggest reformulations"
       agent_role: "secretary"

   │
   ▼
1. Tokenize and normalize
   → ["find", "stalled", "tasks", "trello", "suggest", "reformulations"]
   → Drop stopwords: ["stalled", "tasks", "trello", "suggest", "reformulations"]

   │
   ▼
2. Extract domain terms
   → Recognize "Trello" as a known integration → add tag: "trello"
   → Recognize "tasks" as a task-management concept → add tag: "task-management"

   │
   ▼
3. Add role-specific terms
   → Secretary role always adds: ["workflow", "task-management", "status"]
   → These are configured per role in the agent prompt or search config

   │
   ▼
4. Match against tag vocabulary
   → Load known tags from file_index (cached)
   → "stalled" does not match any tag
   → "trello" matches tag "trello"
   → "tasks" matches tags "task-management", "tasks"
   → Matched tags go into the metadata pre-filter

   │
   ▼
5. Stem / normalize for Whoosh
   → "reformulations" → "reformulat" (Porter stemmer)
   → "stalled" → "stall"
   → Stemmed terms go into the Whoosh query

   │
   ▼
Output: ExpandedQuery(
    whoosh_terms=["stall", "task", "trello", "suggest", "reformulat"],
    tag_filters=["trello", "task-management"],
    role_terms=["workflow", "task-management", "status"],
    context_filter="work",
    raw_query="Find stalled tasks in Trello and suggest reformulations"
)
```

**Design decisions:**

- **No LLM call for expansion.** Query expansion runs on every request and must be fast (<5ms) and free. Using an LLM for expansion would add 500ms+ latency and cost. Rule-based expansion (role terms, tag vocabulary matching, stemming) is sufficient for a personal dataset where the tag vocabulary is small and well-known.
- **Role-specific terms are configurable.** Each agent role can define extra search terms in `config.yaml` or in the role prompt file. This makes search role-aware without hardcoding.
- **Tag vocabulary is cached.** The set of all known tags is loaded from `file_index` on startup and refreshed on sync. Matching against it is a set-intersection operation — microseconds.

### Step 2: Metadata Pre-Filter (PostgreSQL)

**Module:** `search/engine.py` (calls `db/file_index.py`)

**Purpose:** Narrow the candidate set from the full file index to a small subset using structured metadata queries. This avoids searching files that cannot possibly be relevant.

**How it works:**

```sql
SELECT file_path, title, tags, token_count, summary, last_modified
FROM file_index
WHERE
    -- Scope isolation: only files matching the active context
    (context = :context OR context = 'global' OR context IS NULL)

    -- Tag matching: files that share tags with the query
    AND (
        tags && ARRAY[:matched_tags]    -- array overlap operator
        OR :no_tag_filter               -- if no tags matched, skip this filter
    )

    -- Exclude deleted files
    AND deleted_at IS NULL

ORDER BY last_modified DESC;
```

**Result:** A candidate set of typically 30–100 files (from 500+). This set is passed to Whoosh for content scoring.

**Design decisions:**

- **Always include P0 files.** Agent prompts and active policies are always injected into the candidate set regardless of query content. The Context Assembler handles P0 separately, but the search pipeline also surfaces them so ranking is aware of their existence.
- **Context scope includes "global."** Files with `context = 'global'` (like cross-cutting policies) are always candidates in both work and personal contexts.
- **Tag matching uses PostgreSQL array operators.** The `&&` operator checks for array overlap — efficient with a GIN index on the `tags` column.

### Step 3: Full-Text Search (Whoosh BM25)

**Module:** `search/whoosh_index.py`

**Purpose:** Score each candidate file against the expanded query terms using BM25 relevance scoring with field boosts.

**Whoosh schema:**

```python
from whoosh.fields import Schema, TEXT, ID, KEYWORD, DATETIME, STORED

schema = Schema(
    path=ID(stored=True, unique=True),
    title=TEXT(stored=True, field_boost=2.0),
    tags=KEYWORD(stored=True, commas=True, field_boost=1.5),
    content=TEXT(stored=False),
    context=ID(stored=True),
    modified=DATETIME(stored=True),
)
```

**Key field design:**

| Field | Type | Stored? | Boost | Why |
|---|---|---|---|---|
| `path` | ID | Yes | — | Unique identifier; used to join with PostgreSQL results |
| `title` | TEXT | Yes | 2.0x | Title matches are strongly indicative of relevance |
| `tags` | KEYWORD | Yes | 1.5x | Tag matches indicate topical relevance |
| `content` | TEXT | No | 1.0x | Full text indexed for search but not stored (saves space) |
| `context` | ID | Yes | — | Filter field, not scored |
| `modified` | DATETIME | Yes | — | Used for recency ranking in the fusion step |

**Why `content` is not stored:** The index only needs to know *which words appear in which files* — it does not need to store the full text. Content is loaded from the vault file system when needed (by the Context Assembler, not the search engine). This keeps the Whoosh index small (~5 MB for 500 files vs. potentially 50+ MB if content were stored).

**BM25 scoring:** Whoosh uses the Okapi BM25F scoring algorithm by default, which considers:
- **Term frequency (TF):** How often the search term appears in the document. Diminishing returns — the 10th occurrence matters less than the 1st.
- **Inverse document frequency (IDF):** Rare terms across the corpus score higher. "Trello" appearing in 3 files is more discriminating than "task" appearing in 50.
- **Document length normalization:** Longer documents are slightly penalized to avoid them dominating results just because they contain more words.
- **Field boosts:** Title matches get 2x weight, tag matches get 1.5x, as defined in the schema.

**Querying the index:**

```python
from whoosh.qparser import MultifieldParser

parser = MultifieldParser(
    ["title", "tags", "content"],
    schema=schema,
)
query = parser.parse("stall task trello reformulat")

with index.searcher() as searcher:
    results = searcher.search(
        query,
        limit=50,
        filter=terms_filter,  # restrict to candidate file paths from Step 2
    )
```

**How filtering integrates with Step 2:** Whoosh supports a `filter` parameter that restricts results to a pre-defined set of document IDs. The candidate paths from the PostgreSQL pre-filter are converted to a Whoosh filter, so Whoosh only scores files that passed the metadata check. This combines the speed of metadata filtering with the accuracy of BM25 scoring.

### Step 4: Metadata Enrichment

**Module:** `search/engine.py` (calls `db/file_index.py`)

**Purpose:** For the top results from Whoosh, load additional metadata from PostgreSQL that the ranking step needs.

**Enrichment fields:**

| Field | Source | Used for |
|---|---|---|
| `token_count` | `file_index.token_count` | Token budget planning — Context Assembler needs to know how much budget each file will consume before loading it |
| `summary` | `file_index.summary` | Quick relevance sanity-check; also included in results for the Context Assembler to decide inclusion without reading the full file |
| `last_modified` | `file_index.last_modified` | Recency scoring — newer files get a boost |
| `char_count` | `file_index.char_count` | Secondary size indicator |

### Step 5: Memory and History Lookup

**Module:** `search/engine.py` (calls `db/memories.py`, `db/runs.py`)

**Purpose:** Find relevant user preferences, past decisions, and prior run results that should be included alongside file results.

**Memory search:**

```sql
SELECT content, category, confidence, context_scope
FROM memories
WHERE
    active = TRUE
    AND (context_scope = :context OR context_scope = 'global')
    AND confidence >= :min_confidence
ORDER BY confidence DESC, updated_at DESC
LIMIT 10;
```

Memories with keywords matching the query terms are ranked higher. Full-text search on the `content` column is done via PostgreSQL's built-in `tsvector`:

```sql
AND to_tsvector('english', content) @@ plainto_tsquery('english', :query)
```

**Prior run lookup:**

```sql
SELECT run_id, user_request, result_summary, files_used, agent
FROM runs
WHERE
    context_scope = :context
    AND status = 'completed'
    AND to_tsvector('english', user_request || ' ' || COALESCE(result_summary, ''))
        @@ plainto_tsquery('english', :query)
ORDER BY timestamp DESC
LIMIT 5;
```

This finds past runs where the user asked a similar question. The Context Assembler may include prior results to help the agent avoid repeating past mistakes or to build on prior work.

### Step 6: Ranking and Fusion

**Module:** `search/ranker.py`

**Purpose:** Combine results from all sources (Whoosh scores, metadata signals, memories, prior runs) into a single ranked list.

**Reciprocal Rank Fusion (RRF):**

When multiple retrievers produce rankings, RRF is the standard way to combine them. For each result *d*, the fused score is:

```
RRF_score(d) = Σ  1 / (k + rank_i(d))
               i
```

Where `k` is a constant (typically 60) and `rank_i(d)` is the rank of document *d* in retriever *i*. This method is robust to score-scale differences between retrievers.

**In Phase 2** (Whoosh only), RRF combines two "retrievers":
1. **BM25 relevance ranking** (from Whoosh)
2. **Metadata ranking** (recency + source priority + tag match count)

**In Phase 3** (hybrid), RRF will additionally include:
3. **Semantic similarity ranking** (from pgvector)

**Source priority weights:**

Files from different vault directories have different inherent priorities:

| Directory | Priority | Rationale |
|---|---|---|
| `prompts/` | P0 (always included) | Defines agent identity — must be in context |
| `policies/` | P0 (always included) | Defines constraints — must be in context |
| `workflows/` | P1 (high priority) | If matched, provides step-by-step guidance |
| `knowledge/` | P1–P2 (by relevance) | Core knowledge base — main search target |
| `examples/` | P2 (if relevant) | Helpful for output formatting |
| `logs/` | P3 (if budget allows) | Historical context — lower priority |

**Relevance score formula (Phase 2):**

```
Final_score(d) = (
    0.40 × normalized_bm25_score        # From Whoosh
  + 0.20 × tag_match_score              # Proportion of query tags matched
  + 0.15 × recency_score                # decay function of days since last_modified
  + 0.15 × source_priority_score        # Based on vault directory
  + 0.10 × prior_run_bonus              # Was this file useful in similar past runs?
)
```

**Deduplication:** Results are deduplicated by `file_path`. If the same file appears from multiple sources (tag filter, Whoosh, memory reference), it keeps the highest score.

**Output:**

```python
@dataclass
class SearchResult:
    file_path: str
    title: str
    score: float
    context: str | None
    tags: list[str]
    snippet: str | None
    token_count: int | None
    summary: str | None
    source: str           # "whoosh", "metadata", "memory", "prior_run"
```

The search returns an ordered list of `SearchResult` plus a separate list of `MemoryResult` and `PriorRunResult` objects. The Context Assembler decides how to fit them into the token budget.

---

## Whoosh Index Management

### Building the Index

The Whoosh index is built during the sync process (see [data.md — sync process](./data.md#how-the-indexer-stays-in-sync-with-the-dataset)). When a file is new or changed (detected by `content_hash`), it is added or updated in both the PostgreSQL `file_index` and the Whoosh index.

```
Sync process detects changed file
    │
    ▼
Parse frontmatter → extract title, tags, context
    │
    ▼
Update file_index row in PostgreSQL
    │
    ▼
Add/update document in Whoosh index
    │
    Writer = index.writer()
    Writer.update_document(
        path=relative_path,
        title=title,
        tags=",".join(tags),
        content=full_text_without_frontmatter,
        context=context,
        modified=last_modified,
    )
    Writer.commit()
```

**Incremental updates:** Only changed files are re-indexed. Whoosh's `update_document` method handles both inserts and updates — it looks up the document by the `path` field (marked as `unique=True`) and replaces it if it exists.

### Index Storage

The Whoosh index is stored on disk in a configurable directory:

```yaml
search:
  whoosh_index_path: "/home/user/.local/share/harle/whoosh_index"
```

Default location: `~/.local/share/harle/whoosh_index/` (follows XDG Base Directory spec). The index is **not stored in the vault** — it is derived data that can be rebuilt from the vault files at any time.

### Index Rebuild

If the index is corrupted or missing, it is rebuilt from scratch:

```
1. Delete the index directory
2. Walk the vault directory
3. Parse every .md file
4. Build the index from scratch
5. Time: ~1 second for 500 files, ~5 seconds for 5,000 files
```

Rebuild is triggered automatically on startup if the index directory does not exist, or manually via `harle index rebuild`.

---

## Chunking Strategy

For datasets where files exceed ~2,500 tokens, the search algorithm must chunk files into smaller pieces for accurate retrieval. The chunking strategy follows the research findings documented in [data_layer_best_practices.md](./data_layer_best_practices.md).

### When to Chunk

| File type | Typical size | Chunking approach |
|---|---|---|
| Prompts (`prompts/`) | 500–1,500 tokens | **No chunking** — always retrieved whole |
| Policies (`policies/`) | 300–1,000 tokens | **No chunking** — always retrieved whole |
| Workflows (`workflows/`) | 1,000–2,500 tokens | **Section-level** at H2 boundaries |
| Knowledge files < 2,000 tokens | < 2,000 tokens | **No chunking** — retrieved whole |
| Knowledge files > 2,000 tokens | 2,000–10,000 tokens | **Section-level** at H2 boundaries with cascading metadata |
| Logs / artifacts | Variable | **Paragraph-level** with contextual summary |

### Section-Level Chunking

Files are split at H2 (`##`) heading boundaries. Each chunk carries cascading metadata from the heading hierarchy:

```
Original file: knowledge/work/projects/harle.md

Chunk 1:
    path: knowledge/work/projects/harle.md#architecture
    cascading_context: "Harle Project > Architecture"
    content: [text under ## Architecture]

Chunk 2:
    path: knowledge/work/projects/harle.md#data-layer
    cascading_context: "Harle Project > Architecture > Data Layer"
    content: [text under ### Data Layer]
```

The cascading context is prepended to the chunk content in the Whoosh index so that search terms match against both the content and the structural context.

### Contextual Chunk Enrichment

Following Anthropic's Contextual Retrieval research, each chunk stored in the index includes a short auto-generated context summary:

```
[Source] knowledge/work/projects/harle.md > Architecture > Data Layer
[Tags] harle, architecture, data, postgres
[Context] work
[Summary] Describes the data layer design for the Harle project, including
PostgreSQL schema and the file-vs-database storage split.

[Content] The data layer uses a dual-storage approach: Markdown files serve as
the human-readable source of truth...
```

This reduces the "orphaned chunk" problem where a chunk is retrieved but meaningless without its surrounding context.

---

## Semantic Search with pgvector (Phase 3 — design notes)

### How It Will Work

When Phase 3 is implemented, the search pipeline gains a parallel semantic retrieval channel:

1. **At index time:** Each file (or chunk) is sent to an embedding API (e.g., OpenAI `text-embedding-3-small`) and the resulting 1536-dimensional vector is stored in the `embeddings` table via pgvector.

2. **At query time:** The user query is embedded using the same model, and pgvector finds the nearest neighbors using cosine similarity:

```sql
SELECT source_id, chunk_text,
       1 - (embedding <=> :query_embedding) AS similarity
FROM embeddings
WHERE source_type = 'file'
  AND source_id IN (SELECT id FROM file_index WHERE context = :context)
ORDER BY embedding <=> :query_embedding
LIMIT 20;
```

3. **Fusion:** Semantic results are merged with Whoosh BM25 results via Reciprocal Rank Fusion, producing a single ranked list.

### Why Whoosh Stays After pgvector

| Capability | Whoosh (BM25) | pgvector (semantic) |
|---|---|---|
| Exact term match | Excellent | Poor (may miss exact terms) |
| Conceptual similarity | Poor | Excellent |
| API cost per query | Free | ~$0.0001 (embedding API call) |
| Offline capability | Full | Requires embedding API |
| Speed | <10ms | <50ms (with HNSW index) |
| Setup complexity | Zero (pure Python) | Requires pgvector extension + embedding API |

The two methods are complementary — BM25 catches what embeddings miss (exact project names, file titles, rare terms), and embeddings catch what BM25 misses (conceptual similarity, paraphrases, cross-language concepts).

### Optional Reranking

After RRF fusion, an optional reranking step can re-score the top 20 results using a cross-encoder model or a cheap LLM call. Research shows this reduces retrieval failures by up to 67% (Anthropic) but adds ~200ms latency. Reranking is disabled by default and can be enabled in config:

```yaml
search:
  reranking:
    enabled: false
    method: "llm"           # "cross_encoder" or "llm"
    model: "gpt-4o-mini"    # Only for method: "llm"
    top_n: 20               # Rerank top N results
```

---

## Integration with the Context Assembler

The Search Algorithm returns results, but the **Context Assembler** (see [orchestrator.md](./orchestrator.md)) decides what reaches the agent. The interface between them is:

```python
@dataclass
class SearchResponse:
    file_results: list[SearchResult]     # Ranked file matches
    memory_results: list[MemoryResult]   # Relevant memories
    prior_runs: list[PriorRunResult]     # Similar past runs
    query_metadata: QueryMetadata        # Expansion details, timing

class QueryMetadata:
    original_query: str
    expanded_terms: list[str]
    tags_matched: list[str]
    candidates_count: int                # Files after pre-filter
    search_time_ms: float
    phase: str                           # "keyword", "whoosh", "hybrid"
```

The Context Assembler uses `token_count` from each result to fit files into the token budget. It also uses `summary` to make quick inclusion decisions without reading full file content.

**Context ordering (attention zones):** Based on "Lost in the Middle" research, the Context Assembler places the most relevant search results at the beginning and end of the context window, with lower-priority items in the middle. The search algorithm provides the ranking; the assembler provides the positioning.

---

## Configuration

Search configuration lives in `config.yaml` (external to the code repository):

```yaml
search:
  # Phase control
  engine: "keyword"                    # "keyword" (Phase 1), "whoosh" (Phase 2), "hybrid" (Phase 3)

  # Result limits
  max_results: 10                      # Max files returned per query
  min_score: 0.1                       # Minimum relevance score to include

  # Whoosh settings (Phase 2+)
  whoosh_index_path: "~/.local/share/harle/whoosh_index"
  title_boost: 2.0                     # Relevance multiplier for title matches
  tag_boost: 1.5                       # Relevance multiplier for tag matches

  # Ranking weights
  bm25_weight: 0.40                    # Weight for BM25 score in final ranking
  tag_match_weight: 0.20               # Weight for tag overlap
  recency_weight: 0.15                 # Weight for recency signal
  source_priority_weight: 0.15         # Weight for vault directory priority
  prior_run_weight: 0.10               # Weight for prior run usefulness

  # Memory lookup
  memory_min_confidence: 0.3           # Minimum confidence for memory inclusion
  max_memories: 10                     # Max memory entries returned
  max_prior_runs: 5                    # Max prior runs returned

  # Semantic search (Phase 3)
  semantic:
    enabled: false
    embedding_model: "text-embedding-3-small"
    semantic_weight: 0.30              # Weight in RRF (replaces part of bm25_weight)

  # Reranking (Phase 3)
  reranking:
    enabled: false
    method: "llm"
    model: "gpt-4o-mini"
    top_n: 20

  # Query expansion
  expansion:
    add_role_terms: true               # Add role-specific terms to query
    match_tag_vocabulary: true         # Match query against known tags
    use_stemming: true                 # Apply Porter stemming (Whoosh default)

  # Chunking
  chunking:
    enabled: false                     # Enable section-level chunking
    max_chunk_tokens: 2500             # Maximum tokens per chunk
    contextual_enrichment: true        # Prepend context summaries to chunks
    enrichment_model: "gpt-4o-mini"    # Model for generating context summaries
```

**Environment variable overrides:**

| Config key | Environment variable |
|---|---|
| `search.whoosh_index_path` | `HARLE_WHOOSH_INDEX_PATH` |
| `search.engine` | `HARLE_SEARCH_ENGINE` |

---

## Performance Characteristics

### Phase 1 (Simple Keyword Search — current)

| Metric | Value | Notes |
|---|---|---|
| Query time (50 files) | ~20ms | Reads all files from disk |
| Query time (500 files) | ~200ms | I/O-bound — degrades linearly |
| Memory usage | ~5 MB | Only file metadata in memory |
| Index build time | N/A | No index — scans on every query |

### Phase 2 (Whoosh — target)

| Metric | Value | Notes |
|---|---|---|
| Index build time | ~1s for 500 files | One-time on startup or sync |
| Incremental update | ~10ms per file | Only changed files re-indexed |
| Query time | <50ms | Full pipeline: expand → filter → search → rank |
| Index size on disk | ~5 MB for 500 files | Content not stored, only indexed |
| Memory usage | ~20 MB | Whoosh index + PostgreSQL connection pool |

### Phase 3 (Hybrid — future)

| Metric | Value | Notes |
|---|---|---|
| Query time (no rerank) | <100ms | Whoosh + pgvector in parallel |
| Query time (with rerank) | <300ms | Adds LLM call for top-20 reranking |
| Embedding cost per file | ~$0.0001 | One-time per file (or chunk) |
| Embedding cost per query | ~$0.0001 | One API call to embed the query |
| pgvector index size | ~50 MB for 5,000 chunks | HNSW index with 1536-dim vectors |

For a personal dataset (hundreds to low thousands of files), all phases complete well within acceptable latency. The bottleneck is always LLM inference, not search.

---

## Error Handling

| Error | What happens | User impact |
|---|---|---|
| **Whoosh index missing** | Rebuilt from scratch on startup. Logged as warning. | ~1s delay on first query after restart |
| **Whoosh index corrupted** | Detected by Whoosh on open. Deleted and rebuilt. | Same as missing — transparent rebuild |
| **PostgreSQL unreachable** | Search falls back to Whoosh-only mode (no metadata pre-filtering, no memories, no prior runs). | Slightly lower search quality. Warning in run log. |
| **Whoosh + PostgreSQL both down** | Search returns empty results. Context Assembler proceeds with P0 files only (prompts + policies loaded directly). | Agent works but without dataset context. Error message included in response. |
| **File referenced in index but missing from disk** | Skipped in results. `file_index` row marked for cleanup on next sync. | Transparent — that file just does not appear |
| **Embedding API unavailable (Phase 3)** | Semantic search channel returns empty. BM25 results still available via RRF. | Slight quality degradation for conceptual queries. Keyword search unaffected. |
| **Query produces zero results** | Returned as-is. Context Assembler includes a note in the agent context: "No matching documents found." | Agent response includes a note about missing context. Not an error — the dataset may simply not contain relevant information. |
| **Search timeout (>500ms)** | Query is cancelled. Partial results (if any) are returned. | Rare — only possible with very large datasets in Phase 3 with reranking enabled |

---

## Project Structure

```
harle/src/harle/search/             ← Search Algorithm code
│
├── __init__.py                     # Package docstring, public API re-exports
├── types.py                        # SearchQuery, SearchResult, SearchResponse,
│                                   #   MemoryResult, PriorRunResult, QueryMetadata
├── engine.py                       # Main search orchestration
│                                   #   Phase 1: simple keyword search (current)
│                                   #   Phase 2: coordinates expand → filter → search → rank
├── query_expander.py               # Query expansion: tokenize, role terms, tag matching
├── whoosh_index.py                 # Whoosh index build, update, query, rebuild
├── ranker.py                       # Multi-source ranking: RRF, score normalization
└── chunker.py                      # (future) Section-level chunking for long files
```

**Module responsibilities and dependencies:**

```
                    engine.py
                   (orchestrator)
                        │
        ┌───────────────┼───────────────┐
        │               │               │
        ▼               ▼               ▼
query_expander.py  whoosh_index.py  ranker.py
        │               │               │
        └───────────────┼───────────────┘
                        │
                        ▼
                    types.py
                   (data classes)
```

- `engine.py` is the only module called by the rest of the system (the Context Assembler). It coordinates all sub-modules.
- `types.py` defines the stable interface — callers depend only on `SearchQuery` and `SearchResult`.
- Sub-modules (`query_expander`, `whoosh_index`, `ranker`) are internal to the search package and can be replaced independently.

**Key dependencies:**

| Package | Purpose | Phase |
|---|---|---|
| `whoosh` | Full-text search index (build, update, query) | Phase 2+ |
| `sqlalchemy` + `asyncpg` | PostgreSQL access (metadata queries, memories, runs) | All phases |
| `tiktoken` | Token counting for budget-aware ranking | All phases |
| `openai` | Embedding API for pgvector (query embedding) | Phase 3 |

---

## How Search Improves Over Time (Without Code Changes)

The Search Algorithm benefits from improvements that are entirely data-driven:

| Improvement | How it happens | Effect on search |
|---|---|---|
| **Better tags** | User or Specialist agent adds more specific tags to files | More precise metadata pre-filtering; fewer irrelevant candidates |
| **Better titles** | Clearer, keyword-rich file titles | Title boost (2x) becomes more effective |
| **More workflow templates** | New templates added to `workflows/` | Better matches in Step 3; more relevant context for task-oriented queries |
| **Memories accumulate** | Preferences stored from corrections and clarifications | Step 5 returns richer personalization context |
| **Better file summaries** | Auto-generated summaries improve with re-indexing | Context Assembler makes better inclusion decisions |
| **Semantic search (Phase 3)** | pgvector embeddings added | Finds conceptually related documents that keyword search misses |
| **Prior run history grows** | More completed runs with `files_used` tracking | Step 5 learns which files are useful for which types of requests |

---

## Migration Path

### Phase 1 → Phase 2 (keyword → Whoosh)

1. Implement `whoosh_index.py` (build/update/query).
2. Implement `query_expander.py` (tokenize, role terms, tag vocabulary).
3. Implement `ranker.py` (RRF for BM25 + metadata signals).
4. Update `engine.py` to use the new pipeline instead of `_compute_score`.
5. Add `search.engine: "whoosh"` config option; keep `"keyword"` as fallback.
6. The `SearchQuery` and `SearchResult` types remain unchanged — callers are unaffected.

### Phase 2 → Phase 3 (Whoosh → hybrid)

1. Populate the `embeddings` table during sync (embedding API calls for new/changed files).
2. Add a pgvector query function in a new `semantic.py` module.
3. Update `ranker.py` to include semantic results in RRF.
4. Add optional reranking in `ranker.py`.
5. Add `search.engine: "hybrid"` config option.
6. Again, `SearchQuery` and `SearchResult` remain stable.

In both migrations, the public interface (`SearchEngine.search(query) → list[SearchResult]`) does not change. Only the internal implementation evolves.
