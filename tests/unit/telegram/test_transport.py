"""Tests for telegram transport helpers."""

from __future__ import annotations

import pytest

from harle.telegram.errors import ChatHTTPError, ChatProcessingLost, ChatServerTimeout, ChatUnreachable
from harle.telegram.transport import (
    TELEGRAM_MAX_MESSAGE_LENGTH,
    error_reply_for,
    split_for_telegram,
    unsupported_content_reply,
)


def test_split_empty() -> None:
    assert split_for_telegram("") == []


def test_split_short() -> None:
    assert split_for_telegram("hello") == ["hello"]


def test_split_exact_limit() -> None:
    s = "a" * TELEGRAM_MAX_MESSAGE_LENGTH
    parts = split_for_telegram(s)
    assert len(parts) == 1
    assert len(parts[0]) == TELEGRAM_MAX_MESSAGE_LENGTH


def test_split_oversize_ordering() -> None:
    s = "a" * (TELEGRAM_MAX_MESSAGE_LENGTH + 100)
    parts = split_for_telegram(s)
    assert len(parts) == 2
    assert parts[0] == "a" * TELEGRAM_MAX_MESSAGE_LENGTH
    assert parts[1] == "a" * 100


def test_split_all_chunks_within_limit() -> None:
    text = "word " * 3000
    parts = split_for_telegram(text)
    assert parts
    assert all(len(p) <= TELEGRAM_MAX_MESSAGE_LENGTH for p in parts)


def test_unsupported_reply() -> None:
    assert "text" in unsupported_content_reply().lower()


@pytest.mark.parametrize(
    ("exc", "snippet"),
    [
        (ChatServerTimeout("x"), "too long"),
        (ChatUnreachable("net"), "couldn't reach"),
        (ChatProcessingLost(), "lost track"),
        (ChatHTTPError(502, "bad"), "returned an error"),
        (ChatHTTPError(401, ""), "Authentication"),
        (ChatHTTPError(404, ""), "could not process"),
        (RuntimeError("boom"), "Something went wrong"),
    ],
)
def test_error_reply_distinct(exc: Exception, snippet: str) -> None:
    msg = error_reply_for(exc)
    assert snippet.lower() in msg.lower()


def test_error_reply_includes_debug_block_by_default() -> None:
    exc = ChatHTTPError(502, "upstream said no")
    msg = error_reply_for(exc)
    assert "Debug:" in msg
    assert "type: harle.telegram.errors.ChatHTTPError" in msg
    assert "http_status: 502" in msg
    assert "upstream said no" in msg


def test_error_reply_includes_request_id_when_set() -> None:
    exc = ChatHTTPError(502, "boom")
    exc.request_id = "abc-123-def"
    msg = error_reply_for(exc)
    assert "request_id: abc-123-def" in msg


def test_error_reply_omits_request_id_when_unset() -> None:
    msg = error_reply_for(ChatHTTPError(502, "boom"))
    assert "request_id:" not in msg


def test_error_reply_includes_cause_chain() -> None:
    try:
        try:
            raise ValueError("network down")
        except ValueError as inner:
            raise ChatUnreachable("orchestrator missed pings") from inner
    except ChatUnreachable as exc:
        msg = error_reply_for(exc)
    assert "cause: builtins.ValueError" in msg
    assert "network down" in msg


def test_error_reply_can_disable_debug() -> None:
    msg = error_reply_for(ChatHTTPError(502, "boom"), include_debug=False)
    assert "Debug:" not in msg
    assert "type:" not in msg
    assert "boom" not in msg


def test_error_reply_keeps_moderately_long_body_intact() -> None:
    """A 5 KB body fits under the per-field cap and survives without truncation;
    the handler will fan it out across multiple Telegram messages via split_for_telegram."""
    huge = "x" * 5000
    msg = error_reply_for(ChatHTTPError(500, huge))
    assert "…" not in msg
    assert huge in msg
    parts = split_for_telegram(msg)
    assert len(parts) >= 2
    assert sum(len(p) for p in parts) >= len(huge)


def test_error_reply_truncates_pathologically_large_body() -> None:
    """A 50 KB body is truncated to the per-field spam-guard limit so we don't flood the chat."""
    huge = "x" * 50_000
    msg = error_reply_for(ChatHTTPError(500, huge))
    assert "…" in msg
    assert len(msg) < 20_000
