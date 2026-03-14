"""Read-only tool functions for the Notion tool module."""

from __future__ import annotations

import json

from harle.debug import etrace
from harle.tools.notion.client import NotionToolClientError, get_client


async def notion_search(query: str) -> str:
    """Search Notion for pages and databases matching a query.

    Args:
        query: The search text to look for in Notion.

    Returns:
        JSON with a ``results`` array. Each result includes ``id``,
        ``title``, ``object`` (page or database), and ``url``.
    """
    if not query.strip():
        return json.dumps({
            "results": [],
            "error": True,
            "message": "query is required.",
        }, ensure_ascii=False)

    try:
        client = get_client()
        results = await client.search(query.strip())
        etrace.detail(
            "Notion search completed",
            module="notion",
            tool="notion_search",
            query=query.strip(),
            results_count=len(results),
        )
        return json.dumps({"results": results}, ensure_ascii=False)
    except (NotionToolClientError, RuntimeError) as exc:
        etrace.detail(
            "Notion connection error",
            module="notion",
            tool="notion_search",
            error=str(exc),
        )
        return json.dumps({
            "results": [],
            "error": True,
            "message": f"Notion connection error: {exc}",
        }, ensure_ascii=False)


notion_search.permission = "read"  # type: ignore[attr-defined]
notion_search.requires_approval = False  # type: ignore[attr-defined]


async def notion_read_page(page_id: str) -> str:
    """Read a Notion page's full content as Markdown.

    Args:
        page_id: The Notion page ID to read.

    Returns:
        JSON with ``page_id``, ``title``, ``content_markdown``, and
        ``url``.
    """
    if not page_id.strip():
        return json.dumps({
            "page_id": page_id,
            "error": True,
            "message": "page_id is required.",
        }, ensure_ascii=False)

    try:
        client = get_client()
        result = await client.read_page(page_id.strip())
        etrace.detail(
            "Notion page read",
            module="notion",
            tool="notion_read_page",
            page_id=page_id.strip(),
            title=result.get("title", ""),
        )
        return json.dumps(result, ensure_ascii=False)
    except (NotionToolClientError, RuntimeError) as exc:
        etrace.detail(
            "Notion connection error",
            module="notion",
            tool="notion_read_page",
            page_id=page_id.strip(),
            error=str(exc),
        )
        return json.dumps({
            "page_id": page_id.strip(),
            "error": True,
            "message": f"Notion connection error: {exc}",
        }, ensure_ascii=False)


notion_read_page.permission = "read"  # type: ignore[attr-defined]
notion_read_page.requires_approval = False  # type: ignore[attr-defined]


async def notion_get_database(database_id: str) -> str:
    """Get a Notion database's schema (column names and types).

    Use this to understand the structure of a database before querying
    it with ``notion_query_database``.

    Args:
        database_id: The Notion database ID.

    Returns:
        JSON with ``database_id``, ``title``, and ``columns``
        (list of ``{name, type}``).
    """
    if not database_id.strip():
        return json.dumps({
            "database_id": database_id,
            "error": True,
            "message": "database_id is required.",
        }, ensure_ascii=False)

    try:
        client = get_client()
        result = await client.get_database_schema(database_id.strip())
        etrace.detail(
            "Notion database schema retrieved",
            module="notion",
            tool="notion_get_database",
            database_id=database_id.strip(),
            columns_count=len(result.get("columns", [])),
        )
        return json.dumps(result, ensure_ascii=False)
    except (NotionToolClientError, RuntimeError) as exc:
        etrace.detail(
            "Notion connection error",
            module="notion",
            tool="notion_get_database",
            database_id=database_id.strip(),
            error=str(exc),
        )
        return json.dumps({
            "database_id": database_id.strip(),
            "error": True,
            "message": f"Notion connection error: {exc}",
        }, ensure_ascii=False)


notion_get_database.permission = "read"  # type: ignore[attr-defined]
notion_get_database.requires_approval = False  # type: ignore[attr-defined]


async def notion_query_database(
    database_id: str,
    filter_json: str = "",
    max_rows: str = "50",
) -> str:
    """Query a Notion database with optional filter.

    Args:
        database_id: The Notion database ID to query.
        filter_json: Optional JSON string with a Notion filter object.
            Example: ``{"property": "Status", "select": {"equals": "Done"}}``
        max_rows: Maximum number of rows to return (default ``"50"``).

    Returns:
        JSON with ``database_id``, ``title``, ``columns``, ``rows``
        (each with ``page_id`` and ``properties``), ``total_rows``,
        and ``truncated`` (true when more rows exist).
    """
    if not database_id.strip():
        return json.dumps({
            "database_id": database_id,
            "error": True,
            "message": "database_id is required.",
        }, ensure_ascii=False)

    filter_obj = None
    if filter_json.strip():
        try:
            filter_obj = json.loads(filter_json)
        except json.JSONDecodeError as exc:
            return json.dumps({
                "database_id": database_id.strip(),
                "error": True,
                "message": f"Invalid filter_json: {exc}",
            }, ensure_ascii=False)

    try:
        row_limit = int(max_rows)
    except ValueError:
        row_limit = 50

    try:
        client = get_client()
        result = await client.query_database(
            database_id.strip(),
            filter_obj=filter_obj,
            max_rows=row_limit,
        )
        etrace.detail(
            "Notion database queried",
            module="notion",
            tool="notion_query_database",
            database_id=database_id.strip(),
            rows_returned=result.get("total_rows", 0),
            truncated=result.get("truncated", False),
        )
        return json.dumps(result, ensure_ascii=False)
    except (NotionToolClientError, RuntimeError) as exc:
        etrace.detail(
            "Notion connection error",
            module="notion",
            tool="notion_query_database",
            database_id=database_id.strip(),
            error=str(exc),
        )
        return json.dumps({
            "database_id": database_id.strip(),
            "error": True,
            "message": f"Notion connection error: {exc}",
        }, ensure_ascii=False)


notion_query_database.permission = "read"  # type: ignore[attr-defined]
notion_query_database.requires_approval = False  # type: ignore[attr-defined]
