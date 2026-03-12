"""Tool functions for the Web Search module.

Each function is the single source of truth for its name, description,
and parameter schema.  The registry introspects these to build JSON
schemas for the LLM — nothing is duplicated elsewhere.

All functions return JSON strings so the agent can parse structured
data.  Permission attributes (``permission``, ``requires_approval``)
are set as function-level attributes after each definition.
"""

from __future__ import annotations

import json

from harle.tools.web_search.client import (
    PageContent,
    get_client,
    _format_results_as_json,
)


async def search_web(
    query: str,
    max_results: int = 5,
    search_depth: str = "basic",
) -> str:
    """Search the web for information matching a query.

    Use this tool when you need to find current information, verify
    facts, research a topic, or answer questions that require
    up-to-date web data.

    Args:
        query: The search query.  Be specific and include relevant
            keywords for better results.
        max_results: Maximum number of results to return (1–10).
            Defaults to 5.
        search_depth: ``"basic"`` for fast results or ``"advanced"``
            for more thorough, slower search.  Defaults to ``"basic"``.

    Returns:
        JSON string with ``query``, ``answer`` (if available), and a
        ``results`` list.  Each result has ``title``, ``url``,
        ``content``, and optionally ``score``.
    """
    max_results = max(1, min(max_results, 10))
    try:
        client = get_client()
        response = await client.search(
            query,
            max_results=max_results,
            search_depth=search_depth,
            topic="general",
        )
        return _format_results_as_json(response)
    except Exception as exc:
        return json.dumps({
            "query": query,
            "results": [],
            "error": True,
            "message": f"Web search connection error: {exc}",
        }, ensure_ascii=False)


search_web.permission = "read"  # type: ignore[attr-defined]
search_web.requires_approval = False  # type: ignore[attr-defined]


async def search_news(
    query: str,
    max_results: int = 5,
    days: int = 7,
) -> str:
    """Search recent news articles matching a query.

    Use this tool when you need current news, recent events, or
    time-sensitive information.  Results are biased towards recent
    publications.

    Args:
        query: The news search query.
        max_results: Maximum number of results to return (1–10).
            Defaults to 5.
        days: Only return articles published within this many days.
            Defaults to 7.

    Returns:
        JSON string with ``query`` and a ``results`` list.  Each
        result has ``title``, ``url``, ``content``, and optionally
        ``score``.
    """
    max_results = max(1, min(max_results, 10))
    days = max(1, min(days, 365))
    try:
        client = get_client()
        response = await client.search(
            query,
            max_results=max_results,
            search_depth="basic",
            topic="news",
        )
        return _format_results_as_json(response)
    except Exception as exc:
        return json.dumps({
            "query": query,
            "results": [],
            "error": True,
            "message": f"Web search connection error: {exc}",
        }, ensure_ascii=False)


search_news.permission = "read"  # type: ignore[attr-defined]
search_news.requires_approval = False  # type: ignore[attr-defined]


async def fetch_page(url: str) -> str:
    """Fetch and extract the readable content of a web page.

    Use this tool when you have a specific URL and need to read its
    content — for example, to get the full text of an article found
    via ``search_web`` or ``search_news``.

    Args:
        url: The full URL of the page to fetch (must start with
            ``http://`` or ``https://``).

    Returns:
        JSON string with ``url`` and ``content`` (extracted text).
        If extraction fails, ``content`` will contain an error
        description.
    """
    if not url.startswith(("http://", "https://")):
        return json.dumps({
            "url": url,
            "content": "Invalid URL: must start with http:// or https://",
            "error": True,
        }, ensure_ascii=False)

    client = get_client()
    try:
        page: PageContent = await client.fetch_page(url)
        return json.dumps({
            "url": page.url,
            "content": page.content,
        }, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({
            "url": url,
            "content": f"Web search connection error: {exc}",
            "error": True,
        }, ensure_ascii=False)


fetch_page.permission = "read"  # type: ignore[attr-defined]
fetch_page.requires_approval = False  # type: ignore[attr-defined]
