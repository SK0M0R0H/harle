"""Errors raised when talking to the orchestrator from the Telegram bot."""

from __future__ import annotations


class ChatError(Exception):
    """Base for all orchestrator errors surfaced by the Telegram bot.

    ``request_id`` is the ``X-Request-ID`` value the bot generated for the
    in-flight ``POST /chat``. It is attached by ``chat_with_polling`` so the
    caller can include it in user-visible debug output and operators can
    grep orchestrator logs for the same UUID.
    """

    request_id: str | None = None


class ChatServerTimeout(ChatError):
    """POST /chat returned HTTP 504 (server-side run limit)."""


class ChatUnreachable(ChatError):
    """Network failure or repeated processing ping failures while /chat is in flight."""


class ChatProcessingLost(ChatError):
    """GET /processing reported not_found twice while /chat still appeared in progress."""


class ChatHTTPError(ChatError):
    """POST /chat or GET /processing returned a non-success HTTP status (other than 504)."""

    def __init__(self, status_code: int, body: str = "") -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"HTTP {status_code}: {body[:200]}")
