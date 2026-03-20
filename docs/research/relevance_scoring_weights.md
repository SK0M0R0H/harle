---
title: "Default Weights for Context Relevance Scoring"
tags: [relevance-scoring, retrieval, ranking, context-assembly, data-layer]
context: global
last_updated: 2026-03-20
summary: "Defines and explains the default six-component relevance-scoring weights used for context assembly."
---

# Default Weights for Context Relevance Scoring

This note defines the default relevance-scoring weights used by Context Assembly and explains the rationale behind each default.

Reference formula from Data Layer Best Practices section 4.4:

```text
Relevance Score = (
    0.35 * search_relevance
  + 0.20 * metadata_match
  + 0.15 * recency
  + 0.15 * source_priority
  + 0.10 * memory_confidence
  + 0.05 * prior_run_success
)
```

All components are normalized to a 0-1 range before weighting.

## Why these defaults

- `search_relevance = 0.35`: Primary retrieval quality signal (BM25 now; pgvector later), so it remains the largest term.
- `metadata_match = 0.20`: Multi-Meta-RAG findings in Best Practices section 4.4 support strong metadata filtering and matching.
- `recency = 0.15`: Personal knowledge changes over time, so recent files should receive a meaningful but not dominant boost.
- `source_priority = 0.15`: Encodes vault hierarchy reliability (for example prompts/policies over logs), but avoids overpowering query relevance.
- `memory_confidence = 0.10`: Reserves explicit capacity for memory reliability as memory retrieval becomes fully integrated.
- `prior_run_success = 0.05`: Useful as a weak historical prior; kept small to reduce cold-start bias and prevent overfitting to past runs.

## Normalization contract

The scoring pipeline assumes each component is in the `0.0..1.0` interval:

- `search_relevance`: normalized from retriever raw score within the candidate set.
- `metadata_match`: overlap fraction of query metadata filters and candidate metadata.
- `recency`: exponential decay from last-modified time to `0.0..1.0`.
- `source_priority`: static mapping by top-level source directory to `0.0..1.0`.
- `memory_confidence`: memory-provided confidence `0.0..1.0` (currently stubbed for file-only ranking).
- `prior_run_success`: binary or continuous success prior from similar historical runs.

## Tuning guidance

- Keep total weight close to `1.0` for interpretability.
- Change one weight at a time and compare retrieval quality on representative requests.
- If many stale files outrank newer relevant notes, increase recency slightly (`+0.05`) and offset from source priority or prior-run weight.
- If policy/prompt documents dominate too aggressively, reduce source priority before changing search relevance.
