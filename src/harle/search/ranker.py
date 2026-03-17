"""Multi-source result ranker for Phase 2.

Combines Whoosh BM25 scores with metadata signals (tag match, recency,
source priority, prior-run bonus) into a single weighted score and
deduplicates by file path.
"""

from __future__ import annotations

from datetime import datetime, timezone
from math import exp

from harle.search.types import SearchResult

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
    # Decay: 1.0 at 0 days, ~0.37 at 30 days (e^(-1))
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


def rank(
    whoosh_results: list[tuple[str, float]],
    path_to_metadata: dict[str, object],
    *,
    tag_filters: list[str],
    prior_run_files: set[str] | None = None,
    bm25_weight: float = 0.25,
    tag_match_weight: float = 0.20,
    recency_weight: float = 0.15,
    source_priority_weight: float = 0.63,
    prior_run_weight: float = 0.10,
) -> list[SearchResult]:
    """Combine Whoosh scores with metadata and return ranked SearchResults.

    Args:
        whoosh_results: List of (path, bm25_score) from Whoosh.
        path_to_metadata: Map path -> object with .title, .tags, .context,
            .token_count, .summary, .last_modified (e.g. FileIndex).
        tag_filters: Query tag filters for tag_match_score.
        prior_run_files: Set of paths that appeared in similar prior runs.
        bm25_weight: Weight for normalized BM25.
        tag_match_weight: Weight for tag overlap.
        recency_weight: Weight for recency decay.
        source_priority_weight: Weight for vault directory priority.
        prior_run_weight: Weight for prior-run bonus.

    Returns:
        List of :class:`SearchResult` sorted by final score descending,
        deduplicated by path.
    """
    if not whoosh_results:
        return []

    prior_run_files = prior_run_files or set()

    # Normalize BM25 to 0–1 (min-max).
    scores_only = [s for _, s in whoosh_results]
    min_bm25 = min(scores_only)
    max_bm25 = max(scores_only)
    bm25_range = max_bm25 - min_bm25 if max_bm25 > min_bm25 else 1.0

    by_path: dict[str, float] = {}
    meta_by_path: dict[str, object] = dict(path_to_metadata)

    for path, bm25 in whoosh_results:
        norm_bm25 = (bm25 - min_bm25) / bm25_range if bm25_range else 0.0
        meta = meta_by_path.get(path)
        title = getattr(meta, "title", None) or path
        tags = getattr(meta, "tags", None) or []
        context = getattr(meta, "context", None)
        last_mod = getattr(meta, "last_modified", None)

        tag_s = _tag_match_score(tags, tag_filters)
        rec_s = _recency_score(last_mod)
        src_s = _source_priority_score(path)
        prior_s = _prior_run_bonus(path, prior_run_files)

        final = (
            bm25_weight * norm_bm25
            + tag_match_weight * tag_s
            + recency_weight * rec_s
            + source_priority_weight * src_s
            + prior_run_weight * prior_s
        )
        by_path[path] = final

    # Deduplicate and sort; build SearchResult for each path (keep order by score).
    sorted_paths = sorted(by_path.keys(), key=lambda p: by_path[p], reverse=True)
    results: list[SearchResult] = []
    for path in sorted_paths:
        meta = meta_by_path.get(path)
        title = getattr(meta, "title", None) or path
        tags = getattr(meta, "tags", None) or []
        context = getattr(meta, "context", None)
        token_count = getattr(meta, "token_count", None)
        summary = getattr(meta, "summary", None)
        last_modified = getattr(meta, "last_modified", None)
        results.append(
            SearchResult(
                file_path=path,
                title=title,
                score=by_path[path],
                context=context,
                tags=tags or [],
                snippet=None,
                token_count=token_count,
                summary=summary,
                source="whoosh",
                last_modified=last_modified,
            )
        )
    return results
