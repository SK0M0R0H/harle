"""Per-chat in-flight request guard for Telegram DM conversations."""

from __future__ import annotations

import asyncio


class ChatBusyGuard:
    """Track which chat IDs currently have an active `/chat` turn."""

    def __init__(self) -> None:
        self._active_chat_ids: set[int] = set()
        self._lock = asyncio.Lock()

    async def try_acquire(self, chat_id: int) -> bool:
        """Mark ``chat_id`` active; return ``False`` when already active."""
        async with self._lock:
            if chat_id in self._active_chat_ids:
                return False
            self._active_chat_ids.add(chat_id)
            return True

    async def release(self, chat_id: int) -> None:
        """Mark ``chat_id`` inactive."""
        async with self._lock:
            self._active_chat_ids.discard(chat_id)


__all__ = ["ChatBusyGuard"]
