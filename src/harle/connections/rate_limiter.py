"""Async token-bucket rate limiter shared by connection consumers."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimitConfig:
    """Rate-limiter settings."""

    tokens_per_second: float
    burst_size: float | None = None


class RateLimiter:
    """Simple async token-bucket limiter."""

    def __init__(self, config: RateLimitConfig) -> None:
        if config.tokens_per_second <= 0:
            raise ValueError("tokens_per_second must be > 0")
        self._rate = float(config.tokens_per_second)
        self._capacity = float(config.burst_size or config.tokens_per_second)
        self._tokens = self._capacity
        self._updated_at = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0) -> None:
        """Wait until *tokens* are available, then consume them."""
        if tokens <= 0:
            return
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                missing = tokens - self._tokens
                wait_s = missing / self._rate
            await asyncio.sleep(wait_s)

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._updated_at
        self._updated_at = now
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)

