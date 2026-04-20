"""Tests for per-chat busy guard behavior."""

from __future__ import annotations

import pytest

from harle.telegram.busy import ChatBusyGuard


@pytest.mark.asyncio
async def test_busy_guard_rejects_second_acquire_same_chat() -> None:
    guard = ChatBusyGuard()
    assert await guard.try_acquire(1) is True
    assert await guard.try_acquire(1) is False


@pytest.mark.asyncio
async def test_busy_guard_release_allows_reacquire() -> None:
    guard = ChatBusyGuard()
    assert await guard.try_acquire(1) is True
    await guard.release(1)
    assert await guard.try_acquire(1) is True


@pytest.mark.asyncio
async def test_busy_guard_isolated_by_chat_id() -> None:
    guard = ChatBusyGuard()
    assert await guard.try_acquire(1) is True
    assert await guard.try_acquire(2) is True
