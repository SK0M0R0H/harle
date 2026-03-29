"""Bearer token authentication for the HTTP API (remote deployment Phase 3)."""

from __future__ import annotations

import logging
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

def _is_public_health_path(path: str) -> bool:
    """True for ``/health`` and subpaths (``/health/connections``, etc.)."""
    return path == "/health" or path.startswith("/health/")


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Reject requests without a valid ``Authorization: Bearer`` token when configured."""

    def __init__(self, app, token: str) -> None:
        super().__init__(app)
        self._token = token

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path
        if _is_public_health_path(path):
            return await call_next(request)

        auth_header = request.headers.get("authorization") or ""
        parts = auth_header.split(None, 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            self._log_rejection(request)
            return JSONResponse(
                {"detail": "Invalid or missing API token."},
                status_code=401,
            )
        provided = parts[1].strip()
        if len(provided) != len(self._token):
            self._log_rejection(request)
            return JSONResponse(
                {"detail": "Invalid or missing API token."},
                status_code=401,
            )
        if not secrets.compare_digest(provided, self._token):
            self._log_rejection(request)
            return JSONResponse(
                {"detail": "Invalid or missing API token."},
                status_code=401,
            )
        return await call_next(request)

    def _log_rejection(self, request: Request) -> None:
        client_host = request.client.host if request.client else "unknown"
        logger.warning(
            "API token rejected or missing (path=%s client=%s)",
            request.url.path,
            client_host,
        )
