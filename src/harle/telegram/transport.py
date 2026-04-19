"""Telegram message shaping: chunking, unsupported content, error copy."""

from __future__ import annotations

from harle.telegram.errors import (
    ChatError,
    ChatHTTPError,
    ChatProcessingLost,
    ChatServerTimeout,
    ChatUnreachable,
)

TELEGRAM_MAX_MESSAGE_LENGTH = 4096


def unsupported_content_reply() -> str:
    return (
        "I can't process this content type yet. "
        "Please send text messages and commands only."
    )


def split_for_telegram(text: str, limit: int = TELEGRAM_MAX_MESSAGE_LENGTH) -> list[str]:
    """Split *text* into Telegram-sized chunks, preserving order.

    Prefers breaks at paragraph, line, sentence-ish, then word boundaries;
    otherwise hard-splits at *limit*.
    """
    if not text:
        return []
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    rest = text
    min_first_segment = max(32, limit // 4)

    while rest:
        if len(rest) <= limit:
            chunks.append(rest)
            break

        window = rest[:limit]
        cut = _best_break_index(window, limit, min_first_segment)
        part = rest[:cut].rstrip()
        if not part:
            part = rest[:limit]
            cut = limit
        chunks.append(part)
        rest = rest[cut:].lstrip("\n")

    return [c for c in chunks if c]


def _best_break_index(window: str, limit: int, min_first: int) -> int:
    """Return index *within window* (exclusive) where the first chunk should end."""
    for sep in ("\n\n", "\n"):
        idx = window.rfind(sep)
        if idx >= min_first:
            return idx + len(sep)

    idx = window.rfind(". ")
    if idx >= min_first:
        return idx + len(". ")

    idx = window.rfind(" ")
    if idx >= min_first:
        return idx + 1

    return limit


def error_reply_for(exc: BaseException, *, include_debug: bool = True) -> str:
    """Map orchestrator / transport errors to user-visible plain text.

    During early releases we append a ``Debug:`` block so failures are
    self-describing in the chat (exception class, message, HTTP status/body)
    without forcing an operator to dig into server logs. Set ``include_debug=False``
    once the bot stabilises and noisy chat output becomes undesirable.
    """
    return _friendly_message(exc) + (_debug_suffix(exc) if include_debug else "")


def _friendly_message(exc: BaseException) -> str:
    if isinstance(exc, ChatServerTimeout):
        return (
            "The assistant took too long and the server stopped the request (timeout). "
            "Please try again with a shorter question."
        )
    if isinstance(exc, ChatUnreachable):
        return (
            "I couldn't reach the Harle server. "
            "Check that the orchestrator is running and reachable, then try again."
        )
    if isinstance(exc, ChatProcessingLost):
        return (
            "The server lost track of this request while it was still running. "
            "Please try again."
        )
    if isinstance(exc, ChatHTTPError):
        if exc.status_code >= 500:
            return (
                "The Harle server returned an error while processing your message. "
                "Please try again later."
            )
        if exc.status_code == 401 or exc.status_code == 403:
            return (
                "Authentication with the Harle server failed. "
                "Check HARLE_API_TOKEN matches the server configuration."
            )
        return (
            "The Harle server could not process your message "
            f"(HTTP {exc.status_code}). Please try again."
        )
    return (
        "Something went wrong while talking to Harle. "
        "Please try again in a moment."
    )


# Per-field caps for the debug block. The reply itself is later passed through
# ``split_for_telegram`` by the handler, so values larger than 4096 chars are fine —
# they will be sent as multiple messages rather than dropped. The caps below exist
# only as a last-resort spam guard so a pathological orchestrator response (e.g. a
# 5MB HTML error page) cannot flood the chat with dozens of messages.
_DEBUG_BODY_LIMIT = 16_000        # ~4 Telegram messages worth of body
_DEBUG_MESSAGE_LIMIT = 2_000      # exception ``str(exc)`` is normally short


def _debug_suffix(exc: BaseException) -> str:
    """Render a compact ``Debug:`` block for *exc*. Returns ``""`` if nothing useful."""
    cls = f"{type(exc).__module__}.{type(exc).__name__}"
    lines: list[str] = ["", "Debug:", f"  type: {cls}"]

    if isinstance(exc, ChatError) and exc.request_id:
        # X-Request-ID is greppable in orchestrator logs (search ``request_id=<uuid>``).
        lines.append(f"  request_id: {exc.request_id}")

    msg = str(exc).strip()
    if msg:
        lines.append(f"  message: {_truncate(msg, _DEBUG_MESSAGE_LIMIT)}")

    if isinstance(exc, ChatHTTPError):
        lines.append(f"  http_status: {exc.status_code}")
        body = (exc.body or "").strip()
        if body:
            lines.append(f"  body: {_truncate(body, _DEBUG_BODY_LIMIT)}")

    cause = exc.__cause__ or exc.__context__
    if cause is not None and cause is not exc:
        cause_cls = f"{type(cause).__module__}.{type(cause).__name__}"
        cause_msg = _truncate(str(cause).strip(), _DEBUG_MESSAGE_LIMIT)
        lines.append(f"  cause: {cause_cls}: {cause_msg}" if cause_msg else f"  cause: {cause_cls}")

    return "\n" + "\n".join(lines)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"
