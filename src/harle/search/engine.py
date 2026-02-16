"""Simple keyword search engine for small datasets.

Iterates all indexed files, loads content from disk, and performs
case-insensitive term matching with basic relevance scoring.

Designed to be replaced with Whoosh full-text search and pgvector
semantic search as the dataset grows beyond ~100 files.
"""

from __future__ import annotations

import logging
from pathlib import Path

from harle.db.connection import Database
from harle.db.file_index import get_all_entries
from harle.search.types import SearchQuery, SearchResult

logger = logging.getLogger(__name__)

# Scoring weights for term matches in different fields.
_TITLE_WEIGHT = 3.0
_TAG_WEIGHT = 2.0
_CONTENT_WEIGHT = 0.5
_CONTENT_CAP = 3.0  # Max score contribution from content matches per term.


class SearchEngine:
    """Keyword-based search over the indexed dataset.

    For each query, retrieves file metadata from PostgreSQL, loads
    content from disk, and scores by simple term-frequency matching.

    Args:
        dataset_path: Absolute path to the vault root.
        db: Database instance for querying the file_index table.
    """

    def __init__(self, dataset_path: str, db: Database) -> None:
        self.dataset_path = Path(dataset_path)
        self.db = db

    def search(self, query: SearchQuery) -> list[SearchResult]:
        """Execute a search and return ranked results.

        Args:
            query: The search query with optional filters.

        Returns:
            List of :class:`SearchResult` sorted by relevance score
            (descending), limited to ``query.max_results``.
        """
        terms = _tokenize(query.query)
        if not terms:
            return []

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
        return results[: query.max_results]


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
    """Score a file against a set of search terms.

    Weights: title matches > tag matches > content matches.
    Content match score is capped per term to avoid long files
    dominating results.
    """
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
    """Extract a short snippet around the first matched term.

    Args:
        content: Full file content.
        terms: Search terms to look for.
        max_length: Maximum snippet length in characters.

    Returns:
        A text snippet containing the first match, or the start of
        the content if no term is found.
    """
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
