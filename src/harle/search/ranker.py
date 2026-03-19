"""Multi-source result ranker for Phase 2.

Combines Whoosh BM25 scores with metadata signals (tag match, recency,
source priority, prior-run bonus) into a single weighted score. Chunk
hits are keyed by composite doc path; optional cap limits chunks per
vault file in the ranked list.
"""

from __future__ import annotations

from datetime import datetime, timezone
from math import exp

from harle.search.types import SearchResult
from harle.search.whoosh_index import WhooshSearchHit

# Vault directory -> priority score (0–1). TRD: prompts/policies P0, workflows P1, etc.
_SOURCE_PRIORITY: dict[str, float] = {
    "prompts": 1.0,
    "policies": 1.0,
    "workflows": 0.8,
    "knowledge": 0.6,
    "examples": 0.4,
    "logs": 0.2,
}


def _source_priority_score(file_path: str) -> float:
    """Return source priority (0–1) from path prefix."""
    for prefix, score in _SOURCE_PRIORITY.items():
        if file_path.startswith(prefix + "/"):
            return score
    return 0.3  # default for other dirs


def _recency_score(last_modified: datetime | None) -> float:
    """Decay by days since last_modified; 0–1 scale."""
    if last_modified is None:
        return 0.0
    now = datetime.now(timezone.utc)
    if last_modified.tzinfo is None:
        last_modified = last_modified.replace(tzinfo=timezone.utc)
    delta = now - last_modified
    days = max(0, delta.total_seconds() / 86400)
    return exp(-days / 30.0)


def _tag_match_score(file_tags: list[str] | None, query_tag_filters: list[str]) -> float:
    """Proportion of query tag_filters that appear in the file's tags."""
    if not query_tag_filters:
        return 0.0
    file_set = {t.lower() for t in (file_tags or [])}
    matched = sum(1 for t in query_tag_filters if t.lower() in file_set)
    return matched / len(query_tag_filters)


def _prior_run_bonus(file_path: str, prior_run_files: set[str]) -> float:
    """1.0 if file was used in a similar prior run, else 0.0."""
    return 1.0 if file_path in prior_run_files else 0.0


def _cap_chunks_per_file(
    results: list[SearchResult],
    max_per_file: int,
) -> list[SearchResult]:
    """Keep global score order; skip once a file has max_per_file results."""
    if max_per_file <= 0:
        max_per_file = 3
    counts: dict[str, int] = {}
    out: list[SearchResult] = []
    for r in results:
        n = counts.get(r.file_path, 0)
        if n >= max_per_file:
            continue
        counts[r.file_path] = n + 1
        out.append(r)
    return out


def rank(
    whoosh_hits: list[WhooshSearchHit],
    path_to_metadata: dict[str, object],
    *,
    tag_filters: list[str],
    prior_run_files: set[str] | None = None,
    bm25_weight: float = 0.25,
    tag_match_weight: float = 0.20,
    recency_weight: float = 0.15,
    source_priority_weight: float = 0.63,
    prior_run_weight: float = 0.10,
    max_chunks_per_file: int = 3,
) -> list[SearchResult]:
    """Combine Whoosh scores with metadata and return ranked SearchResults."""
    if not whoosh_hits:
        return []

    prior_run_files = prior_run_files or set()
    scores_only = [h.score for h in whoosh_hits]
    min_bm25 = min(scores_only)
    max_bm25 = max(scores_only)
    bm25_range = max_bm25 - min_bm25 if max_bm25 > min_bm25 else 1.0

    by_doc: dict[str, float] = {}
    meta_by_path: dict[str, object] = dict(path_to_metadata)
    hit_by_doc: dict[str, WhooshSearchHit] = {h.doc_path: h for h in whoosh_hits}

    for hit in whoosh_hits:
        norm_bm25 = (hit.score - min_bm25) / bm25_range if bm25_range else 0.0
        meta = meta_by_path.get(hit.file_path)
        tags = getattr(meta, "tags", None) or []
        last_mod = getattr(meta, "last_modified", None)

        tag_s = _tag_match_score(tags, tag_filters)
        rec_s = _recency_score(last_mod)
        src_s = _source_priority_score(hit.file_path)
        prior_s = _prior_run_bonus(hit.file_path, prior_run_files)

        final = (
            bm25_weight * norm_bm25
            + tag_match_weight * tag_s
            + recency_weight * rec_s
            + source_priority_weight * src_s
            + prior_run_weight * prior_s
        )
        by_doc[hit.doc_path] = final

    sorted_docs = sorted(by_doc.keys(), key=lambda d: by_doc[d], reverse=True)
    results: list[SearchResult] = []
    for doc_path in sorted_docs:
        hit = hit_by_doc[doc_path]
        meta = meta_by_path.get(hit.file_path)
        title = getattr(meta, "title", None) or hit.file_path
        tags = getattr(meta, "tags", None) or []
        context = getattr(meta, "context", None)
        token_count = getattr(meta, "token_count", None)
        summary = getattr(meta, "summary", None)
        last_modified = getattr(meta, "last_modified", None)
        hp = (hit.heading_path or "").strip() or None
        results.append(
            SearchResult(
                file_path=hit.file_path,
                title=title,
                score=by_doc[doc_path],
                context=context,
                tags=tags or [],
                snippet=None,
                token_count=token_count,
                summary=summary,
                source="whoosh",
                last_modified=last_modified,
                chunk_index=hit.chunk_index,
                heading_path=hp,
            )
        )

    return _cap_chunks_per_file(results, max_chunks_per_file)
