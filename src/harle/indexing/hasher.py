"""SHA-256 content hashing for change detection.

Used by the indexer to determine whether a file has changed since it
was last indexed, avoiding unnecessary re-processing.
"""

from __future__ import annotations

import hashlib


def compute_hash(content: str) -> str:
    """Compute a SHA-256 hex digest of *content*.

    Args:
        content: Text content to hash.

    Returns:
        Hex-encoded SHA-256 digest prefixed with ``sha256:``.
    """
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
