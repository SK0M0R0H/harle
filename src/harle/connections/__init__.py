"""Connections layer public API."""

from harle.connections.base import BaseConnection, ConnectionStatus
from harle.connections.exceptions import ConnectionConfigError, ConnectionNotFound
from harle.connections.rate_limiter import RateLimitConfig, RateLimiter
from harle.connections.registry import ConnectionRegistry
from harle.connections.tavily import TavilyConnection
from harle.connections.trello import TrelloConnection

__all__ = [
    "BaseConnection",
    "ConnectionStatus",
    "ConnectionConfigError",
    "ConnectionNotFound",
    "RateLimitConfig",
    "RateLimiter",
    "ConnectionRegistry",
    "TavilyConnection",
    "TrelloConnection",
]
