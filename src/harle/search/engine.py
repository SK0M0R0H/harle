"""Search engine: Phase 1 (keyword) and Phase 2 (Whoosh) pipelines.

Phase 1 iterates indexed files and scores by term matching. Phase 2
uses query expansion, metadata pre-filter, Whoosh BM25, and ranking.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from harle.db.connection import Database
from harle.db.file_index import (
    get_all_entries,
    get_all_tags,
    get_candidates_for_search,
    get_entries_by_paths,
)
from harle.db.memories import search_memories
from harle.db.runs import search_similar_runs
from harle.debug import etrace
from harle.search.query_expander import expand
from harle.search.ranker import rank
from harle.search.types import (
    MemoryResult,
    PriorRunResult,
    QueryMetadata,
    SearchQuery,
    SearchResponse,
    SearchResult,
)
from harle.search import whoosh_index

logger = logging.getLogger(__name__)


def _rebuild_whoosh_index(dataset_path: Path, index_path: Path, log: logging.Logger) -> None:
    """Rebuild the Whoosh index from scratch; log and swallow errors."""
    try:
        from harle.dataset.reader import DatasetReader
        reader = DatasetReader(str(dataset_path))
        whoosh_index.build_from_scratch(reader, index_path)
    except Exception as e:
        log.warning("Whoosh index rebuild failed: %s", e)


def _whoosh_search_safe(
    index_path: Path,
    whoosh_terms: list[str],
    candidate_paths: set[str],
    log: logging.Logger,
) -> list[tuple[str, float]] | None:
    """Run Whoosh search; return None on failure (e.g. corrupt index)."""
    try:
        return whoosh_index.search(
            index_path,
            whoosh_terms,
            candidate_paths,
            limit=50,
        )
    except Exception as e:
        log.warning("Whoosh search failed: %s", e)
        return None


# Scoring weights for Phase 1 term matches.
_TITLE_WEIGHT = 3.0
_TAG_WEIGHT = 2.0
_CONTENT_WEIGHT = 0.5
_CONTENT_CAP = 3.0


class SearchEngine:
    """Search over the indexed dataset (Phase 1 keyword or Phase 2 Whoosh).

    Args:
        dataset_path: Absolute path to the vault root.
        db: Database instance for file_index, memories, runs.
        search_config: Optional Phase 2 config; if None, engine uses
            keyword-only (Phase 1) or calls get_search_config() when needed.
    """

    def __init__(
        self,
        dataset_path: str,
        db: Database,
        search_config: object | None = None,
    ) -> None:
        self.dataset_path = Path(dataset_path)
        self.db = db
        self._search_config = search_config

    def search(self, query: SearchQuery) -> SearchResponse:
        """Execute a search and return a full response (files, memories, metadata).

        Uses Phase 2 (Whoosh) when config.engine is "whoosh" and the
        Whoosh index is available; otherwise uses Phase 1 (keyword).
        """
        t0 = time.perf_counter()
        config = self._get_config()
        engine_name = getattr(config, "engine", "keyword") or "keyword"

        if engine_name == "whoosh":
            response = self._search_phase2(query, config, t0)
        else:
            response = self._search_phase1(query, t0)

        return response

    def _get_config(self) -> object:
        if self._search_config is not None:
            return self._search_config
        from harle.config import get_search_config
        return get_search_config()

    def _search_phase1(self, query: SearchQuery, t0: float) -> SearchResponse:
        """Phase 1: keyword search over all candidates."""
        terms = _tokenize(query.query)
        if not terms:
            etrace.detail("Search skipped", module="search", reason="empty_query")
            return SearchResponse(
                file_results=[],
                memory_results=[],
                prior_runs=[],
                query_metadata=QueryMetadata(
                    original_query=query.query,
                    expanded_terms=[],
                    tags_matched=[],
                    candidates_count=0,
                    search_time_ms=(time.perf_counter() - t0) * 1000,
                    phase="keyword",
                ),
            )

        etrace.detail(
            "Search query",
            module="search",
            query=query.query[:200],
            context=query.context,
            max_results=query.max_results,
        )

        with self.db.session() as session:
            candidates = get_all_entries(session, context=query.context)

        results: list[SearchResult] = []
        for candidate in candidates:
            file_path = self.dataset_path / candidate.file_path
            if not file_path.exists():
                continue
            try:
                content = file_path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            score = _compute_score(
                terms=terms,
                title=candidate.title or "",
                tags=candidate.tags or [],
                content=content,
            )
            if score > 0:
                results.append(
                    SearchResult(
                        file_path=candidate.file_path,
                        title=candidate.title or candidate.file_path,
                        score=score,
                        context=candidate.context,
                        tags=candidate.tags or [],
                        snippet=_extract_snippet(content, terms),
                    )
                )

        results.sort(key=lambda r: r.score, reverse=True)
        limited = results[: query.max_results]

        for r in limited[:5]:
            etrace.trace_entry(
                "Search result score",
                module="search",
                file_path=r.file_path,
                score=round(r.score, 2),
            )
        etrace.step(
            "Search executed",
            module="search",
            result_count=len(limited),
            scoring="keyword",
        )

        return SearchResponse(
            file_results=limited,
            memory_results=[],
            prior_runs=[],
            query_metadata=QueryMetadata(
                original_query=query.query,
                expanded_terms=terms,
                tags_matched=[],
                candidates_count=len(candidates),
                search_time_ms=(time.perf_counter() - t0) * 1000,
                phase="keyword",
            ),
        )

    def _search_phase2(self, query: SearchQuery, config: object, t0: float) -> SearchResponse:
        """Phase 2: expand -> pre-filter -> Whoosh -> enrich -> memory/prior -> rank."""
        index_path_str = getattr(config, "whoosh_index_path", "") or ""
        index_path = Path(index_path_str).expanduser() if index_path_str else None
        max_results = query.max_results if query.max_results is not None and query.max_results > 0 else (getattr(config, "max_results", 10) or 10)
        max_mem = getattr(config, "max_memories", 10) or 10
        max_runs = getattr(config, "max_prior_runs", 5) or 5
        min_conf = getattr(config, "memory_min_confidence", 0.3) or 0.0

        etrace.detail(
            "Search query",
            module="search",
            query=query.query[:200],
            context=query.context,
            max_results=max_results,
        )

        with self.db.session() as session:
            tag_vocabulary = get_all_tags(session)
            expanded = expand(query, tag_vocabulary, config)
            etrace.detail(
                "Query expanded",
                module="search",
                whoosh_terms=expanded.whoosh_terms[:20],
                tag_filters=expanded.tag_filters,
            )

            candidates = get_candidates_for_search(
                session,
                context=query.context,
                tag_filters=expanded.tag_filters or None,
                include_global=True,
            )
            candidate_paths = {c.file_path for c in candidates}
            candidates_by_path = {c.file_path: c for c in candidates}

            if not expanded.whoosh_terms or not index_path:
                # No Whoosh terms or no index: return empty file results but still memory/prior
                whoosh_results = []
            else:
                if not index_path.exists() or not whoosh_index.exists_in(str(index_path)):
                    etrace.detail("Whoosh index missing, rebuilding", module="search")
                    _rebuild_whoosh_index(self.dataset_path, index_path, logger)
                    whoosh_results = _whoosh_search_safe(
                        index_path, expanded.whoosh_terms, candidate_paths, logger,
                    ) or []
                else:
                    whoosh_results = _whoosh_search_safe(
                        index_path, expanded.whoosh_terms, candidate_paths, logger,
                    )
                    if whoosh_results is None:
                        etrace.detail("Whoosh index corrupt, rebuilding", module="search")
                        _rebuild_whoosh_index(self.dataset_path, index_path, logger)
                        whoosh_results = _whoosh_search_safe(
                            index_path, expanded.whoosh_terms, candidate_paths, logger,
                        ) or []

            top_paths = [p for p, _ in whoosh_results[: max_results * 2]]
            enriched = get_entries_by_paths(session, top_paths)
            for e in enriched:
                candidates_by_path[e.file_path] = e

            memory_rows = search_memories(
                session,
                context_scope=query.context or "personal",
                query_text=query.query or "",
                min_confidence=min_conf,
                limit=max_mem,
            )
            memory_results = [
                MemoryResult(
                    content=m.content,
                    category=m.category,
                    confidence=float(m.confidence or 0),
                )
                for m in memory_rows
            ]

            run_rows = search_similar_runs(
                session,
                context_scope=query.context or "personal",
                query_text=query.query or "",
                limit=max_runs,
            )
            prior_runs = [
                PriorRunResult(
                    run_id=r.run_id,
                    user_request=r.user_request,
                    result_summary=r.result_summary,
                    files_used=list(r.files_used or []),
                    agent=r.agent,
                )
                for r in run_rows
            ]
            prior_run_files = set()
            for r in run_rows:
                if r.files_used:
                    prior_run_files.update(r.files_used)

            ranked = rank(
                whoosh_results,
                candidates_by_path,
                tag_filters=expanded.tag_filters or [],
                prior_run_files=prior_run_files,
                bm25_weight=getattr(config, "bm25_weight", 0.40),
                tag_match_weight=getattr(config, "tag_match_weight", 0.20),
                recency_weight=getattr(config, "recency_weight", 0.15),
                source_priority_weight=getattr(config, "source_priority_weight", 0.15),
                prior_run_weight=getattr(config, "prior_run_weight", 0.10),
            )
            limited = ranked[:max_results]

        for r in limited[:5]:
            etrace.trace_entry(
                "Search result score",
                module="search",
                file_path=r.file_path,
                score=round(r.score, 2),
            )
        etrace.step(
            "Search executed",
            module="search",
            result_count=len(limited),
            scoring="whoosh",
        )

        return SearchResponse(
            file_results=limited,
            memory_results=memory_results,
            prior_runs=prior_runs,
            query_metadata=QueryMetadata(
                original_query=query.query,
                expanded_terms=expanded.whoosh_terms,
                tags_matched=expanded.tag_filters or [],
                candidates_count=len(candidates),
                search_time_ms=(time.perf_counter() - t0) * 1000,
                phase="whoosh",
            ),
        )


def _tokenize(text: str) -> list[str]:
    """Split text into lowercase tokens, dropping very short words."""
    return [w.lower() for w in text.split() if len(w) > 1]


def _compute_score(
    *,
    terms: list[str],
    title: str,
    tags: list[str],
    content: str,
) -> float:
    """Score a file against a set of search terms (Phase 1)."""
    score = 0.0
    title_lower = title.lower()
    tags_lower = {t.lower() for t in tags}
    content_lower = content.lower()

    for term in terms:
        if term in title_lower:
            score += _TITLE_WEIGHT
        for tag in tags_lower:
            if term in tag:
                score += _TAG_WEIGHT
                break
        count = content_lower.count(term)
        score += min(count * _CONTENT_WEIGHT, _CONTENT_CAP)

    return score


def _extract_snippet(content: str, terms: list[str], max_length: int = 200) -> str:
    """Extract a short snippet around the first matched term."""
    content_lower = content.lower()
    for term in terms:
        pos = content_lower.find(term)
        if pos >= 0:
            start = max(0, pos - 60)
            end = min(len(content), pos + max_length - 60)
            snippet = content[start:end].replace("\n", " ").strip()
            if start > 0:
                snippet = "..." + snippet
            if end < len(content):
                snippet = snippet + "..."
            return snippet

    return content[:max_length].replace("\n", " ").strip() + "..."
