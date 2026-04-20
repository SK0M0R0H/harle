"""Tests for SQLite-backed conversation mapping store."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from harle.telegram.store import SqliteConversationStore


@pytest.mark.asyncio
async def test_init_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite"
    store = SqliteConversationStore(str(path))
    await store.init()
    await store.init()
    await store.aclose()
    assert path.exists()


@pytest.mark.asyncio
async def test_set_get_clear_roundtrip(tmp_path: Path) -> None:
    store = SqliteConversationStore(str(tmp_path / "state.sqlite"))
    await store.init()
    await store.set(123, "conv-1")
    assert await store.get(123) == "conv-1"
    await store.clear(123)
    assert await store.get(123) is None
    await store.aclose()


@pytest.mark.asyncio
async def test_set_upserts_same_chat(tmp_path: Path) -> None:
    store = SqliteConversationStore(str(tmp_path / "state.sqlite"))
    await store.init()
    await store.set(123, "conv-1")
    await store.set(123, "conv-2")
    assert await store.get(123) == "conv-2"
    await store.aclose()


@pytest.mark.asyncio
async def test_concurrent_set_calls_complete(tmp_path: Path) -> None:
    store = SqliteConversationStore(str(tmp_path / "state.sqlite"))
    await store.init()
    await asyncio.gather(*(store.set(123, f"conv-{idx}") for idx in range(20)))
    value = await store.get(123)
    assert value is not None
    assert value.startswith("conv-")
    await store.aclose()


@pytest.mark.asyncio
async def test_value_persists_across_reopen(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite"
    store = SqliteConversationStore(str(path))
    await store.init()
    await store.set(123, "conv-persisted")
    await store.aclose()

    reopened = SqliteConversationStore(str(path))
    await reopened.init()
    assert await reopened.get(123) == "conv-persisted"
    await reopened.aclose()
