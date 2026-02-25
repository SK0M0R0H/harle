"""Async HTTP wrapper for web search providers.

Abstracts over multiple search backends (Tavily, Bing, SearXNG) behind
a common interface.  The :class:`WebSearchClient` is initialised once
by :class:`WebSearchModule` and accessed by tool functions via
:func:`get_client`.

Provider selection is config-driven (``provider`` field).  Tavily is
the primary implementation; Bing and SearXNG are stubs that will be
filled in when those providers are needed.

Usage::

    client = WebSearchClient(
        provider="tavily",
        api_key="tvly-...",
        max_results=5,
    )
    await client.open()

    results = await client.search("python async patterns")
    page = await client.fetch_page("https://example.com")

    await client.close()
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_TAVILY_SEARCH_URL = "https://api.tavily.com/search"
_TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"

_SUPPORTED_PROVIDERS = frozenset({"tavily", "bing", "searxng"})


@dataclass(frozen=True)
class SearchResult:
    """A single search result returned by any provider.

    Attributes:
        title: Page title.
        url: Source URL.
        content: Extracted text snippet or summary.
        score: Relevance score (0.0–1.0).  ``None`` when the provider
            does not supply one.
    """

    title: str
    url: str
    content: str
    score: float | None = None


@dataclass(frozen=True)
class SearchResponse:
    """Aggregated response from a search query.

    Attributes:
        query: The original query string.
        results: Ordered list of results (most relevant first).
        answer: An optional synthesised answer from the provider
            (Tavily's ``include_answer`` feature).
    """

    query: str
    results: list[SearchResult]
    answer: str | None = None


@dataclass(frozen=True)
class PageContent:
    """Extracted content from a fetched web page.

    Attributes:
        url: The requested URL.
        raw_content: Full extracted text (may be long).
        content: A shorter, cleaned excerpt when available; falls back
            to *raw_content*.
    """

    url: str
    raw_content: str
    content: str


@dataclass
class WebSearchClient:
    """Async HTTP client that delegates to a configured search provider.

    Args:
        provider: Backend identifier (``"tavily"``, ``"bing"``, or
            ``"searxng"``).
        api_key: Provider API key.
        max_results: Default number of results to return per query.
        timeout: HTTP request timeout in seconds.
    """

    provider: str = "tavily"
    api_key: str = ""
    max_results: int = 5
    timeout: float = 30.0
    _http: httpx.AsyncClient = field(default=None, init=False, repr=False)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.provider not in _SUPPORTED_PROVIDERS:
            raise ValueError(
                f"Unsupported search provider '{self.provider}'. "
                f"Choose from: {sorted(_SUPPORTED_PROVIDERS)}"
            )

    async def open(self) -> None:
        """Create the underlying ``httpx.AsyncClient``."""
        self._http = httpx.AsyncClient(timeout=self.timeout)

    async def close(self) -> None:
        """Close the HTTP client and release resources."""
        if self._http is not None:
            await self._http.aclose()
            self._http = None  # type: ignore[assignment]

    async def search(
        self,
        query: str,
        *,
        max_results: int | None = None,
        search_depth: str = "basic",
        topic: str = "general",
    ) -> SearchResponse:
        """Execute a search query against the configured provider.

        Args:
            query: The search query string.
            max_results: Override the default result count.
            search_depth: ``"basic"`` (fast) or ``"advanced"``
                (slower, more thorough).  Tavily-specific; ignored by
                other providers.
            topic: ``"general"`` or ``"news"``.

        Returns:
            A :class:`SearchResponse` with ordered results.

        Raises:
            httpx.HTTPStatusError: On non-2xx responses.
            RuntimeError: If the client has not been opened.
        """
        self._ensure_open()
        effective_max = max_results if max_results is not None else self.max_results

        if self.provider == "tavily":
            return await self._tavily_search(
                query,
                max_results=effective_max,
                search_depth=search_depth,
                topic=topic,
            )

        raise NotImplementedError(
            f"Provider '{self.provider}' search is not yet implemented."
        )

    async def fetch_page(self, url: str) -> PageContent:
        """Fetch and extract readable content from a web page.

        Args:
            url: The page URL to fetch.

        Returns:
            A :class:`PageContent` with extracted text.

        Raises:
            httpx.HTTPStatusError: On non-2xx responses.
            RuntimeError: If the client has not been opened.
        """
        self._ensure_open()

        if self.provider == "tavily":
            return await self._tavily_extract(url)

        raise NotImplementedError(
            f"Provider '{self.provider}' page extraction is not yet "
            f"implemented."
        )

    async def verify_credentials(self) -> bool:
        """Verify the API key by running a lightweight test query.

        Returns:
            ``True`` if the provider accepts the credentials.
        """
        try:
            self._ensure_open()
            await self.search("test", max_results=1)
            return True
        except Exception:
            logger.warning("Web search credential verification failed.", exc_info=True)
            return False

    # ------------------------------------------------------------------
    # Tavily implementation
    # ------------------------------------------------------------------

    async def _tavily_search(
        self,
        query: str,
        *,
        max_results: int,
        search_depth: str,
        topic: str,
    ) -> SearchResponse:
        payload: dict[str, Any] = {
            "query": query,
            "max_results": max_results,
            "search_depth": search_depth,
            "topic": topic,
            "include_answer": True,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        resp = await self._http.post(
            _TAVILY_SEARCH_URL, json=payload, headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()

        results = [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                content=r.get("content", ""),
                score=r.get("score"),
            )
            for r in data.get("results", [])
        ]
        return SearchResponse(
            query=query,
            results=results,
            answer=data.get("answer"),
        )

    async def _tavily_extract(self, url: str) -> PageContent:
        payload: dict[str, Any] = {
            "urls": [url],
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        resp = await self._http.post(
            _TAVILY_EXTRACT_URL, json=payload, headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()

        pages = data.get("results", [])
        if not pages:
            return PageContent(url=url, raw_content="", content="No content extracted.")

        page = pages[0]
        raw = page.get("raw_content", "")
        content = page.get("content", raw) or raw
        return PageContent(url=url, raw_content=raw, content=content)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_open(self) -> None:
        if self._http is None:
            raise RuntimeError(
                "WebSearchClient is not open. Call `await client.open()` "
                "first, or use WebSearchModule.initialize()."
            )


# ---------------------------------------------------------------------------
# Module-level accessor for tool functions
# ---------------------------------------------------------------------------

_active_client: WebSearchClient | None = None


def set_client(client: WebSearchClient) -> None:
    """Set the module-level client instance (called by WebSearchModule)."""
    global _active_client
    _active_client = client


def get_client() -> WebSearchClient:
    """Return the active :class:`WebSearchClient`.

    Raises:
        RuntimeError: If no client has been set (module not initialised).
    """
    if _active_client is None:
        raise RuntimeError(
            "Web search client is not initialised. Ensure "
            "WebSearchModule.initialize() has been called."
        )
    return _active_client


def clear_client() -> None:
    """Remove the module-level client reference (called on shutdown)."""
    global _active_client
    _active_client = None


def _format_results_as_json(response: SearchResponse) -> str:
    """Serialise a :class:`SearchResponse` to a JSON string for the LLM."""
    payload: dict[str, Any] = {"query": response.query, "results": []}
    if response.answer:
        payload["answer"] = response.answer
    for r in response.results:
        entry: dict[str, Any] = {
            "title": r.title,
            "url": r.url,
            "content": r.content,
        }
        if r.score is not None:
            entry["score"] = round(r.score, 4)
        payload["results"].append(entry)
    return json.dumps(payload, ensure_ascii=False)
