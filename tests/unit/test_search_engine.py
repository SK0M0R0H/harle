"""Tests for harle.search.engine — tokenizer, scorer, snippet extraction, SearchResponse."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from harle.search.engine import (
    SearchEngine,
    _compute_score,
    _extract_snippet,
    _tokenize,
)
from harle.search.types import ExpandedQuery, SearchQuery, SearchResponse


# ---------------------------------------------------------------------------
# _tokenize
# ---------------------------------------------------------------------------

class TestTokenize:
    def test_basic_split(self) -> None:
        assert _tokenize("hello world") == ["hello", "world"]

    def test_lowercase(self) -> None:
        assert _tokenize("Hello WORLD") == ["hello", "world"]

    def test_drops_short_words(self) -> None:
        # Words with len <= 1 are dropped
        assert _tokenize("a I am ok") == ["am", "ok"]

    def test_empty_string(self) -> None:
        assert _tokenize("") == []

    def test_whitespace_only(self) -> None:
        assert _tokenize("   ") == []

    def test_single_long_word(self) -> None:
        assert _tokenize("testing") == ["testing"]

    def test_single_char_word(self) -> None:
        assert _tokenize("x") == []


# ---------------------------------------------------------------------------
# _compute_score
# ---------------------------------------------------------------------------

class TestComputeScore:
    def test_title_match(self) -> None:
        score = _compute_score(
            terms=["python"],
            title="Python Tutorial",
            tags=[],
            content="",
        )
        assert score == pytest.approx(3.0)  # _TITLE_WEIGHT

    def test_tag_match(self) -> None:
        score = _compute_score(
            terms=["python"],
            title="",
            tags=["python", "testing"],
            content="",
        )
        assert score == pytest.approx(2.0)  # _TAG_WEIGHT

    def test_content_match(self) -> None:
        score = _compute_score(
            terms=["hello"],
            title="",
            tags=[],
            content="hello hello hello",
        )
        # 3 occurrences * 0.5 = 1.5, under the cap of 3.0
        assert score == pytest.approx(1.5)

    def test_content_match_capped(self) -> None:
        score = _compute_score(
            terms=["hello"],
            title="",
            tags=[],
            content="hello " * 100,
        )
        # Capped at 3.0 per term
        assert score == pytest.approx(3.0)

    def test_combined_score(self) -> None:
        score = _compute_score(
            terms=["python"],
            title="Python Guide",
            tags=["python"],
            content="Learn python programming in python.",
        )
        # title: 3.0, tag: 2.0, content: min(2 * 0.5, 3.0) = 1.0
        assert score == pytest.approx(6.0)

    def test_no_match(self) -> None:
        score = _compute_score(
            terms=["rust"],
            title="Python Guide",
            tags=["python"],
            content="Learn python.",
        )
        assert score == 0.0

    def test_multiple_terms(self) -> None:
        score = _compute_score(
            terms=["python", "guide"],
            title="Python Guide",
            tags=[],
            content="",
        )
        # Both match in title: 3.0 + 3.0
        assert score == pytest.approx(6.0)

    def test_case_insensitive(self) -> None:
        score = _compute_score(
            terms=["python"],
            title="PYTHON",
            tags=["PYTHON"],
            content="Python",
        )
        assert score > 0

    def test_empty_terms(self) -> None:
        score = _compute_score(
            terms=[],
            title="Python",
            tags=["python"],
            content="Python is great",
        )
        assert score == 0.0

    def test_partial_tag_match(self) -> None:
        """A term that is a substring of a tag should match."""
        score = _compute_score(
            terms=["test"],
            title="",
            tags=["testing"],
            content="",
        )
        assert score == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# _extract_snippet
# ---------------------------------------------------------------------------

class TestExtractSnippet:
    def test_first_term_found(self) -> None:
        content = "The quick brown fox jumps over the lazy dog."
        snippet = _extract_snippet(content, ["fox"])
        assert "fox" in snippet

    def test_no_match_returns_start(self) -> None:
        content = "The quick brown fox jumps over the lazy dog."
        snippet = _extract_snippet(content, ["zebra"])
        assert snippet.startswith("The quick")

    def test_ellipsis_prefix_when_offset(self) -> None:
        content = "x" * 100 + " target word here."
        snippet = _extract_snippet(content, ["target"])
        assert snippet.startswith("...")

    def test_ellipsis_suffix_when_truncated(self) -> None:
        content = "target " + "x" * 500
        snippet = _extract_snippet(content, ["target"], max_length=50)
        assert snippet.endswith("...")

    def test_max_length_respected(self) -> None:
        content = "word " * 200
        snippet = _extract_snippet(content, ["word"], max_length=100)
        # Snippet may have "..." prefix/suffix but should be bounded
        assert len(snippet) < 200

    def test_newlines_replaced_with_spaces(self) -> None:
        content = "line one\nline two\nline three"
        snippet = _extract_snippet(content, ["line"])
        assert "\n" not in snippet

    def test_empty_terms(self) -> None:
        content = "Some content here."
        snippet = _extract_snippet(content, [])
        assert snippet.startswith("Some content")


# ---------------------------------------------------------------------------
# SearchEngine.search return type (Phase 1)
# ---------------------------------------------------------------------------

class TestSearchReturnsSearchResponse:
    """Engine.search() returns SearchResponse with file_results, query_metadata."""

    def test_empty_query_returns_response_with_empty_file_results(self) -> None:
        db = MagicMock()
        session_mock = MagicMock()
        session_mock.__enter__ = lambda self: self
        session_mock.__exit__ = lambda *a: None
        db.session.return_value = session_mock
        session_mock.scalars.return_value.all.return_value = []

        engine = SearchEngine(dataset_path="/nonexistent", db=db)
        query = SearchQuery(query="", max_results=10)
        response = engine.search(query)

        assert isinstance(response, SearchResponse)
        assert response.file_results == []
        assert response.query_metadata.phase == "whoosh"  # default engine
        assert response.query_metadata.original_query == ""


# ---------------------------------------------------------------------------
# Phase 2 — Whoosh rebuild when schema is stale
# ---------------------------------------------------------------------------


class TestSearchPhase2WhooshRebuild:
    def test_rebuilds_when_disk_schema_reported_stale(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from harle.dataset.reader import DatasetReader
        from harle.search import whoosh_index

        vault = tmp_path / "vault"
        (vault / "prompts").mkdir(parents=True)
        (vault / "prompts" / "p0.md").write_text(
            "---\ntitle: P\ntags: []\ncontext: work\n---\nbody\n",
            encoding="utf-8",
        )
        ix = tmp_path / "ix"
        reader = DatasetReader(str(vault))
        whoosh_index.build_from_scratch(reader, ix)

        rebuilds: list[int] = []

        def track_rebuild(_dp, _ip, _log):
            rebuilds.append(1)

        monkeypatch.setattr("harle.search.engine._rebuild_whoosh_index", track_rebuild)
        monkeypatch.setattr("harle.search.engine._whoosh_search_safe", lambda *a, **k: [])
        monkeypatch.setattr(
            "harle.search.engine.whoosh_index.disk_index_schema_current",
            lambda _p: False,
        )
        monkeypatch.setattr("harle.search.engine.get_all_tags", lambda _s: set())
        monkeypatch.setattr(
            "harle.search.engine.expand",
            lambda q, _tv, _cfg: ExpandedQuery(
                whoosh_terms=["body"],
                tag_filters=[],
                role_terms=[],
                context_filter=None,
                raw_query=q.query or "",
            ),
        )
        monkeypatch.setattr(
            "harle.search.engine.get_candidates_for_search",
            lambda *_a, **_kw: [],
        )
        monkeypatch.setattr("harle.search.engine.get_entries_by_paths", lambda _s, _p: [])
        monkeypatch.setattr("harle.search.engine.search_memories", lambda *_a, **_kw: [])
        monkeypatch.setattr("harle.search.engine.search_similar_runs", lambda *_a, **_kw: [])

        @contextmanager
        def session_cm():
            yield MagicMock()

        db = MagicMock()
        db.session = session_cm

        class Cfg:
            engine = "whoosh"
            whoosh_index_path = str(ix)
            max_results = 10
            max_memories = 10
            max_prior_runs = 5
            memory_min_confidence = 0.3
            bm25_weight = 0.4
            tag_match_weight = 0.2
            recency_weight = 0.15
            source_priority_weight = 0.15
            prior_run_weight = 0.1

        engine = SearchEngine(str(vault), db, Cfg())
        engine.search(SearchQuery(query="hello", max_results=10))
        assert rebuilds == [1]

    def test_rebuilds_when_whoosh_search_fails_then_succeeds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from harle.dataset.reader import DatasetReader
        from harle.search import whoosh_index

        vault = tmp_path / "vault"
        (vault / "prompts").mkdir(parents=True)
        (vault / "prompts" / "p0.md").write_text(
            "---\ntitle: P\ntags: []\ncontext: work\n---\nbody\n",
            encoding="utf-8",
        )
        ix = tmp_path / "ix"
        reader = DatasetReader(str(vault))
        whoosh_index.build_from_scratch(reader, ix)

        rebuilds: list[int] = []

        def track_rebuild(*_a):
            rebuilds.append(1)

        attempt = {"n": 0}

        def flaky_search(*args, **kwargs):
            attempt["n"] += 1
            if attempt["n"] == 1:
                raise ValueError("simulated corrupt index read")
            return []

        monkeypatch.setattr("harle.search.engine._rebuild_whoosh_index", track_rebuild)
        monkeypatch.setattr("harle.search.engine.whoosh_index.search", flaky_search)
        monkeypatch.setattr("harle.search.engine.get_all_tags", lambda _s: set())
        monkeypatch.setattr(
            "harle.search.engine.expand",
            lambda q, _tv, _cfg: ExpandedQuery(
                whoosh_terms=["body"],
                tag_filters=[],
                role_terms=[],
                context_filter=None,
                raw_query=q.query or "",
            ),
        )
        monkeypatch.setattr(
            "harle.search.engine.get_candidates_for_search",
            lambda *_a, **_kw: [],
        )
        monkeypatch.setattr("harle.search.engine.get_entries_by_paths", lambda _s, _p: [])
        monkeypatch.setattr("harle.search.engine.search_memories", lambda *_a, **_kw: [])
        monkeypatch.setattr("harle.search.engine.search_similar_runs", lambda *_a, **_kw: [])

        @contextmanager
        def session_cm():
            yield MagicMock()

        db = MagicMock()
        db.session = session_cm

        class Cfg:
            engine = "whoosh"
            whoosh_index_path = str(ix)
            max_results = 10
            max_memories = 10
            max_prior_runs = 5
            memory_min_confidence = 0.3
            bm25_weight = 0.4
            tag_match_weight = 0.2
            recency_weight = 0.15
            source_priority_weight = 0.15
            prior_run_weight = 0.1

        engine = SearchEngine(str(vault), db, Cfg())
        engine.search(SearchQuery(query="hello", max_results=10))
        assert rebuilds == [1]
        assert attempt["n"] == 2

    def test_no_rebuild_when_search_safe_returns_empty_list(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``whoosh_hits = raw_hits`` path: non-None empty list does not trigger rebuild."""
        from harle.dataset.reader import DatasetReader
        from harle.search import whoosh_index

        vault = tmp_path / "vault"
        (vault / "prompts").mkdir(parents=True)
        (vault / "prompts" / "p0.md").write_text(
            "---\ntitle: P\ntags: []\ncontext: work\n---\nbody\n",
            encoding="utf-8",
        )
        ix = tmp_path / "ix"
        reader = DatasetReader(str(vault))
        whoosh_index.build_from_scratch(reader, ix)

        rebuilds: list[int] = []

        monkeypatch.setattr(
            "harle.search.engine._rebuild_whoosh_index",
            lambda *_a: rebuilds.append(1),
        )
        monkeypatch.setattr("harle.search.engine._whoosh_search_safe", lambda *a, **k: [])
        monkeypatch.setattr("harle.search.engine.get_all_tags", lambda _s: set())
        monkeypatch.setattr(
            "harle.search.engine.expand",
            lambda q, _tv, _cfg: ExpandedQuery(
                whoosh_terms=["body"],
                tag_filters=[],
                role_terms=[],
                context_filter=None,
                raw_query=q.query or "",
            ),
        )
        monkeypatch.setattr(
            "harle.search.engine.get_candidates_for_search",
            lambda *_a, **_kw: [],
        )
        monkeypatch.setattr("harle.search.engine.get_entries_by_paths", lambda _s, _p: [])
        monkeypatch.setattr("harle.search.engine.search_memories", lambda *_a, **_kw: [])
        monkeypatch.setattr("harle.search.engine.search_similar_runs", lambda *_a, **_kw: [])

        @contextmanager
        def session_cm():
            yield MagicMock()

        db = MagicMock()
        db.session = session_cm

        class Cfg:
            engine = "whoosh"
            whoosh_index_path = str(ix)
            max_results = 10
            max_memories = 10
            max_prior_runs = 5
            memory_min_confidence = 0.3
            bm25_weight = 0.4
            tag_match_weight = 0.2
            recency_weight = 0.15
            source_priority_weight = 0.15
            prior_run_weight = 0.1

        engine = SearchEngine(str(vault), db, Cfg())
        engine.search(SearchQuery(query="hello", max_results=10))
        assert rebuilds == []
