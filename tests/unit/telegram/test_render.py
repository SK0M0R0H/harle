"""Tests for Markdown rendering helpers."""

from __future__ import annotations

import pytest

from harle.telegram.render import to_markdown_v2


def test_to_markdown_v2_happy_path() -> None:
    out = to_markdown_v2("**bold** and `code`")
    assert out is not None
    assert isinstance(out, str)


def test_to_markdown_v2_returns_none_on_conversion_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(_: str) -> str:
        raise RuntimeError("bad markdown")

    monkeypatch.setattr("harle.telegram.render.markdownify", _boom)
    assert to_markdown_v2("text") is None


def test_to_markdown_v2_escapes_markdown_v2_sensitive_chars() -> None:
    out = to_markdown_v2("literal_underscore")
    assert out is not None
    assert "\\_" in out
