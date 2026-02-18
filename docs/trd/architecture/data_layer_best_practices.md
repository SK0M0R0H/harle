---
title: "Data Layer Best Practices for Harle"
tags: [data-layer, best-practices, retrieval, chunking, search, memory, metadata, research]
context: global
last_updated: 2026-02-19
summary: "Research-backed guide to structuring, storing, indexing, and retrieving personal knowledge so that LLM agents produce consistently relevant results."
---

# Data Layer Best Practices for Harle

## What We Know That Can Help Harle Be Actually Useful on Big Personal Datasets

> A research-backed guide to structuring, storing, indexing, and retrieving personal knowledge so that LLM agents produce consistently relevant results. Every recommendation below is grounded in published scientific work (2023–2025). References are collected in [Appendix A](#appendix-a-references).

This document is a companion to `architecture/data.md`. While `data.md` describes **what** the data layer looks like, this document answers **why** — what does the research literature say about making a personal AI assistant actually useful at scale?

---

## Table of Contents

1. [Core Problem Statement](#1-core-problem-statement)
2. [How to Structure Markdown Files](#2-how-to-structure-markdown-files)
3. [What Belongs in PostgreSQL vs. Files](#3-what-belongs-in-postgresql-vs-files)
4. [Context Assembly: What to Include and How](#4-context-assembly-what-to-include-and-how)
5. [Chunking Strategy](#5-chunking-strategy)
6. [Retrieval Strategy: Hybrid Search](#6-retrieval-strategy-hybrid-search)
7. [Memory Architecture](#7-memory-architecture)
8. [Metadata and Tagging](#8-metadata-and-tagging)
9. [Practical Limits and Failure Modes](#9-practical-limits-and-failure-modes)
10. [How Ambitious Can Personalized AI Get?](#10-how-ambitious-can-personalized-ai-get)
11. [Summary of Actionable Recommendations](#11-summary-of-actionable-recommendations)
12. [Appendix A: References](#appendix-a-references)

---

## 1. Core Problem Statement

Harle operates over a personal dataset that can grow to thousands of files — notes, rules, project docs, workflow templates, preferences, and logs. LLMs have a fixed context window (typically 128K tokens for frontier models, though effective use is much smaller). The fundamental problem is:

> **Given a user request, which 5–15 pages out of thousands should the agent see — and in what form — so that the response is maximally useful?**

This is not a search engine problem. Search finds *relevant* documents. Harle needs to find *the right context* — which includes documents, memories, policies, conversation history, and prior run results — assembled in a token-budgeted package where position and structure matter.

The research literature tells us several things that directly affect how Harle should design its data layer.

---

## 2. How to Structure Markdown Files

### 2.1 Heading Hierarchy Directly Affects Retrieval Quality

**Key finding:** HiQA (Hierarchical Contextual Augmentation RAG) demonstrates that integrating hierarchical structural information from documents — headings, sections, subsections — significantly improves both retrieval accuracy and token efficiency compared to flat chunking approaches [1]. The system uses a Markdown Formatter to preserve the heading hierarchy as "cascading metadata," creating a path like `Document Title > Section > Subsection` that travels with each chunk through the retrieval pipeline.

**Key finding:** MDEval [2] establishes that Markdown structure quality (heading hierarchy, list formatting, code block usage) is a measurable property that directly correlates with LLM output quality. Models that receive well-structured Markdown produce better-structured outputs.

**Recommendation for Harle vault files:**

```markdown
---
title: "Weekly Status Report Workflow"
tags: [workflow, status-report, weekly, work]
context: work
priority: P1
last_updated: 2026-02-10
---

# Weekly Status Report Workflow

Brief description of what this workflow does and when to use it.

## Prerequisites

- Access to Trello board "Work Q1"
- Last week's status report (for comparison)

## Steps

### Step 1: Gather Task Updates

Pull all cards moved to "Done" in the last 7 days...

### Step 2: Identify Blockers

Check "Blocked" column for cards older than 3 days...

## Output Format

The report should follow this structure:
- **Completed**: bullet list of finished items
- **In Progress**: bullet list with % estimate
- **Blocked**: bullet list with blocker description and owner
```

**Why this structure matters:**

| Structural element | Function in retrieval pipeline |
|---|---|
| **YAML frontmatter** | Pre-filters candidates before content search (tags, context, priority) [3] |
| **H1 title** | Gets 2x relevance boost in Whoosh; serves as the chunk's identity when building cascading metadata [1] |
| **H2 sections** | Natural chunk boundaries; each section can be independently retrieved and still make sense [4] |
| **H3 subsections** | Provide fine-grained retrieval for long documents; the cascading path `Workflow > Steps > Step 1` disambiguates chunks that share similar vocabulary [1] |
| **Bullet lists** | More token-efficient than prose; LLMs parse lists more reliably than paragraphs [2] |
| **Bold terms** | Act as implicit keywords; improve BM25 keyword matching when terms like `**Blocked**` appear |

### 2.2 File Length Sweet Spot

**Key finding:** Research on RAG chunking [4] identifies a "context cliff" — retrieval quality degrades beyond approximately 2,500 tokens per chunk. For whole-file retrieval (as Harle uses for prompts and policies), this suggests files should generally stay under 2,000–3,000 tokens (~1,500–2,200 words).

**Recommendation:**

| File type | Target length | Rationale |
|---|---|---|
| Prompts (`prompts/`) | 500–1,500 tokens | Loaded in full on every request (P0). Must fit budget. |
| Policies (`policies/`) | 300–1,000 tokens | Loaded in full on every request (P0). Keep atomic — one policy per file. |
| Workflows (`workflows/`) | 1,000–2,500 tokens | Loaded when matched (P1). Can be longer because sections are independently retrievable. |
| Knowledge (`knowledge/`) | 500–3,000 tokens | Retrieved by search (P1/P2). Long files should use clear H2 sections so chunks are self-contained. |
| Examples (`examples/`) | 300–800 tokens | Few-shot examples. Shorter is better — you want the model to see the pattern, not wade through prose. |

**For files that must be longer** (e.g., a 5,000-word project architecture doc): use clear H2 sections so the search algorithm can retrieve individual sections rather than the whole file. The heading hierarchy becomes the chunk boundary.

### 2.3 Writing Style That Helps Retrieval

Research on metadata-enriched RAG [3] and contextual retrieval [5] shows that the way content is written — not just structured — affects retrieval quality.

**Do:**

- **Start each file with a one-sentence summary.** This becomes the file's "abstract" for the search algorithm and for LLM-generated summaries. Example: *"This policy defines which external tools each agent role is permitted to invoke."*
- **Use specific terms, not pronouns.** Write "the Researcher agent" not "it" or "the agent." BM25 and embeddings both benefit from explicit terminology [5].
- **Include keywords naturally.** If a file is about travel planning for Japan, the words "Japan", "travel", "flights", "itinerary" should appear in the text — not just in tags.
- **Prefer structured formats** (bullet lists, tables, numbered steps) over long prose paragraphs. These are more token-efficient and easier for LLMs to extract information from.

**Don't:**

- Don't write overly generic summaries ("This document contains useful information about work").
- Don't rely on implicit context ("As discussed in the meeting" — which meeting? When?). Each file should be self-contained enough to be understood without reading other files.
- Don't duplicate content across files. Duplication pollutes retrieval results and wastes token budget. Use cross-references instead (`See: workflows/task-triage.md`).

---

## 3. What Belongs in PostgreSQL vs. Files

### 3.1 The Research Basis for Dual Storage

**Key finding:** PersonalAI [6] — a 2025 systematic comparison of knowledge storage approaches for personalized LLM agents — demonstrates that no single storage mechanism is optimal for all task types. Knowledge graphs excel at relational reasoning (e.g., "which agent handled tasks similar to this?"), while vector/content stores excel at semantic similarity (e.g., "find files related to data privacy"). The paper recommends **hybrid architectures** that combine structured and unstructured storage.

**Key finding:** HetaRAG [7] shows that orchestrating heterogeneous data stores — vector indices, knowledge graphs, full-text engines, and structured databases — into a unified retrieval plane improves both recall and precision compared to any single-store approach.

### 3.2 Decision Framework

| Data characteristic | Store in **files** (Markdown vault) | Store in **PostgreSQL** | Store in **both** |
|---|---|---|---|
| **Human-editable** | Yes — this is the primary authoring surface | No | — |
| **Requires structured queries** (filtering, aggregation, joins) | No | Yes | — |
| **Source of truth for user knowledge** | Yes | No (mirror only) | Metadata in DB, content in files |
| **Machine-generated** (run logs, cost tracking, embeddings) | Summary only (in `logs/`) | Full structured data | Summary in file, structured in DB |
| **Needs to survive DB rebuild** | Yes — files are the recovery source | No — DB can be rebuilt from files | — |
| **Relationships between entities** | Unstructured only (wiki-style `[[links]]` form a graph, but no enforced schema) | Yes (foreign keys, joins, enforced referential integrity) | — |
| **Requires real-time querying** | No (file system scan is slow) | Yes (indexed queries are fast) | — |

### 3.3 Concrete Split for Harle

**Only in files (source of truth, human-authored):**
- Agent prompts, policies, workflow templates
- Personal knowledge base (notes, project docs, preferences)
- Few-shot examples

**Only in PostgreSQL (machine-generated, structured):**
- `runs` — execution history with cost/token/tool tracking
- `conversations` / `messages` — multi-turn chat state
- `embeddings` — vector representations for semantic search
- Computed metadata (token counts, content hashes, auto-generated summaries)

**In both (file is source of truth, DB mirrors for queryability):**
- `file_index` — metadata from frontmatter + computed fields. If the DB is lost, rebuild from files. If a file is deleted, remove the DB row.
- `memories` — could live as files in a `memories/` directory *or* as DB rows. Research [6, 8] suggests that for memories that evolve frequently (confidence scores update, new connections form), a database is more practical. But for auditability, memories should be exportable to Markdown.
- `artifacts` — agent outputs. Stored in DB for querying, but also saved as files in `logs/` for human review and version control.

### 3.4 Why Not Just a Database?

PersonalAI [6] and Knoll [9] both find that user engagement and data quality are higher when users can directly edit their knowledge base in familiar formats. A PostgreSQL row is not a natural editing surface. The "files-first, DB-mirrors" architecture preserves human agency — which is critical for a *personal* assistant where the user must trust and control the data.

---

## 4. Context Assembly: What to Include and How

### 4.1 The "Lost in the Middle" Problem

**Key finding:** Liu et al. [10] demonstrate that LLMs exhibit a U-shaped attention pattern — they attend strongly to information at the beginning and end of the context window but significantly underperform on information placed in the middle. This was validated across models including GPT-3.5-Turbo, GPT-4, and Claude, and published in *Transactions of the Association for Computational Linguistics* (2024). Performance can degrade by 10+ percentage points depending on position.

**Key finding:** A follow-up paper [11] identifies the root cause as an intrinsic positional attention bias and proposes a calibration mechanism that improves RAG performance by up to 10 percentage points.

**Implication for Harle's Context Assembler:** The order in which context is packed into the prompt matters as much as *what* is included. High-priority content should go at the beginning and end, not in the middle.

### 4.2 Recommended Context Assembly Order

Based on the "Lost in the Middle" findings [10, 11] and token-budget research [12], Harle's Context Assembler should pack context in this order:

```
┌─────────────────────────────────────────────────────────┐
│  BEGINNING OF CONTEXT (high attention zone)              │
│                                                          │
│  1. System prompt + agent role definition (from prompts/)│
│     → Always included. Defines agent identity.           │
│                                                          │
│  2. Active policies (from policies/)                     │
│     → Always included. Defines constraints.              │
│                                                          │
│  3. Most relevant search results (top 3-5 files)         │
│     → Ranked by search algorithm. These are the          │
│       files most likely to contain the answer.           │
│                                                          │
├─────────────────────────────────────────────────────────┤
│  MIDDLE OF CONTEXT (lower attention zone)                │
│                                                          │
│  4. Supporting search results (files 6-10)               │
│     → Less critical but potentially useful.              │
│                                                          │
│  5. Prior run results (if similar request was handled)   │
│     → Historical context. Useful but not critical.       │
│                                                          │
│  6. Relevant memories (preferences, past decisions)      │
│     → Can be compressed into a short list.               │
│                                                          │
├─────────────────────────────────────────────────────────┤
│  END OF CONTEXT (high attention zone)                    │
│                                                          │
│  7. Conversation history (recent turns)                  │
│     → Most recent first. Critical for continuity.        │
│                                                          │
│  8. The user's current request                           │
│     → Always last. This is what the model attends to     │
│       most strongly.                                     │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### 4.3 Token Budget Allocation

**Key finding:** Token-Budget-Aware LLM Reasoning [12] shows that explicitly constraining the token budget in prompts can reduce cost without degrading quality, because LLMs often produce unnecessarily verbose reasoning when unconstrained.

**Recommended budget split for a 128K-token model (practical limit ~30K usable tokens):**

| Context slot | Budget % | ~Tokens | Rationale |
|---|---|---|---|
| System prompt + role | 5–8% | 1,500–2,400 | Fixed cost. Keep prompts concise. |
| Policies | 3–5% | 900–1,500 | One-file-per-policy keeps this bounded. |
| Top search results (3-5 files) | 25–35% | 7,500–10,500 | The core knowledge for this request. |
| Supporting results (5-10) | 10–15% | 3,000–4,500 | Diminishing returns beyond top 5 [4]. |
| Memories + prior runs | 5–8% | 1,500–2,400 | Compressed summaries, not full content. |
| Conversation history | 10–15% | 3,000–4,500 | Recent turns in full, older ones summarized [8]. |
| **Reserved for model output** | **20–30%** | **6,000–9,000** | **The model needs room to generate.** |

**Why ~30K usable out of 128K?** While frontier models accept 128K tokens, research shows diminishing returns and degraded attention beyond much smaller effective windows [10]. Additionally, the "context cliff" [4] means retrieval quality peaks at smaller context sizes. For a personal assistant, 25–35K of carefully selected context outperforms 100K of everything-and-the-kitchen-sink.

### 4.4 Context Relevance Scoring

**Key finding:** Multi-Meta-RAG [3] demonstrates that using LLM-extracted metadata to pre-filter documents before semantic search significantly improves multi-hop query performance. This is directly applicable to Harle's two-phase search (metadata pre-filter in PostgreSQL → content search in Whoosh/pgvector).

The Context Assembler should score each candidate piece of context:

```
Relevance Score = (
    0.35 × search_relevance      # From Whoosh/pgvector
  + 0.20 × metadata_match        # Tag overlap, context scope match
  + 0.15 × recency               # Newer files score higher
  + 0.15 × source_priority       # Prompts > Policies > Workflows > Knowledge > Logs
  + 0.10 × memory_confidence     # For memory entries
  + 0.05 × prior_run_success     # Was this file useful in similar past requests?
)
```

---

## 5. Chunking Strategy

### 5.1 When and How to Chunk

**Key finding:** A comprehensive 2025 study [4] systematically evaluated chunking strategies and found:

- **Sentence-level chunking** is the most cost-effective approach, matching semantic chunking performance for contexts up to ~5K tokens.
- **Chunk overlap provides no measurable benefit** while increasing indexing costs. Avoid it.
- A **"context cliff"** reduces quality beyond ~2,500 tokens per chunk — the retriever returns less relevant results when chunks are too large.
- **Semantic chunking** (merging adjacent sentences based on cosine similarity >0.5) preserves coherence but adds computational cost with marginal gains over sentence chunking for typical personal-knowledge documents.

**Key finding:** Anthropic's Contextual Retrieval [5] demonstrates that prepending a short context summary (generated by the LLM) to each chunk before embedding reduces retrieval failures by 49%, and by 67% when combined with reranking. This is because isolated chunks lose the context of the surrounding document.

### 5.2 Recommendation for Harle

For the Harle vault, files are predominantly short (500–3,000 tokens). The chunking strategy should differ by file type:

| File type | Chunking approach | Rationale |
|---|---|---|
| Prompts, policies, examples | **No chunking** — retrieve whole file | These are short and must be used in full. Chunking would break their coherence. |
| Workflows | **Section-level** — chunk at H2 boundaries | Steps are independently meaningful. A search for "identify blockers" should return just that section. |
| Knowledge files (<2K tokens) | **No chunking** — retrieve whole file | Below the context cliff. Chunking adds overhead without benefit. |
| Knowledge files (>2K tokens) | **Section-level** at H2 boundaries, with cascading metadata | Prepend the heading path (`Project Harle > Architecture > Data Layer`) to each chunk per HiQA [1]. |
| Logs / artifacts | **Paragraph-level** with contextual summary | These can be long. Prepend a one-line summary per Anthropic's approach [5]. |

### 5.3 Contextual Chunk Enrichment

Following Anthropic's Contextual Retrieval [5], each chunk stored in the search index should include:

```
[Chunk metadata]
Source: knowledge/work/projects/harle.md
Section: Architecture > Data Layer
Tags: harle, architecture, data, postgres
Context: work

[Contextual summary — auto-generated]
This chunk describes the data layer architecture of the Harle project,
including PostgreSQL schema design and file-based storage decisions.

[Original chunk content]
The data layer uses a dual-storage approach: Markdown files serve as
the human-readable source of truth, while PostgreSQL mirrors metadata
and provides structured querying capabilities...
```

This contextual enrichment reduces the "orphaned chunk" problem where a chunk like "The system uses HNSW indexing" is meaningless without knowing which system is being discussed.

---

## 6. Retrieval Strategy: Hybrid Search

### 6.1 Why Hybrid Search Is Not Optional

**Key finding:** Blended RAG [13] demonstrates that combining dense retrieval (vector similarity) with sparse retrieval (BM25/keyword) consistently outperforms either approach alone across NQ, TREC-COVID, and SQuAD benchmarks.

**Key finding:** Mixture-of-Retrievers (MoR) [14] shows that dynamically selecting retrievers per query achieves +10.8% improvement over individual retrievers. Different queries benefit from different retrieval strategies — a personal assistant must handle both "find documents about privacy" (semantic) and "find the file called task-triage.md" (keyword/exact).

**Key finding:** Research on sparse vs. dense retrieval [14, 15] shows that BM25 remains competitive with — and sometimes outperforms — dense retrieval in specialized domains and for rare entities. For a personal vault with project-specific terminology, BM25 catches the terms that embeddings miss.

### 6.2 Recommended Retrieval Pipeline for Harle

**How metadata pre-filter is derived from the request.** Before the pipeline starts, the system must translate a raw user request into a set of filter criteria for Phase 1. This happens in a lightweight extraction step:

1. **Context scope** is determined by the active session: each Harle session is bound to a scope (e.g. `work`, `personal`, a specific project), so the scope filter is implicit — no NLP needed.
2. **Tag matching** uses a two-pronged approach: (a) exact keyword matching against a known tag vocabulary (e.g. request contains "privacy" → tag `#privacy`), and (b) optionally, a fast LLM classification call that maps the request to one or more predefined categories. The tag vocabulary is maintained in the vault metadata and indexed in PostgreSQL.
3. **Priority inclusion** is unconditional — P0 (critical/always-relevant) files are always injected into the candidate set regardless of the request content. This ensures core policies, user preferences, and active project context are never missed.

The result of this extraction is a PostgreSQL `WHERE` clause that narrows the full file set down to a candidate set (typically 30–100 files), which is then passed into the parallel retrieval phase.

```
User request
    │
    ▼
Phase 1: METADATA PRE-FILTER (PostgreSQL)
    → Filter by context scope (work/personal)
    → Filter by tags if request matches known categories
    → Filter by priority (always include P0 files)
    → Result: candidate set (typically 30–100 files from 500+)
    │
    ▼
Phase 2: PARALLEL RETRIEVAL
    ┌─────────────────┬──────────────────┐
    │                 │                  │
    ▼                 ▼                  ▼
 BM25/Whoosh      pgvector          Metadata
 (keyword)        (semantic)        (tag match,
    │                │               recency)
    │                │                  │
    └─────────────────┴──────────────────┘
                     │
                     ▼
Phase 3: RECIPROCAL RANK FUSION
    → Combine rankings from all retrievers
    → Each result gets: 1/(k + rank_in_retriever)
    → Sum across retrievers
    → Top-N results by combined score
    │
    ▼
Phase 4: RERANKING (optional, adds latency)
    → Use a cross-encoder or LLM to re-score top-20
    → Anthropic reports 67% failure reduction with reranking [5]
    → Only justified if latency budget allows (~200ms extra)
    │
    ▼
Phase 5: TOKEN BUDGET FITTING
    → Load file content for top results
    → Fit into token budget using priority order
    → Truncate or summarize lowest-priority items to fit
```

### 6.3 When Each Retriever Wins

| Query type | Best retriever | Example |
|---|---|---|
| Exact term lookup | BM25 | "Find the task-triage workflow" |
| Conceptual similarity | pgvector | "How should we handle data protection?" |
| Category browsing | Metadata filter | "Show me all privacy policies" |
| Multi-hop reasoning | Hybrid + reranking | "Based on our L2 architecture, what privacy solutions fit?" |
| Personal preference recall | Memory lookup (PostgreSQL) | "What format does the user prefer for reports?" |

---

## 7. Memory Architecture

### 7.1 Research on LLM Memory Systems

Three recent papers define the state of the art for LLM agent memory:

**A-MEM (Agentic Memory)** [8] proposes a Zettelkasten-inspired memory system where each memory is a structured note with contextual description, keywords, tags, and connections to other memories. Crucially, new memories can trigger updates to existing memories — a process called "memory evolution." This prevents the memory store from becoming a flat, ever-growing list.

**Reflective Memory Management (RMM)** [16] introduces two key mechanisms:
- **Prospective reflection:** Dynamically summarizing interactions at different granularities (utterance, turn, session) to create multi-resolution memory.
- **Retrospective reflection:** Using reinforcement learning to refine retrieval — learning which memories are actually useful when recalled. This achieved 10%+ accuracy improvement over baselines.

**MemGPT** [17] applies operating system memory management principles to LLMs, introducing a tiered memory hierarchy:
- **Main context** (in the LLM's context window) — equivalent to RAM.
- **Archival memory** (in external storage) — equivalent to disk.
- **Working memory** (editable by the agent) — a scratchpad for the current task.

The agent can read from and write to its own memory using tool calls, creating a self-managing memory system.

### 7.2 Recommendation for Harle's Memory System

Based on these papers, Harle should implement a **three-tier memory architecture:**

```
Tier 1: WORKING MEMORY (in-context, ephemeral)
    → Current conversation history
    → Current task state
    → Relevant memories retrieved for this request
    → Dies when the conversation ends
    │
Tier 2: EPISODIC MEMORY (PostgreSQL `memories` + `runs`)
    → Learned preferences ("user prefers bullet points")
    → Past decisions ("chose Japan Airlines for flexibility")
    → Corrections ("don't include budget in external reports")
    → Run history summaries
    → Persists across conversations
    → Has confidence scores that evolve [8]
    │
Tier 3: SEMANTIC MEMORY (Markdown vault + embeddings)
    → The user's knowledge base
    → Agent prompts and policies
    → Workflow templates and examples
    → Persists indefinitely, human-editable
    → Indexed for search
```

**Key design principles from the literature:**

1. **Memories should have connections to each other** [8]. This follows directly from A-MEM's Zettelkasten-inspired model, where each memory is not an isolated record but a node in a graph — linked to related memories via explicit connections. A-MEM's "memory evolution" mechanism means that storing a new memory triggers a search for related existing memories and may update or merge them. For Harle, this means a preference "user likes bullet points" should be linked to the correction "but use numbered lists for step-by-step instructions." This prevents contradictory memories from being applied simultaneously.

2. **Memories should have confidence scores that update** [8, 16]. Two papers converge on this idea from different angles. A-MEM's memory evolution provides the mechanism: when a memory is reinforced by new evidence it strengthens, when contradicted it gets revised. RMM's *retrospective reflection* provides the signal: by tracking which retrieved memories actually led to successful outcomes (via RL), the system learns which memories deserve higher confidence. For Harle, a new memory starts at low confidence. Each time it's used and the user doesn't correct the agent, confidence increases. If the user corrects the agent, confidence decreases or the memory is updated.

3. **Old conversation history should be summarized, not truncated** [16, 17]. RMM's *prospective reflection* directly addresses this: it dynamically summarizes interactions at multiple granularities (utterance → turn → session), creating multi-resolution memory that preserves key information while staying within token limits. MemGPT complements this with its tiered architecture: recent turns stay in main context (RAM), older turns are evicted to archival memory (disk) and replaced with compressed summaries — the agent can page them back in when needed. Together, they show that multi-resolution summarization (keep recent turns verbatim, summarize older turns, create a one-line session summary for very old sessions) outperforms both full-context and simple-truncation approaches.

4. **The agent should be able to write to its own memory** [17]. This is MemGPT's central contribution: treating memory management as a set of tool calls (`core_memory_append`, `archival_memory_insert`, etc.) that the agent invokes autonomously, just as an OS manages its own page table. Rather than relying on an external system to decide what to store, the agent itself decides when something is worth remembering. For Harle, this means agents should have a `save_memory` tool that creates entries in the `memories` table. This is not automatic — the agent decides when something is worth remembering.

---

## 8. Metadata and Tagging

### 8.1 Why Metadata Is a Force Multiplier

**Key finding:** Research on metadata-enriched RAG [3] shows that metadata-enriched approaches achieve 82.5% precision compared to 73.3% for content-only semantic search — a 12.5% relative improvement from simply adding structured metadata to chunks.

**Key finding:** Multi-Meta-RAG [3] demonstrates that LLM-extracted metadata with database filtering significantly improves performance on multi-hop queries — the kind Harle handles routinely (e.g., "Based on our architecture decisions, what privacy approach fits our L2?").

### 8.2 Required Frontmatter Fields

Based on the research, every Markdown file in the Harle vault should include these frontmatter fields:

```yaml
---
# REQUIRED
title: "Descriptive title with key terms"  # Used for title-boost in search [1]
tags: [specific, relevant, tags]            # Used for metadata pre-filtering [3]
context: work | personal | global           # Scope isolation

# RECOMMENDED
priority: P0 | P1 | P2 | P3                # Context assembly priority
last_updated: 2026-02-10                    # Recency ranking signal
summary: "One-sentence description"         # Used if auto-summary fails

# OPTIONAL (auto-generated by indexer)
token_count: 1250                           # Estimated token count
content_hash: "sha256:..."                  # Change detection
---
```

### 8.3 Tagging Conventions

Tags are the primary mechanism for metadata pre-filtering [3]. Consistency matters more than exhaustiveness:

**Tag categories:**

| Category | Examples | Purpose |
|---|---|---|
| **Domain** | `privacy`, `architecture`, `travel`, `health` | Topic filtering |
| **Role** | `researcher`, `secretary`, `specialist` | Agent-specific retrieval |
| **Action** | `workflow`, `policy`, `prompt`, `example` | File-type filtering |
| **Project** | `harle`, `l2-chain`, `product-x` | Project-scoped queries |
| **Status** | `active`, `archived`, `draft` | Currency filtering |

**Rules:**

1. Use lowercase, hyphenated multi-word tags (`status-report`, not `StatusReport`).
2. Aim for 3–7 tags per file. Fewer is too sparse for filtering; more dilutes precision.
3. At least one domain tag and one action tag per file.
4. Project tags should be consistent — decide on `harle` vs. `project-harle` and stick with it.

### 8.4 Auto-Generated Metadata

The indexer should auto-generate metadata that humans shouldn't maintain manually:

| Field | Generation method | Cost |
|---|---|---|
| `token_count` | `tiktoken` estimation | Free, instant |
| `content_hash` | SHA-256 of file content | Free, instant |
| `summary` | LLM-generated (GPT-4o-mini) | ~$0.001/file |
| `key_entities` | LLM-extracted entities and terms | ~$0.001/file |
| `questions_answered` | LLM-generated: "What questions does this file answer?" | ~$0.001/file |

The `questions_answered` field is particularly powerful — it was introduced by LlamaIndex [18] and directly improves retrieval because user queries are often phrased as questions, and matching "question ↔ question" has higher semantic overlap than "question ↔ declarative content."

---

## 9. Practical Limits and Failure Modes

### 9.1 Known Failure Modes from Research

| Failure mode | Research source | Mitigation |
|---|---|---|
| **Lost in the middle** — model ignores information in the middle of context | Liu et al. [10] | Place highest-priority content at beginning and end of context |
| **Context cliff** — retrieval quality drops beyond ~2.5K token chunks | RAG chunking study [4] | Keep chunks under 2,500 tokens; use section-level chunking for long files |
| **Vocabulary mismatch** — keyword search misses semantically relevant docs | Blended RAG [13] | Use hybrid search (BM25 + pgvector); never rely on keyword-only |
| **Orphaned chunks** — chunks lose meaning without surrounding context | Anthropic [5] | Prepend contextual summaries and heading paths to each chunk |
| **Memory staleness** — outdated preferences applied to new situations | A-MEM [8] | Confidence decay over time; memory evolution when new info contradicts old |
| **Over-retrieval** — too many documents dilute the signal | Token budget research [12] | Hard token budget with priority-based truncation; 5–10 files is usually optimal |
| **Duplicate retrieval** — same information from multiple sources wastes budget | HiQA [1] | Deduplication by content hash; prefer the most specific source |

### 9.2 Dataset Scale Considerations

For a personal dataset, Harle will typically handle:

| Scale | File count | Index size | Search latency | Notes |
|---|---|---|---|---|
| **Small** | <100 files | <1 MB | <10ms | Full-text search alone is sufficient |
| **Medium** | 100–1,000 files | 1–10 MB | <50ms | Metadata pre-filtering becomes valuable |
| **Large** | 1,000–10,000 files | 10–100 MB | <100ms | Semantic search (pgvector) becomes necessary |
| **Very large** | 10,000+ files | 100+ MB | <200ms | Need chunking, reranking, and aggressive budget management |

pgvector benchmarks [19] show that PostgreSQL with HNSW indexing handles millions of vectors with sub-100ms latency, which is far beyond what a personal dataset needs. The bottleneck will be context assembly and LLM inference, not search.

---

## 10. How Ambitious Can Personalized AI Get?

> Can Harle become an actual extension of your digitalized memory — a "second brain" that knows everything you know — or is there a hard ceiling where context management breaks down?

This section examines what the research says about the upper bound of ambition for personal AI systems, and where the realistic frontier lies today and in the near term.

### 10.1 The Scale of a Human Life in Tokens

To understand whether "total digital memory" is feasible, we need to quantify it:

| Data source | Estimated volume per year | Tokens per year | Over 10 years |
|---|---|---|---|
| **Email** (sent + received) | ~42,000 words sent [R1]; ~200K words received | ~320K tokens | ~3.2M tokens |
| **Work documents** (reports, specs, notes) | ~100K–500K words | ~130K–650K tokens | ~1.3M–6.5M tokens |
| **Personal notes** (journal, ideas, todo) | ~20K–100K words | ~26K–130K tokens | ~260K–1.3M tokens |
| **Chat messages** (Slack, Telegram, etc.) | ~50K–200K words | ~65K–260K tokens | ~650K–2.6M tokens |
| **Bookmarks, clippings, highlights** | ~30K–100K words | ~39K–130K tokens | ~390K–1.3M tokens |
| **Code** (personal projects) | ~50K–500K words | ~65K–650K tokens | ~650K–6.5M tokens |

**Total estimate: a decade of one person's digital text life is roughly 5–20 million tokens.**

This is a critical number. It tells us that the *entire text output of your digital life* over 10 years fits within a range that is technically addressable — but not by stuffing it into a context window.

### 10.2 The Context Window Is Not the Answer

A natural first instinct: "Gemini has 1M–10M token context. Just load everything." Research says this fails for three reasons:

**Reason 1: Performance degrades with context length.** Despite Gemini 1.5 Pro accepting 1M+ tokens and achieving near-perfect retrieval on synthetic needle-in-a-haystack tests [21], real-world evaluations show significant performance degradation on analytical tasks (sentiment analysis, categorization, reasoning) with long inputs — across all tested models including Claude 3, Gemini Pro, GPT-3.5 Turbo, Llama 3, and Mistral [22]. The "Lost in the Middle" effect [10] gets worse, not better, with more context. A large context window is a necessary capability but not a sufficient solution.

**Reason 2: Cost and latency scale linearly (or worse) with context.** Processing 1M tokens per request is ~50–100x more expensive than processing 20K tokens. For a personal assistant making dozens of requests per day, this is financially unsustainable for most users.

**Reason 3: Most of your data is irrelevant to any given question.** When you ask "What did we decide about the L2 privacy architecture?", you need 3–5 specific files, not 10 years of emails. Loading everything introduces noise that actively degrades response quality [4, 10, 22].

**The research consensus:** RAG (selective retrieval) outperforms or matches long-context on most practical tasks while being 10–100x cheaper [23]. A hybrid approach — RAG for selection, long context for the selected material — is optimal [23].

### 10.3 What *Is* Feasible: The Three Horizons

Based on the current literature, here is what personalized AI can realistically achieve at different ambition levels:

#### Horizon 1: Structured Personal Knowledge Base (feasible now)

**What it is:** A curated vault of 500–5,000 Markdown files (prompts, policies, project notes, workflows, preferences) with hybrid search, metadata filtering, and a memory system.

**Why it works:** This is the operating range where all the techniques in this document are well-validated. Whoosh + pgvector handles this scale trivially. The context assembler can select 5–15 relevant files per request. The user actively curates content — quality is high because it's intentional.

**Research support:** Knoll [9] deployed exactly this model with 200+ real users and demonstrated improved response quality. PersonaMem-v2 [24] achieves effective personalization with structured memory systems at this scale, reducing token usage by 16x compared to raw context stuffing.

**Scale:** ~500K–5M tokens total. Well within retrieval system capabilities.

**What Harle gets from this:** An assistant that knows your projects, respects your rules, follows your preferred formats, remembers your past decisions, and improves over time. This is already dramatically more useful than a generic chatbot.

#### Horizon 2: Augmented Digital Memory (feasible 2025–2027)

**What it is:** Beyond curated notes — ingesting email archives, Slack exports, browser bookmarks, read-later articles, code repositories, and calendar data. The system becomes a queryable mirror of your digital activity.

**Why it's harder:** The data volume jumps to 5M–50M tokens. Content is noisy (most emails are irrelevant). Temporal reasoning becomes critical ("What did I discuss with Alex *last March*?"). Privacy boundaries become complex (work Slack vs. personal Telegram).

**Research support:** OmniQuery [25] demonstrates that augmenting captured memories with contextual information enables answering complex personal questions across interconnected data sources, achieving 71.5% accuracy and outperforming conventional retrieval in 74.5% of evaluations. Memoria [26] presents a hybrid architecture (session summarization + weighted knowledge graphs) achieving 87.1% accuracy while reducing latency by 38.7%, showing that structured compression makes this scale tractable.

**Key enablers needed:**
- **Automatic ingestion pipelines** — parsing email, Slack, bookmarks into indexed Markdown.
- **Time-aware retrieval** — temporal knowledge graphs that model "when" in addition to "what" [27].
- **Aggressive summarization** — most ingested data should be compressed to summaries with the original accessible on demand.
- **Privacy-aware scoping** — not just work/personal, but per-source access controls.

**Scale:** ~5M–50M tokens total. Feasible with chunking, summarization, and tiered storage, but retrieval quality becomes the bottleneck.

**What Harle gets from this:** An assistant that can answer "What was the name of that restaurant in Osaka that someone recommended on Slack?" or "Summarize all architecture decisions we made this quarter across Trello, docs, and email threads."

#### Horizon 3: Cognitive Digital Twin (research frontier, 2027+)

**What it is:** An AI that doesn't just retrieve your data but models *you* — your reasoning patterns, communication style, decision-making heuristics, and knowledge gaps. It could draft emails in your voice, predict what questions you'd ask about a proposal, or notice that your current project contradicts a decision you made two years ago.

**Why it's currently out of reach:** This requires not just retrieval but *deep personalization* — training or fine-tuning models on your behavioral patterns. Current research shows that even frontier LLMs achieve only 37–48% accuracy on implicit personalization tasks despite 128K-token context windows [24]. Reasoning about a person's implicit preferences is fundamentally harder than retrieving their explicit statements.

**Research support:** Brain Cache [28] proposes AI as a "cognitive exoskeleton" — externalizing biological memory into semantic networks and activating it through contextual recommendations. PersonalAI [6] shows that different storage and retrieval architectures are optimal for different cognitive tasks. The Self-Adaptive Long-term Memory (SALM) survey [29] maps human memory types (episodic, semantic, procedural) to AI architectures and proposes that next-generation systems will need all three.

**What's missing:**
- **Implicit preference learning** — current systems are good at "user said they prefer bullets" but bad at "user consistently chooses pragmatic solutions over theoretically optimal ones." PersonaMem-v2 achieves 55% on these tasks with reinforcement fine-tuning [24] — promising but not production-ready.
- **Causal and temporal reasoning** — "You chose approach A because of constraint X, but X has changed" requires causal models over your decision history, not just retrieval.
- **Contradiction detection** — across thousands of documents written over years, preferences evolve and decisions conflict. No current system handles this robustly.
- **Acceptable latency** — modeling you in real-time during a conversation requires sub-second inference over your entire knowledge graph, which is not yet practical.

### 10.4 The Honest Assessment

```
┌───────────────────────────────────────────────────────────────┐
│                                                               │
│    Can Harle be an extension of your digital memory?          │
│                                                               │
│    YES — for structured, curated knowledge (Horizon 1).       │
│    This is achievable today with the techniques in this       │
│    document. It's not "everything you've ever known" but      │
│    it's "everything you've deliberately organized" — and      │
│    that's already transformative.                             │
│                                                               │
│    PARTIALLY — for broader digital activity (Horizon 2).      │
│    Ingesting email/Slack/bookmarks is an engineering          │
│    problem with known solutions, but retrieval quality        │
│    degrades as noise increases. The 80/20 rule applies:       │
│    80% of the value comes from 20% of the data.              │
│                                                               │
│    NOT YET — for true cognitive modeling (Horizon 3).         │
│    The research is promising (PersonaMem-v2, Brain Cache,     │
│    SALM) but accuracy on implicit personalization is          │
│    37–55%, which is not reliable enough for production.       │
│                                                               │
│    The bottleneck is NOT storage or retrieval — it's          │
│    reasoning. We can store and find everything. We cannot     │
│    yet make an AI that *understands* your patterns the        │
│    way a long-time colleague does.                            │
│                                                               │
└───────────────────────────────────────────────────────────────┘
```

### 10.5 What This Means for Harle's Architecture

The architecture described in this document and in `architecture/data.md` is designed for **Horizon 1 with a clear path to Horizon 2:**

| Architectural choice | Horizon 1 | Horizon 2 readiness |
|---|---|---|
| Markdown vault as source of truth | Core use case | Ingestion pipelines write to the vault |
| PostgreSQL + pgvector | Metadata + future semantic search | Scales to millions of embeddings [19] |
| Hybrid search (BM25 + semantic) | Optimal for curated content [13] | Required for noisy, large-scale data |
| Three-tier memory (working/episodic/semantic) | Preferences and decisions | Behavioral pattern modeling |
| Token-budgeted context assembly | 5–15 files per request | Same principle, harder selection problem |
| Priority-based context ordering | P0/P1/P2 files | Per-source priority and trust levels |

**The key insight:** Harle does not need to solve Horizon 3 to be transformative. A system that reliably knows your 500 most important files, remembers your preferences, and improves over time is already something that does not exist in a production-grade, self-hosted form. That's the target.

Horizon 2 (ingesting broader digital activity) is an incremental extension — adding ingestion pipelines, temporal reasoning, and privacy scoping — not an architectural rewrite. The foundation designed for Horizon 1 supports it.

Horizon 3 (cognitive modeling) would require deeper changes — personalized fine-tuning, causal reasoning modules, and possibly custom model training. But by the time Harle reaches that ambition level, the research will have matured. The current architecture won't block it.

### 10.6 The Pragmatic Path

> "The best time to plant a tree was twenty years ago. The second best time is now."

For Harle, the pragmatic path is:

1. **Now:** Build Horizon 1 exceptionally well. A perfectly curated 1,000-file vault with excellent search, memory, and context assembly will outperform a sloppy 100,000-file ingestion system.

2. **Next:** Add ingestion pipelines for the highest-value external sources (email summaries, Trello syncs, bookmark highlights). Each source gets its own quality filter — don't index noise.

3. **Later:** When the research matures and Harle has enough user interaction history, explore Horizon 3 capabilities — behavioral modeling, implicit preference learning, proactive suggestions.

The data layer architecture in this document supports all three stages. The investment in structured Markdown, metadata, hybrid search, and tiered memory is not throwaway work for Horizon 1 — it's the foundation that Horizons 2 and 3 build on.

---

## 11. Summary of Actionable Recommendations

### For File Authoring (vault contributors — user and agents)

1. **Use consistent heading hierarchy** (H1 → H2 → H3). Never skip levels. Headings are chunk boundaries and cascading metadata sources [1].
2. **Start every file with a one-sentence summary** below the H1. This is the file's "abstract" for search and summarization.
3. **Keep files under 3,000 tokens** when possible. Split longer content into multiple files or use clear H2 sections.
4. **Include YAML frontmatter** with at least `title`, `tags`, and `context`. This is the single highest-impact improvement for retrieval quality [3].
5. **Write explicitly** — use specific terms, avoid pronouns and implicit references. Each file should be understandable in isolation.
6. **Prefer structured formats** (bullets, tables, numbered steps) over prose paragraphs.

### For the Data Layer (engineering)

7. **Implement hybrid search** from day one — BM25 (Whoosh) + metadata filtering (PostgreSQL). Add pgvector when the dataset exceeds ~500 files or when users report "I know I wrote about this but the agent didn't find it" [13, 14].
8. **Prepend contextual summaries** to chunks before indexing (per Anthropic's Contextual Retrieval [5]). This is the single highest-impact engineering improvement for retrieval quality.
9. **Order context by attention zones** — high-priority content at beginning and end, lower-priority in the middle [10, 11].
10. **Implement three-tier memory** — working (in-context), episodic (PostgreSQL), semantic (vault + embeddings) [8, 16, 17].
11. **Auto-generate metadata** — summaries, token counts, key entities, and "questions answered" for every file [18].
12. **No chunk overlap** — research shows it provides no benefit while increasing cost [4].
13. **Use Reciprocal Rank Fusion** to combine results from multiple retrievers rather than ad-hoc score combination [13].

### For Context Assembly (orchestrator)

14. **Hard token budget** with priority-based allocation. Reserve 20–30% for model output [12].
15. **Summarize old conversation history** rather than truncating it [16, 17].
16. **Include 5–10 files maximum** per request. Diminishing returns beyond this threshold [4, 10].
17. **Memory confidence scoring** — new memories start low, increase with use, decrease with corrections [8].

---

## Appendix A: References

### Retrieval-Augmented Generation and Chunking

[1] **HiQA: A Hierarchical Contextual Augmentation RAG for Multi-Documents QA.** Zhu, Y. et al. (2024). arXiv:2402.01767. — Demonstrates that hierarchical document structure (heading hierarchy, cascading metadata) significantly improves retrieval accuracy and token efficiency in multi-document QA.

[2] **MDEval: Evaluating and Enhancing Markdown Awareness in Large Language Models.** Ren, F. et al. (2025). Proceedings of WWW 2025. arXiv:2501.15000. — Establishes that Markdown structure quality is measurable and directly correlates with LLM output quality. Introduces a benchmark with 0.791 Spearman correlation with human evaluation.

[3] **Multi-Meta-RAG: Improving RAG for Multi-Hop Queries using Database Filtering with LLM-Extracted Metadata.** Bayazit, D. et al. (2024). arXiv:2406.13213. — Shows that LLM-extracted metadata with database pre-filtering achieves 82.5% precision vs. 73.3% for content-only retrieval; critical for multi-hop queries.

[4] **Enhancing Retrieval-Augmented Generation: A Study of Best Practices.** Lu, X. et al. (2025). Proceedings of COLING 2025. arXiv:2501.07391. — Comprehensive evaluation of chunking strategies: sentence-level chunking matches semantic chunking; no benefit from chunk overlap; "context cliff" at ~2.5K tokens.

[5] **Contextual Retrieval.** Anthropic (2024). anthropic.com/engineering/contextual-retrieval. — Demonstrates that prepending contextual summaries to chunks before embedding reduces retrieval failures by 49% (67% with reranking). Recommends combining contextual embeddings with contextual BM25.

### Hybrid Search and Retrieval Strategies

[6] **PersonalAI: A Systematic Comparison of Knowledge Graph Storage and Retrieval Approaches for Personalized LLM Agents.** (2025). arXiv:2506.17001. — Systematic comparison finding that no single storage mechanism is optimal; recommends hybrid architectures with knowledge graphs for relational reasoning and vector stores for semantic similarity.

[7] **HetaRAG: Hybrid Deep Retrieval-Augmented Generation across Heterogeneous Data Stores.** (2025). arXiv:2509.21336. — Shows that orchestrating multiple data stores (vector, knowledge graph, full-text, structured DB) into a unified retrieval plane improves both recall and precision.

[13] **Blended RAG: Improving RAG Accuracy with Semantic Search and Hybrid Query-Based Retrievers.** Sawarkar, K. et al. (2024). arXiv:2404.07220. — Demonstrates that combining dense (vector) and sparse (BM25) retrieval consistently outperforms either alone across standard benchmarks.

[14] **Mixture-of-Retrievers (MoR).** (2025). EMNLP 2025. — Dynamic per-query retriever selection achieves +10.8% improvement over individual retrievers.

### Memory and Long-Term Personalization

[8] **A-MEM: Agentic Memory for LLM Agents.** (2025). arXiv:2502.12110. — Zettelkasten-inspired memory system with structured notes, inter-memory connections, and "memory evolution" where new memories update existing ones. Provides the theoretical basis for confidence-scored, connected memories.

[9] **Knoll: Creating a Knowledge Ecosystem for Large Language Models.** (2025). arXiv:2505.19335. — Software infrastructure enabling end-users to create and curate custom knowledge modules for LLMs. Demonstrates that user-curated knowledge improves response quality in deployment with 200+ users.

[16] **Reflective Memory Management for Long-term Personalized Dialogue Agents.** (2025). ACL 2025. arXiv:2503.08026. — Introduces prospective reflection (multi-resolution summarization) and retrospective reflection (RL-refined retrieval), achieving 10%+ accuracy improvement for long-term personalized dialogue.

[17] **MemGPT: Towards LLMs as Operating Systems.** Packer, C. et al. (2023). arXiv:2310.08560. — Applies OS memory management (paging between fast/slow storage) to LLMs. Introduces tiered memory hierarchy and self-directed memory management via tool calls.

### Context Window and Attention

[10] **Lost in the Middle: How Language Models Use Long Contexts.** Liu, N.F. et al. (2024). *Transactions of the Association for Computational Linguistics (TACL)*. — Landmark paper demonstrating U-shaped attention: models attend to beginning and end of context, underperform on middle content. Validated across GPT-3.5-Turbo, GPT-4, Claude.

[11] **Found in the Middle: Calibrating Positional Attention Bias Improves Long Context Utilization.** (2024). Findings of ACL 2024. — Identifies root cause of "lost in the middle" as intrinsic attention bias; proposes calibration mechanism improving RAG performance by up to 10pp.

[12] **Token-Budget-Aware LLM Reasoning.** (2024). arXiv:2412.18547. — Shows that explicit token budget constraints in prompts reduce cost without quality degradation; LLM reasoning is often unnecessarily verbose when unconstrained.

### Infrastructure

[15] **When Large Language Models Meet Vector Databases: A Survey.** (2024). arXiv:2402.01763. — Comprehensive survey on LLM + vector database synergy for addressing hallucinations and outdated knowledge.

[18] **Automated Metadata Extraction for Better Retrieval and Synthesis.** LlamaIndex documentation and associated research (2024). — Demonstrates that auto-generating "questions answered" metadata for each chunk significantly improves query-to-chunk matching.

[19] **The 150x pgvector Speedup: A Year-in-Review.** Katz, J. (2024). jkatz.github.io. — Documents pgvector's performance evolution: HNSW indexing, quantization, and parallel builds bring PostgreSQL vector search to sub-100ms latency for million-scale datasets.

### Knowledge Graph for Personalization

[20] **HybGRAG: Hybrid Retrieval-Augmented Generation on Textual and Relational Knowledge Bases.** (2024). ACL 2025. arXiv:2412.16311. — Combines textual and relational retrieval for semi-structured knowledge, achieving 51% improvement in Hit@1 on the STaRK benchmark.

### Ambition Ceiling: Long Context, Digital Memory, and Personalization

[21] **Gemini 1.5: Unlocking Multimodal Understanding across Millions of Tokens of Context.** Google DeepMind (2024). — Demonstrates near-perfect retrieval up to 10M tokens on synthetic tasks, establishing the upper bound of raw context window capability.

[22] **Efficient Solutions for an Intriguing Failure of LLMs: Long Context Window Does Not Mean LLMs Can Analyze Long Sequences Flawlessly.** (2024). arXiv:2408.01866. — Shows significant performance degradation on analytical tasks with long inputs across Claude 3, Gemini Pro, GPT-3.5 Turbo, Llama 3, and Mistral — even within their stated context limits. Proposes solutions improving performance by up to 50% while reducing cost by 93%.

[23] **Retrieval Augmented Generation or Long-Context LLMs? A Comprehensive Study and Hybrid Approach.** (2024). arXiv:2407.16833. — Systematic comparison finding that RAG matches or outperforms long-context on most tasks at 10–100x lower cost. Introduces Self-Route, a hybrid that dynamically routes queries to RAG or long-context based on self-reflection.

[24] **PersonaMem-v2: Towards Personalized Intelligence via Learning Implicit User Personas and Agentic Memory.** (2025). arXiv:2512.06688. — Trains AI on implicit user preferences through interaction history. Achieves 55% accuracy on implicit personalization (vs. 37–48% for frontier LLMs) while reducing token usage by 16x. Establishes the current frontier of personal AI.

[25] **OmniQuery: Contextually Augmenting Captured Multimodal Memory to Enable Personal Question Answering.** (2024). arXiv:2409.08250. — Demonstrates 71.5% accuracy on complex personal questions by augmenting captured memories (photos, screenshots, notes) with contextual information across interconnected data sources.

[26] **Memoria: Scalable Personalized Memory for Conversational AI.** (2024). arXiv:2512.12686. — Hybrid architecture combining session-level summarization with weighted knowledge graphs, achieving 87.1% accuracy while reducing inference latency by 38.7%.

[27] **Toward Conversational Agents with Context and Time Sensitive Long-term Memory.** (2024). arXiv:2406.00057. — Addresses temporal reasoning challenges in personal AI: time-based queries and ambiguous queries requiring surrounding context. Demonstrates that hybrid retrieval with temporal awareness outperforms standard RAG.

[28] **Brain Cache: Generative AI as a Cognitive Exoskeleton.** (2025). GenAICHI Workshop, CHI 2025. — Proposes AI as a "neural co-processor" that externalizes biological memory into personal knowledge repositories, structures fragmented insights into semantic networks, and activates knowledge through contextual recommendations.

[29] **Human-inspired Perspectives: A Survey on AI Long-term Memory.** (2024). arXiv:2411.00489. — Comprehensive survey mapping human memory types (episodic, semantic, procedural) to AI architectures. Proposes the Self-Adaptive Long-term Memory (SALM) framework for next-generation personal AI systems.

[R1] **Email volume estimation.** Cue app data reported in *The Atlantic* (2013). — Average user sends ~41,638 words per year via email, equivalent to a 166-page novel. Used for the lifetime data volume estimate in Section 10.1.

---

*This document should be updated as new research emerges. The field is moving fast — papers from 2024-2025 may be superseded by 2026 findings. Key areas to watch: contextual retrieval improvements, graph-based memory systems, native long-context model architectures that may reduce the need for aggressive context window management, and implicit personalization research (PersonaMem and successors).*
