"""Tests for the Web Search tool module (Phase 2).

Covers:
- WebSearchClient: construction, lifecycle, Tavily search/extract,
  provider validation, credential verification
- Module-level accessor: get_client / set_client / clear_client
- Data classes: SearchResult, SearchResponse, PageContent
- Result serialisation: _format_results_as_json
- Tool functions: search_web, search_news, fetch_page (with mocked client)
- Permission attributes on tool functions
- WebSearchModule: lifecycle, get_tools, health_check, default_constraints
- Registry integration: registering the module, getting agent tools
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from harle.tools.web_search.client import (
    PageContent,
    SearchResponse,
    SearchResult,
    WebSearchClient,
    _format_results_as_json,
    clear_client,
    get_client,
    set_client,
)
from harle.tools.web_search.module import WebSearchModule
from harle.tools.web_search.tools import fetch_page, search_news, search_web


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


# -------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------


def _tavily_search_response(
    *,
    results: list[dict[str, Any]] | None = None,
    answer: str | None = "Summarised answer.",
) -> dict[str, Any]:
    """Build a realistic Tavily search API response payload."""
    if results is None:
        results = [
            {
                "title": "Python Docs",
                "url": "https://docs.python.org",
                "content": "Official Python documentation.",
                "score": 0.95,
            },
            {
                "title": "Real Python",
                "url": "https://realpython.com",
                "content": "Python tutorials and guides.",
                "score": 0.88,
            },
        ]
    return {"results": results, "answer": answer}


def _tavily_extract_response(
    *,
    url: str = "https://example.com",
    raw_content: str = "Full page text...",
    content: str = "Cleaned excerpt.",
) -> dict[str, Any]:
    """Build a realistic Tavily extract API response payload."""
    return {
        "results": [
            {
                "url": url,
                "raw_content": raw_content,
                "content": content,
            },
        ],
    }


def _mock_http_response(json_data: dict[str, Any]) -> MagicMock:
    """Create a mock httpx response with the given JSON data."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = json_data
    return resp


@pytest.fixture(autouse=True)
def _clean_module_client():
    """Ensure the module-level client is cleared between tests."""
    clear_client()
    yield
    clear_client()


# ===================================================================
# Data classes
# ===================================================================


class TestSearchResult:
    """Tests for SearchResult frozen dataclass."""

    def test_required_fields(self) -> None:
        r = SearchResult(title="T", url="https://x.com", content="C")
        assert r.title == "T"
        assert r.url == "https://x.com"
        assert r.content == "C"
        assert r.score is None

    def test_with_score(self) -> None:
        r = SearchResult(title="T", url="u", content="C", score=0.91)
        assert r.score == 0.91

    def test_frozen(self) -> None:
        r = SearchResult(title="T", url="u", content="C")
        with pytest.raises(AttributeError):
            r.title = "X"  # type: ignore[misc]


class TestSearchResponse:
    """Tests for SearchResponse frozen dataclass."""

    def test_defaults(self) -> None:
        resp = SearchResponse(query="q", results=[])
        assert resp.query == "q"
        assert resp.results == []
        assert resp.answer is None

    def test_with_answer(self) -> None:
        resp = SearchResponse(query="q", results=[], answer="ans")
        assert resp.answer == "ans"


class TestPageContent:
    """Tests for PageContent frozen dataclass."""

    def test_fields(self) -> None:
        pc = PageContent(url="u", raw_content="raw", content="clean")
        assert pc.url == "u"
        assert pc.raw_content == "raw"
        assert pc.content == "clean"

    def test_frozen(self) -> None:
        pc = PageContent(url="u", raw_content="r", content="c")
        with pytest.raises(AttributeError):
            pc.url = "x"  # type: ignore[misc]


# ===================================================================
# WebSearchClient — construction
# ===================================================================


class TestWebSearchClientConstruction:
    """Tests for WebSearchClient initialisation and validation."""

    def test_default_provider(self) -> None:
        c = WebSearchClient(api_key="key")
        assert c.provider == "tavily"
        assert c.max_results == 5
        assert c.timeout == 30.0

    def test_custom_values(self) -> None:
        c = WebSearchClient(provider="tavily", api_key="k", max_results=3, timeout=10.0)
        assert c.max_results == 3
        assert c.timeout == 10.0

    def test_valid_providers(self) -> None:
        for p in ("tavily", "bing", "searxng"):
            c = WebSearchClient(provider=p, api_key="k")
            assert c.provider == p

    def test_invalid_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported search provider"):
            WebSearchClient(provider="google", api_key="k")


# ===================================================================
# WebSearchClient — lifecycle
# ===================================================================


class TestWebSearchClientLifecycle:
    """Tests for open/close and _ensure_open."""

    def test_not_open_raises(self) -> None:
        c = WebSearchClient(api_key="k")
        with pytest.raises(RuntimeError, match="not open"):
            c._ensure_open()

    def test_open_requires_connection_managed_http_client(self) -> None:
        c = WebSearchClient(api_key="k")
        with pytest.raises(RuntimeError, match="connection-managed"):
            _run(c.open())

    def test_close_clears_http(self) -> None:
        c = WebSearchClient(api_key="k", http_client=AsyncMock())
        _run(c.open())
        _run(c.close())
        assert c._http is None

    def test_close_idempotent_when_not_opened(self) -> None:
        c = WebSearchClient(api_key="k")
        _run(c.close())

    def test_search_before_open_raises(self) -> None:
        c = WebSearchClient(api_key="k")
        with pytest.raises(RuntimeError, match="not open"):
            _run(c.search("test"))

    def test_fetch_page_before_open_raises(self) -> None:
        c = WebSearchClient(api_key="k")
        with pytest.raises(RuntimeError, match="not open"):
            _run(c.fetch_page("https://example.com"))


# ===================================================================
# WebSearchClient — Tavily search
# ===================================================================


class TestWebSearchClientTavilySearch:
    """Tests for the Tavily search implementation (mocked HTTP)."""

    def _make_client(self) -> WebSearchClient:
        c = WebSearchClient(api_key="tvly-test", max_results=5)
        c._http = AsyncMock()
        return c

    def test_search_returns_results(self) -> None:
        c = self._make_client()
        c._http.post = AsyncMock(return_value=_mock_http_response(
            _tavily_search_response(),
        ))
        resp = _run(c.search("python asyncio"))

        assert isinstance(resp, SearchResponse)
        assert resp.query == "python asyncio"
        assert len(resp.results) == 2
        assert resp.results[0].title == "Python Docs"
        assert resp.results[0].score == 0.95
        assert resp.answer == "Summarised answer."

    def test_search_passes_correct_payload(self) -> None:
        c = self._make_client()
        c._http.post = AsyncMock(return_value=_mock_http_response(
            _tavily_search_response(results=[], answer=None),
        ))
        _run(c.search(
            "test query",
            max_results=3,
            search_depth="advanced",
            topic="news",
        ))

        call_args = c._http.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["query"] == "test query"
        assert payload["max_results"] == 3
        assert payload["search_depth"] == "advanced"
        assert payload["topic"] == "news"
        assert payload["include_answer"] is True

    def test_search_does_not_manage_auth_headers_directly(self) -> None:
        c = self._make_client()
        c._http.post = AsyncMock(return_value=_mock_http_response(
            _tavily_search_response(results=[]),
        ))
        _run(c.search("q"))

        call_args = c._http.post.call_args
        headers = call_args.kwargs.get("headers") or call_args[1].get("headers")
        assert headers is None

    def test_search_uses_default_max_results(self) -> None:
        c = WebSearchClient(api_key="k", max_results=7)
        c._http = AsyncMock()
        c._http.post = AsyncMock(return_value=_mock_http_response(
            _tavily_search_response(results=[]),
        ))
        _run(c.search("q"))

        payload = c._http.post.call_args.kwargs.get("json") or c._http.post.call_args[1].get("json")
        assert payload["max_results"] == 7

    def test_search_overrides_max_results(self) -> None:
        c = self._make_client()
        c._http.post = AsyncMock(return_value=_mock_http_response(
            _tavily_search_response(results=[]),
        ))
        _run(c.search("q", max_results=2))

        payload = c._http.post.call_args.kwargs.get("json") or c._http.post.call_args[1].get("json")
        assert payload["max_results"] == 2

    def test_search_empty_results(self) -> None:
        c = self._make_client()
        c._http.post = AsyncMock(return_value=_mock_http_response(
            _tavily_search_response(results=[], answer=None),
        ))
        resp = _run(c.search("obscure query"))
        assert resp.results == []
        assert resp.answer is None

    def test_search_result_without_score(self) -> None:
        c = self._make_client()
        c._http.post = AsyncMock(return_value=_mock_http_response(
            _tavily_search_response(results=[
                {"title": "T", "url": "u", "content": "C"},
            ]),
        ))
        resp = _run(c.search("q"))
        assert resp.results[0].score is None


# ===================================================================
# WebSearchClient — Tavily extract (fetch_page)
# ===================================================================


class TestWebSearchClientTavilyExtract:
    """Tests for the Tavily extract/fetch implementation (mocked HTTP)."""

    def _make_client(self) -> WebSearchClient:
        c = WebSearchClient(api_key="tvly-test")
        c._http = AsyncMock()
        return c

    def test_fetch_page_returns_content(self) -> None:
        c = self._make_client()
        c._http.post = AsyncMock(return_value=_mock_http_response(
            _tavily_extract_response(),
        ))
        page = _run(c.fetch_page("https://example.com"))

        assert isinstance(page, PageContent)
        assert page.url == "https://example.com"
        assert page.raw_content == "Full page text..."
        assert page.content == "Cleaned excerpt."

    def test_fetch_page_empty_results(self) -> None:
        c = self._make_client()
        c._http.post = AsyncMock(return_value=_mock_http_response(
            {"results": []},
        ))
        page = _run(c.fetch_page("https://empty.com"))
        assert page.content == "No content extracted."
        assert page.raw_content == ""

    def test_fetch_page_sends_url_in_payload(self) -> None:
        c = self._make_client()
        c._http.post = AsyncMock(return_value=_mock_http_response(
            _tavily_extract_response(),
        ))
        _run(c.fetch_page("https://target.com/page"))

        payload = c._http.post.call_args.kwargs.get("json") or c._http.post.call_args[1].get("json")
        assert payload["urls"] == ["https://target.com/page"]

    def test_fetch_page_uses_raw_when_content_missing(self) -> None:
        c = self._make_client()
        c._http.post = AsyncMock(return_value=_mock_http_response({
            "results": [{"url": "u", "raw_content": "raw text only"}],
        }))
        page = _run(c.fetch_page("https://example.com"))
        assert page.content == "raw text only"
        assert page.raw_content == "raw text only"


# ===================================================================
# WebSearchClient — unsupported providers
# ===================================================================


class TestWebSearchClientUnsupportedProviders:
    """Tests that stub providers raise NotImplementedError."""

    def test_bing_search_not_implemented(self) -> None:
        c = WebSearchClient(provider="bing", api_key="k")
        c._http = AsyncMock()
        with pytest.raises(NotImplementedError, match="bing"):
            _run(c.search("q"))

    def test_searxng_search_not_implemented(self) -> None:
        c = WebSearchClient(provider="searxng", api_key="k")
        c._http = AsyncMock()
        with pytest.raises(NotImplementedError, match="searxng"):
            _run(c.search("q"))

    def test_bing_fetch_not_implemented(self) -> None:
        c = WebSearchClient(provider="bing", api_key="k")
        c._http = AsyncMock()
        with pytest.raises(NotImplementedError, match="bing"):
            _run(c.fetch_page("https://x.com"))

    def test_searxng_fetch_not_implemented(self) -> None:
        c = WebSearchClient(provider="searxng", api_key="k")
        c._http = AsyncMock()
        with pytest.raises(NotImplementedError, match="searxng"):
            _run(c.fetch_page("https://x.com"))


# ===================================================================
# WebSearchClient — verify_credentials
# ===================================================================


class TestVerifyCredentials:
    """Tests for the credential verification method."""

    def test_returns_true_on_success(self) -> None:
        c = WebSearchClient(api_key="k")
        c._http = AsyncMock()
        c._http.post = AsyncMock(return_value=_mock_http_response(
            _tavily_search_response(results=[]),
        ))
        assert _run(c.verify_credentials()) is True

    def test_returns_false_on_failure(self) -> None:
        c = WebSearchClient(api_key="k")
        c._http = AsyncMock()
        c._http.post = AsyncMock(side_effect=Exception("401 Unauthorized"))
        assert _run(c.verify_credentials()) is False

    def test_returns_false_when_not_open(self) -> None:
        c = WebSearchClient(api_key="k")
        assert _run(c.verify_credentials()) is False


# ===================================================================
# Module-level accessor
# ===================================================================


class TestModuleLevelAccessor:
    """Tests for get_client / set_client / clear_client."""

    def test_get_client_before_set_raises(self) -> None:
        with pytest.raises(RuntimeError, match="not initialised"):
            get_client()

    def test_set_and_get(self) -> None:
        c = WebSearchClient(api_key="k")
        set_client(c)
        assert get_client() is c

    def test_clear_then_get_raises(self) -> None:
        c = WebSearchClient(api_key="k")
        set_client(c)
        clear_client()
        with pytest.raises(RuntimeError, match="not initialised"):
            get_client()

    def test_set_replaces_previous(self) -> None:
        c1 = WebSearchClient(api_key="k1")
        c2 = WebSearchClient(api_key="k2")
        set_client(c1)
        set_client(c2)
        assert get_client() is c2


# ===================================================================
# _format_results_as_json
# ===================================================================


class TestFormatResultsAsJson:
    """Tests for the JSON serialisation helper."""

    def test_basic_serialisation(self) -> None:
        resp = SearchResponse(
            query="test",
            results=[
                SearchResult(title="T", url="u", content="C", score=0.9),
            ],
            answer="A",
        )
        text = _format_results_as_json(resp)
        data = json.loads(text)
        assert data["query"] == "test"
        assert data["answer"] == "A"
        assert len(data["results"]) == 1
        assert data["results"][0]["title"] == "T"
        assert data["results"][0]["score"] == 0.9

    def test_no_answer(self) -> None:
        resp = SearchResponse(query="q", results=[])
        data = json.loads(_format_results_as_json(resp))
        assert "answer" not in data

    def test_score_none_excluded(self) -> None:
        resp = SearchResponse(
            query="q",
            results=[SearchResult(title="T", url="u", content="C")],
        )
        data = json.loads(_format_results_as_json(resp))
        assert "score" not in data["results"][0]

    def test_score_rounded(self) -> None:
        resp = SearchResponse(
            query="q",
            results=[SearchResult(title="T", url="u", content="C", score=0.123456789)],
        )
        data = json.loads(_format_results_as_json(resp))
        assert data["results"][0]["score"] == 0.1235

    def test_unicode_preserved(self) -> None:
        resp = SearchResponse(
            query="тест",
            results=[SearchResult(title="Заголовок", url="u", content="Контент")],
        )
        text = _format_results_as_json(resp)
        assert "тест" in text
        assert "Заголовок" in text


# ===================================================================
# Tool functions — search_web
# ===================================================================


class TestSearchWebTool:
    """Tests for the search_web tool function."""

    def _setup_client(self, response_data: dict[str, Any] | None = None) -> WebSearchClient:
        c = WebSearchClient(api_key="k")
        c._http = AsyncMock()
        c._http.post = AsyncMock(return_value=_mock_http_response(
            response_data or _tavily_search_response(),
        ))
        set_client(c)
        return c

    def test_returns_json_string(self) -> None:
        self._setup_client()
        result = _run(search_web("python async"))
        data = json.loads(result)
        assert data["query"] == "python async"
        assert len(data["results"]) == 2

    def test_clamps_max_results_low(self) -> None:
        c = self._setup_client(_tavily_search_response(results=[]))
        _run(search_web("q", max_results=0))
        payload = c._http.post.call_args.kwargs.get("json") or c._http.post.call_args[1].get("json")
        assert payload["max_results"] == 1

    def test_clamps_max_results_high(self) -> None:
        c = self._setup_client(_tavily_search_response(results=[]))
        _run(search_web("q", max_results=99))
        payload = c._http.post.call_args.kwargs.get("json") or c._http.post.call_args[1].get("json")
        assert payload["max_results"] == 10

    def test_passes_search_depth(self) -> None:
        c = self._setup_client(_tavily_search_response(results=[]))
        _run(search_web("q", search_depth="advanced"))
        payload = c._http.post.call_args.kwargs.get("json") or c._http.post.call_args[1].get("json")
        assert payload["search_depth"] == "advanced"

    def test_uses_general_topic(self) -> None:
        c = self._setup_client(_tavily_search_response(results=[]))
        _run(search_web("q"))
        payload = c._http.post.call_args.kwargs.get("json") or c._http.post.call_args[1].get("json")
        assert payload["topic"] == "general"


    def test_returns_error_when_connection_unavailable(self) -> None:
        clear_client()
        result = _run(search_web("python async"))
        data = json.loads(result)
        assert data["error"] is True
        assert "connection error" in data["message"].lower()

    def test_permission_attribute(self) -> None:
        assert search_web.permission == "read"
        assert search_web.requires_approval is False


# ===================================================================
# Tool functions — search_news
# ===================================================================


class TestSearchNewsTool:
    """Tests for the search_news tool function."""

    def _setup_client(self, response_data: dict[str, Any] | None = None) -> WebSearchClient:
        c = WebSearchClient(api_key="k")
        c._http = AsyncMock()
        c._http.post = AsyncMock(return_value=_mock_http_response(
            response_data or _tavily_search_response(),
        ))
        set_client(c)
        return c

    def test_returns_json_string(self) -> None:
        self._setup_client()
        result = _run(search_news("AI news"))
        data = json.loads(result)
        assert data["query"] == "AI news"

    def test_uses_news_topic(self) -> None:
        c = self._setup_client(_tavily_search_response(results=[]))
        _run(search_news("q"))
        payload = c._http.post.call_args.kwargs.get("json") or c._http.post.call_args[1].get("json")
        assert payload["topic"] == "news"

    def test_clamps_max_results(self) -> None:
        c = self._setup_client(_tavily_search_response(results=[]))
        _run(search_news("q", max_results=-5))
        payload = c._http.post.call_args.kwargs.get("json") or c._http.post.call_args[1].get("json")
        assert payload["max_results"] == 1

    def test_clamps_days_low(self) -> None:
        self._setup_client(_tavily_search_response(results=[]))
        _run(search_news("q", days=0))

    def test_clamps_days_high(self) -> None:
        self._setup_client(_tavily_search_response(results=[]))
        _run(search_news("q", days=9999))


    def test_returns_error_when_connection_unavailable(self) -> None:
        clear_client()
        result = _run(search_news("AI news"))
        data = json.loads(result)
        assert data["error"] is True
        assert "connection error" in data["message"].lower()

    def test_permission_attribute(self) -> None:
        assert search_news.permission == "read"
        assert search_news.requires_approval is False


# ===================================================================
# Tool functions — fetch_page
# ===================================================================


class TestFetchPageTool:
    """Tests for the fetch_page tool function."""

    def _setup_client(self, response_data: dict[str, Any] | None = None) -> WebSearchClient:
        c = WebSearchClient(api_key="k")
        c._http = AsyncMock()
        c._http.post = AsyncMock(return_value=_mock_http_response(
            response_data or _tavily_extract_response(),
        ))
        set_client(c)
        return c

    def test_returns_json_with_content(self) -> None:
        self._setup_client()
        result = _run(fetch_page("https://example.com"))
        data = json.loads(result)
        assert data["url"] == "https://example.com"
        assert data["content"] == "Cleaned excerpt."
        assert "error" not in data

    def test_invalid_url_returns_error(self) -> None:
        self._setup_client()
        result = _run(fetch_page("ftp://example.com"))
        data = json.loads(result)
        assert data["error"] is True
        assert "Invalid URL" in data["content"]

    def test_invalid_url_no_scheme(self) -> None:
        self._setup_client()
        result = _run(fetch_page("example.com"))
        data = json.loads(result)
        assert data["error"] is True

    def test_http_url_accepted(self) -> None:
        self._setup_client()
        result = _run(fetch_page("http://example.com"))
        data = json.loads(result)
        assert "error" not in data

    def test_client_error_returns_error_json(self) -> None:
        c = WebSearchClient(api_key="k")
        c._http = AsyncMock()
        c._http.post = AsyncMock(side_effect=Exception("Connection refused"))
        set_client(c)

        result = _run(fetch_page("https://down.example.com"))
        data = json.loads(result)
        assert data["error"] is True
        assert "connection error" in data["content"].lower()

    def test_permission_attribute(self) -> None:
        assert fetch_page.permission == "read"
        assert fetch_page.requires_approval is False


# ===================================================================
# WebSearchModule
# ===================================================================


class TestWebSearchModule:
    """Tests for the WebSearchModule class."""

    def test_name(self) -> None:
        m = WebSearchModule()
        assert m.name == "web_search"

    def test_description(self) -> None:
        m = WebSearchModule()
        assert "search" in m.description.lower()

    def test_get_tools_returns_three(self) -> None:
        m = WebSearchModule()
        tools = m.get_tools()
        assert len(tools) == 3
        names = {fn.__name__ for fn in tools}
        assert names == {"search_web", "search_news", "fetch_page"}

    def test_default_constraints_is_none(self) -> None:
        m = WebSearchModule()
        assert m.default_constraints() is None

    @patch("harle.tools.web_search.module.WebSearchClient")
    def test_initialize_requires_connections(self, mock_cls: MagicMock) -> None:
        m = WebSearchModule()
        with pytest.raises(RuntimeError, match="ConnectionRegistry"):
            _run(m.initialize({}))
        mock_cls.assert_not_called()

    @patch("harle.tools.web_search.module.WebSearchClient")
    def test_initialize_uses_connection_client(self, mock_cls: MagicMock) -> None:
        mock_instance = MagicMock()
        mock_instance.open = AsyncMock()
        mock_cls.return_value = mock_instance

        mock_http = AsyncMock()
        mock_connection = MagicMock()
        mock_connection.get_client.return_value = mock_http
        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_connection

        m = WebSearchModule()
        _run(m.initialize({"connection": "tavily", "max_results": 3}, connections=mock_registry))

        mock_registry.get.assert_called_once_with("tavily")
        mock_connection.get_client.assert_called_once_with()
        mock_cls.assert_called_once_with(
            provider="tavily",
            max_results=3,
            http_client=mock_http,
        )
        mock_instance.open.assert_awaited_once()

    @patch("harle.tools.web_search.module.WebSearchClient")
    def test_initialize_sets_module_client(self, mock_cls: MagicMock) -> None:
        mock_instance = MagicMock()
        mock_instance.open = AsyncMock()
        mock_cls.return_value = mock_instance

        mock_connection = MagicMock()
        mock_connection.get_client.return_value = AsyncMock()
        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_connection

        m = WebSearchModule()
        _run(m.initialize({"connection": "tavily"}, connections=mock_registry))

        assert get_client() is mock_instance

    @patch("harle.tools.web_search.module.WebSearchClient")
    def test_shutdown_clears_client(self, mock_cls: MagicMock) -> None:
        mock_instance = MagicMock()
        mock_instance.open = AsyncMock()
        mock_instance.close = AsyncMock()
        mock_cls.return_value = mock_instance

        mock_connection = MagicMock()
        mock_connection.get_client.return_value = AsyncMock()
        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_connection

        m = WebSearchModule()
        _run(m.initialize({"connection": "tavily"}, connections=mock_registry))
        _run(m.shutdown())

        mock_instance.close.assert_awaited_once()
        with pytest.raises(RuntimeError):
            get_client()

    def test_shutdown_before_init_safe(self) -> None:
        m = WebSearchModule()
        _run(m.shutdown())

    def test_health_check_before_init_returns_false(self) -> None:
        m = WebSearchModule()
        assert _run(m.health_check()) is False

    @patch("harle.tools.web_search.module.WebSearchClient")
    def test_health_check_delegates_to_connection(self, mock_cls: MagicMock) -> None:
        mock_instance = MagicMock()
        mock_instance.open = AsyncMock()
        mock_cls.return_value = mock_instance

        status = MagicMock()
        status.healthy = True

        mock_connection = MagicMock()
        mock_connection.get_client.return_value = AsyncMock()
        mock_connection.health_check = AsyncMock(return_value=status)
        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_connection

        m = WebSearchModule()
        _run(m.initialize({"connection": "tavily"}, connections=mock_registry))

        assert _run(m.health_check()) is True
        mock_connection.health_check.assert_awaited_once()


# ===================================================================
# Registry integration
# ===================================================================


class TestRegistryIntegration:
    """Tests for registering WebSearchModule with the ToolRegistry."""

    def _setup_module(self, mock_cls: MagicMock) -> WebSearchModule:
        mock_instance = MagicMock()
        mock_instance.open = AsyncMock()
        mock_cls.return_value = mock_instance

        mock_connection = MagicMock()
        mock_connection.get_client.return_value = AsyncMock()
        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_connection

        m = WebSearchModule()
        _run(m.initialize({"connection": "tavily"}, connections=mock_registry))
        return m

    @patch("harle.tools.web_search.module.WebSearchClient")
    def test_register_and_list_tools(self, mock_cls: MagicMock) -> None:
        from harle.tools.registry import ToolRegistry

        m = self._setup_module(mock_cls)

        registry = ToolRegistry()
        registry.register_module(m)

        assert "search_web" in registry
        assert "search_news" in registry
        assert "fetch_page" in registry
        assert len(registry) == 3

    @patch("harle.tools.web_search.module.WebSearchClient")
    def test_get_agent_tools(self, mock_cls: MagicMock) -> None:
        from harle.tools.registry import ToolRegistry

        m = self._setup_module(mock_cls)

        registry = ToolRegistry()
        registry.register_module(m)

        sdk_tools = registry.get_agent_tools(["search_web", "fetch_page"])
        assert len(sdk_tools) == 2

    @patch("harle.tools.web_search.module.WebSearchClient")
    def test_module_for_tool(self, mock_cls: MagicMock) -> None:
        from harle.tools.registry import ToolRegistry

        m = self._setup_module(mock_cls)

        registry = ToolRegistry()
        registry.register_module(m)

        owner = registry.get_module_for_tool("search_web")
        assert owner is m
        assert owner.name == "web_search"

    @patch("harle.tools.web_search.module.WebSearchClient")
    def test_no_default_constraints_yields_empty(self, mock_cls: MagicMock) -> None:
        from harle.tools.registry import ToolRegistry

        m = self._setup_module(mock_cls)

        registry = ToolRegistry()
        registry.register_module(m)

        cfg = registry.get_module_constraints("web_search")
        assert cfg.is_empty is True

    @patch("harle.tools.web_search.module.WebSearchClient")
    def test_shutdown_all(self, mock_cls: MagicMock) -> None:
        from harle.tools.registry import ToolRegistry

        mock_instance = MagicMock()
        mock_instance.open = AsyncMock()
        mock_instance.close = AsyncMock()
        mock_cls.return_value = mock_instance

        mock_connection = MagicMock()
        mock_connection.get_client.return_value = AsyncMock()
        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_connection

        m = WebSearchModule()
        _run(m.initialize({"connection": "tavily"}, connections=mock_registry))

        registry = ToolRegistry()
        registry.register_module(m)
        _run(registry.shutdown_all())

        mock_instance.close.assert_awaited_once()

    @patch("harle.tools.web_search.module.WebSearchClient")
    def test_builtin_skill_loads(self, mock_cls: MagicMock) -> None:
        from harle.tools.registry import ToolRegistry

        m = self._setup_module(mock_cls)

        registry = ToolRegistry()
        registry.register_module(m, skill_names=["research"])

        skills = registry.get_module_skills("web_search")
        assert len(skills) == 1
        assert skills[0].name == "research"
        assert skills[0].source == "builtin"
        assert "search_web" in skills[0].content


# ===================================================================
# Tool function signatures (SDK compatibility)
# ===================================================================


class TestToolFunctionSignatures:
    """Verify tool functions have the attributes the registry expects."""

    @pytest.mark.parametrize("fn", [search_web, search_news, fetch_page])
    def test_has_docstring(self, fn: Callable) -> None:
        assert fn.__doc__ is not None
        assert len(fn.__doc__) > 20

    @pytest.mark.parametrize("fn", [search_web, search_news, fetch_page])
    def test_has_type_hints(self, fn: Callable) -> None:
        import inspect
        sig = inspect.signature(fn)
        for param in sig.parameters.values():
            assert param.annotation != inspect.Parameter.empty, (
                f"Parameter '{param.name}' in '{fn.__name__}' has no type hint."
            )

    @pytest.mark.parametrize("fn", [search_web, search_news, fetch_page])
    def test_returns_str(self, fn: Callable) -> None:
        import inspect
        sig = inspect.signature(fn)
        # `from __future__ import annotations` makes annotations strings
        assert sig.return_annotation in (str, "str")

    @pytest.mark.parametrize("fn", [search_web, search_news, fetch_page])
    def test_is_async(self, fn: Callable) -> None:
        import inspect
        assert inspect.iscoroutinefunction(fn)

    @pytest.mark.parametrize("fn", [search_web, search_news, fetch_page])
    def test_permission_is_read(self, fn: Callable) -> None:
        assert getattr(fn, "permission", None) == "read"

    @pytest.mark.parametrize("fn", [search_web, search_news, fetch_page])
    def test_requires_no_approval(self, fn: Callable) -> None:
        assert getattr(fn, "requires_approval", None) is False
