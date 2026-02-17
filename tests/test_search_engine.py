"""Tests for harle.search.engine — tokenizer, scorer, snippet extraction."""

from __future__ import annotations

import pytest

from harle.search.engine import _compute_score, _extract_snippet, _tokenize


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
