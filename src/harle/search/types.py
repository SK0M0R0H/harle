"""Data types for the search algorithm.

Defines the query and result structures used throughout the search
pipeline. These types form the stable interface between the search
engine and the rest of the system — implementations can change
without affecting callers.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SearchQuery:
    """Input to the search engine.

    Attributes:
        query: Free-text user query.
        context: Optional context scope filter (``work`` / ``personal``).
        max_results: Maximum number of results to return.
    """

    query: str
    context: str | None = None
    max_results: int = 10


@dataclass(frozen=True)
class SearchResult:
    """A single search result with relevance score.

    Attributes:
        file_path: Path relative to the dataset root.
        title: Human-readable title (from frontmatter or filename).
        score: Relevance score (higher is better, not normalized).
        context: Context scope of the file.
        tags: Tags from frontmatter.
        snippet: Optional short excerpt showing the match.
    """

    file_path: str
    title: str
    score: float
    context: str | None = None
    tags: list[str] = field(default_factory=list)
    snippet: str | None = None
