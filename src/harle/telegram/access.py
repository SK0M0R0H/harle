"""Telegram bot access policy (Stage 1: allowlist vs open)."""

from __future__ import annotations

import logging

from harle.config import Settings

logger = logging.getLogger(__name__)

POLICY_ALLOWLIST = "allowlist"
POLICY_OPEN = "open"


class AccessPolicy:
    """Declarative gate on ``from_user.id`` before invoking the orchestrator."""

    def __init__(self, settings: Settings) -> None:
        self._raw_policy = (settings.HARLE_TELEGRAM_ACCESS_POLICY or "").strip().lower()
        self._allowed_ids = _parse_user_ids(settings.HARLE_TELEGRAM_ALLOWED_USER_IDS)

    def is_allowed(self, user_id: int | None) -> bool:
        if user_id is None:
            return False
        mode = self._raw_policy if self._raw_policy in (POLICY_ALLOWLIST, POLICY_OPEN) else POLICY_ALLOWLIST
        if mode == POLICY_OPEN:
            return True
        allowed = user_id in self._allowed_ids
        if not allowed:
            logger.info("Access denied for user_id=%s (allowlist mode)", user_id)
        return allowed

    def refusal_message(self) -> str:
        return (
            "You are not authorized to use this bot. "
            "If you believe this is a mistake, ask the operator to add your Telegram user ID "
            "to HARLE_TELEGRAM_ALLOWED_USER_IDS."
        )


def _parse_user_ids(raw: str) -> frozenset[int]:
    ids: set[int] = set()
    for part in (raw or "").split(","):
        piece = part.strip()
        if not piece:
            continue
        try:
            ids.add(int(piece))
        except ValueError:
            logger.warning("Ignoring invalid Telegram user id segment: %r", piece)
    return frozenset(ids)
