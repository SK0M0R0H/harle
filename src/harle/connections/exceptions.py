"""Connections layer exceptions."""


class ConnectionConfigError(ValueError):
    """Raised when a connection has missing or invalid configuration."""


class ConnectionNotFound(LookupError):
    """Raised when a requested connection is not registered."""

