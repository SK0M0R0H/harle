"""Tests for harle.search.query_expander."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from harle.search.query_expander import expand
from harle.search.types import ExpandedQuery, SearchQuery


def _config(add_role_terms: bool = True, match_tag_vocabulary: bool = True, use_stemming: bool = True) -> object:
    return SimpleNamespace(
        add_role_terms=add_role_terms,
        match_tag_vocabulary=match_tag_vocabulary,
        use_stemming=use_stemming,
    )


class TestExpand:
    def test_tokenizes_and_lowercases(self) -> None:
        q = SearchQuery(query="Hello World", max_results=5)
        out = expand(q, set(), _config())
        assert isinstance(out, ExpandedQuery)
        assert "hello" in out.whoosh_terms
        assert "world" in out.whoosh_terms
        assert out.raw_query == "Hello World"

    def test_drops_stopwords(self) -> None:
        q = SearchQuery(query="the quick brown fox", max_results=5)
        out = expand(q, set(), _config())
        assert "the" not in out.whoosh_terms
        assert "quick" in out.whoosh_terms
        assert "brown" in out.whoosh_terms
        assert "fox" in out.whoosh_terms

    def test_tag_filters_matched_vocabulary(self) -> None:
        q = SearchQuery(query="trello tasks", max_results=5)
        vocab = {"trello", "task-management", "work"}
        out = expand(q, vocab, _config())
        assert "trello" in out.tag_filters
        assert "tasks" in out.tag_filters
        assert out.whoosh_terms

    def test_tag_filters_empty_when_no_match(self) -> None:
        q = SearchQuery(query="xyz unknown", max_results=5)
        vocab = {"other"}
        out = expand(q, vocab, _config())
        assert out.tag_filters == []

    def test_context_filter_passed_through(self) -> None:
        q = SearchQuery(query="foo", context="work", max_results=5)
        out = expand(q, set(), _config())
        assert out.context_filter == "work"

    def test_role_terms_added_for_secretary(self) -> None:
        q = SearchQuery(query="tasks", context="work", max_results=5, agent_role="secretary")
        out = expand(q, set(), _config(add_role_terms=True))
        assert "workflow" in out.role_terms
        assert "task-management" in out.role_terms

    def test_role_terms_empty_when_add_role_terms_false(self) -> None:
        q = SearchQuery(query="tasks", agent_role="secretary", max_results=5)
        out = expand(q, set(), _config(add_role_terms=False))
        assert out.role_terms == []

    def test_empty_query(self) -> None:
        q = SearchQuery(query="   ", max_results=5)
        out = expand(q, set(), _config())
        assert out.raw_query == ""
        assert out.whoosh_terms == []
        assert out.tag_filters == []
