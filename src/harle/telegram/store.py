"""SQLite-backed DM conversation mapping for Stage 2."""

from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite


class SqliteConversationStore:
    """Persist ``chat_id -> conversation_id`` mappings in SQLite."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def init(self) -> None:
        """Open the SQLite connection and ensure schema exists."""
        path = Path(self._db_path)
        if path.parent != Path("."):
            path.parent.mkdir(parents=True, exist_ok=True)

        conn = await aiosqlite.connect(self._db_path)
        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.execute("PRAGMA synchronous=NORMAL;")
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dm_conversations (
                chat_id         INTEGER PRIMARY KEY,
                conversation_id TEXT    NOT NULL,
                updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        await conn.commit()
        self._conn = conn

    async def aclose(self) -> None:
        """Close the SQLite connection if it is open."""
        async with self._lock:
            if self._conn is not None:
                await self._conn.close()
                self._conn = None

    async def get(self, chat_id: int) -> str | None:
        """Return the mapped conversation ID for ``chat_id`` if present."""
        async with self._lock:
            conn = self._require_connection()
            cursor = await conn.execute(
                "SELECT conversation_id FROM dm_conversations WHERE chat_id = ?",
                (chat_id,),
            )
            row = await cursor.fetchone()
            await cursor.close()
            return str(row[0]) if row else None

    async def set(self, chat_id: int, conversation_id: str) -> None:
        """Upsert ``chat_id -> conversation_id`` mapping."""
        async with self._lock:
            conn = self._require_connection()
            await conn.execute(
                """
                INSERT INTO dm_conversations(chat_id, conversation_id, updated_at)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(chat_id) DO UPDATE SET
                    conversation_id=excluded.conversation_id,
                    updated_at=datetime('now')
                """,
                (chat_id, conversation_id),
            )
            await conn.commit()

    async def clear(self, chat_id: int) -> None:
        """Delete the mapping for ``chat_id`` if present."""
        async with self._lock:
            conn = self._require_connection()
            await conn.execute("DELETE FROM dm_conversations WHERE chat_id = ?", (chat_id,))
            await conn.commit()

    def _require_connection(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("SqliteConversationStore is not initialized; call init() first.")
        return self._conn


__all__ = ["SqliteConversationStore"]
