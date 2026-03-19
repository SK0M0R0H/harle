"""Tests for harle.search.ranker."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from harle.search.ranker import rank
from harle.search.types import SearchResult
from harle.search.whoosh_index import WhooshSearchHit


def _hit(
    doc_path: str,
    score: float,
    *,
    file_path: str | None = None,
    chunk_index: int | None = None,
    heading_path: str = "",
) -> WhooshSearchHit:
    fp = file_path if file_path is not None else doc_path
    return WhooshSearchHit(
        doc_path=doc_path,
        score=score,
        file_path=fp,
        chunk_index=chunk_index,
        heading_path=heading_path,
    )


def _meta(path: str, title: str = "", tags: list[str] | None = None, token_count: int | None = None, last_modified: datetime | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        file_path=path,
        title=title or path,
        tags=tags or [],
        context=None,
        token_count=token_count,
        summary=None,
        last_modified=last_modified,
    )


class TestRank:
    def test_returns_search_results_sorted_by_score(self) -> None:
        whoosh_results = [_hit("a.md", 2.0), _hit("b.md", 1.0)]
        path_to_metadata = {
            "a.md": _meta("a.md", title="A"),
            "b.md": _meta("b.md", title="B"),
        }
        results = rank(whoosh_results, path_to_metadata, tag_filters=[])
        assert len(results) == 2
        assert all(isinstance(r, SearchResult) for r in results)
        assert results[0].score >= results[1].score
        assert results[0].file_path == "a.md"
        assert results[0].title == "A"

    def test_deduplication_by_path(self) -> None:
        whoosh_results = [_hit("a.md", 1.0), _hit("a.md", 2.0)]
        path_to_metadata = {"a.md": _meta("a.md")}
        results = rank(whoosh_results, path_to_metadata, tag_filters=[])
        assert len(results) == 1
        assert results[0].file_path == "a.md"

    def test_empty_whoosh_returns_empty(self) -> None:
        results = rank([], {}, tag_filters=[])
        assert results == []

    def test_tag_match_increases_score(self) -> None:
        whoosh_results = [_hit("f.md", 0.5), _hit("g.md", 0.5)]
        path_to_metadata = {
            "f.md": _meta("f.md", tags=["trello"]),
            "g.md": _meta("g.md", tags=[]),
        }
        results = rank(
            whoosh_results,
            path_to_metadata,
            tag_filters=["trello"],
            tag_match_weight=0.5,
            bm25_weight=0.5,
        )
        assert len(results) == 2
        # f.md has tag match so should rank higher
        assert results[0].file_path == "f.md"

    def test_source_priority_boosts_prompts(self) -> None:
        whoosh_results = [_hit("knowledge/x.md", 0.6), _hit("prompts/y.md", 0.5)]
        path_to_metadata = {
            "knowledge/x.md": _meta("knowledge/x.md"),
            "prompts/y.md": _meta("prompts/y.md"),
        }
        results = rank(whoosh_results, path_to_metadata, tag_filters=[])
        assert results[0].file_path == "prompts/y.md"
