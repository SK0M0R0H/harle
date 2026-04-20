"""Rendering helpers for Telegram reply formatting."""

from __future__ import annotations

import logging

from telegramify_markdown import markdownify

logger = logging.getLogger(__name__)


def to_markdown_v2(markdown_text: str) -> str | None:
    """Convert Markdown text to Telegram MarkdownV2 text.

    Returns ``None`` when conversion fails so callers can fall back to plain text.
    """
    try:
        return markdownify(markdown_text)
    except Exception:  # noqa: BLE001 - conversion failures should not break replies
        logger.exception("Failed to convert assistant markdown to Telegram MarkdownV2")
        return None


__all__ = ["to_markdown_v2"]
