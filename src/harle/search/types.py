"""Data types for the search algorithm.

Defines the query and result structures used throughout the search
pipeline. These types form the stable interface between the search
engine and the rest of the system — implementations can change
without affecting callers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


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
    agent_role: str | None = None  # For Phase 2 role-term expansion


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
        token_count: Estimated tokens (for budget-aware assembly).
        summary: Short summary (from file_index).
        source: Origin of the result (e.g. "whoosh", "metadata").
        last_modified: File last modified time (for recency ranking).
        chunk_index: When set, this hit is a section/chunk (Whoosh composite id).
        heading_path: Cascading heading path for chunk hits (HiQA-style).
    """

    file_path: str
    title: str
    score: float
    context: str | None = None
    tags: list[str] = field(default_factory=list)
    snippet: str | None = None
    token_count: int | None = None
    summary: str | None = None
    source: str = "whoosh"
    last_modified: datetime | None = None
    chunk_index: int | None = None
    heading_path: str | None = None


@dataclass(frozen=True)
class ExpandedQuery:
    """Output of query expansion for the Phase 2 pipeline.

    Attributes:
        whoosh_terms: Stemmed/normalized terms for Whoosh BM25.
        tag_filters: Tags matched from vocabulary (for metadata pre-filter).
        role_terms: Role-specific terms added to the query.
        context_filter: Context scope (work / personal).
        raw_query: Original user query string.
    """

    whoosh_terms: list[str]
    tag_filters: list[str]
    role_terms: list[str]
    context_filter: str | None
    raw_query: str


@dataclass(frozen=True)
class QueryMetadata:
    """Metadata about how the search was executed.

    Attributes:
        original_query: User's raw query.
        expanded_terms: Terms used for Whoosh/search.
        tags_matched: Tags that matched the tag vocabulary.
        candidates_count: Number of files after pre-filter.
        search_time_ms: Total search duration in milliseconds.
        phase: Engine phase (e.g. "keyword", "whoosh").
    """

    original_query: str
    expanded_terms: list[str]
    tags_matched: list[str]
    candidates_count: int
    search_time_ms: float
    phase: str


@dataclass(frozen=True)
class MemoryResult:
    """A single memory entry relevant to the query.

    Attributes:
        content: Memory text.
        category: Memory category.
        confidence: Confidence score (0–1).
    """

    content: str
    category: str
    confidence: float


@dataclass(frozen=True)
class PriorRunResult:
    """A prior run similar to the current query.

    Attributes:
        run_id: Unique run identifier.
        user_request: User request from that run.
        result_summary: Short summary of the result.
        files_used: Dataset files included in context.
        agent: Agent role that handled the run.
    """

    run_id: str
    user_request: str
    result_summary: str | None
    files_used: list[str]
    agent: str


@dataclass(frozen=True)
class SearchResponse:
    """Full search result set (Phase 2+).

    Attributes:
        file_results: Ranked file matches.
        memory_results: Relevant memories.
        prior_runs: Similar past runs.
        query_metadata: Expansion details and timing.
    """

    file_results: list[SearchResult]
    memory_results: list[MemoryResult]
    prior_runs: list[PriorRunResult]
    query_metadata: QueryMetadata
