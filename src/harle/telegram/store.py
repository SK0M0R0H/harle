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
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dm_chat_epoch (
                chat_id INTEGER PRIMARY KEY,
                epoch   INTEGER NOT NULL DEFAULT 0
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

    async def get_conversation_and_epoch(self, chat_id: int) -> tuple[str | None, int]:
        """Return ``(conversation_id, epoch)`` for ``chat_id`` under one lock.

        Callers should use this snapshot when starting a turn so ``/new`` (which
        bumps ``epoch`` and clears the row) invalidates late persistence from older
        turns.
        """
        async with self._lock:
            conn = self._require_connection()
            cursor = await conn.execute(
                "SELECT conversation_id FROM dm_conversations WHERE chat_id = ?",
                (chat_id,),
            )
            conv_row = await cursor.fetchone()
            await cursor.close()
            conversation_id = str(conv_row[0]) if conv_row else None

            cursor = await conn.execute(
                "SELECT epoch FROM dm_chat_epoch WHERE chat_id = ?",
                (chat_id,),
            )
            epoch_row = await cursor.fetchone()
            await cursor.close()
            epoch = int(epoch_row[0]) if epoch_row else 0
            return conversation_id, epoch

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

    async def set_conversation_if_epoch_matches(
        self,
        chat_id: int,
        conversation_id: str,
        *,
        expected_epoch: int,
    ) -> bool:
        """Persist ``conversation_id`` only if ``dm_chat_epoch`` for ``chat_id`` is still ``expected_epoch``."""
        async with self._lock:
            conn = self._require_connection()
            cursor = await conn.execute(
                "SELECT epoch FROM dm_chat_epoch WHERE chat_id = ?",
                (chat_id,),
            )
            row = await cursor.fetchone()
            await cursor.close()
            current = int(row[0]) if row else 0
            if current != expected_epoch:
                return False
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
            return True

    async def clear(self, chat_id: int) -> None:
        """Bump per-chat epoch and delete the mapping for ``chat_id`` (``/new``).

        Bumping the epoch invalidates any in-flight turn that started with an older
        epoch snapshot, so late ``RunResponse`` writes cannot undo a reset.
        """
        async with self._lock:
            conn = self._require_connection()
            await conn.execute(
                """
                INSERT INTO dm_chat_epoch(chat_id, epoch) VALUES (?, 1)
                ON CONFLICT(chat_id) DO UPDATE SET epoch = epoch + 1
                """,
                (chat_id,),
            )
            await conn.execute("DELETE FROM dm_conversations WHERE chat_id = ?", (chat_id,))
            await conn.commit()

    def _require_connection(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("SqliteConversationStore is not initialized; call init() first.")
        return self._conn


__all__ = ["SqliteConversationStore"]
