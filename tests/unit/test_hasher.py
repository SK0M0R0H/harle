"""Tests for harle.indexing.hasher — SHA-256 content hashing."""

from __future__ import annotations

import hashlib

from harle.indexing.hasher import compute_hash


class TestComputeHash:
    def test_prefix(self) -> None:
        result = compute_hash("hello")
        assert result.startswith("sha256:")

    def test_known_digest(self) -> None:
        content = "hello"
        expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
        assert compute_hash(content) == f"sha256:{expected}"

    def test_deterministic(self) -> None:
        assert compute_hash("same content") == compute_hash("same content")

    def test_different_content(self) -> None:
        assert compute_hash("content A") != compute_hash("content B")

    def test_empty_string(self) -> None:
        result = compute_hash("")
        expected = hashlib.sha256(b"").hexdigest()
        assert result == f"sha256:{expected}"

    def test_unicode(self) -> None:
        result = compute_hash("привет мир")
        assert result.startswith("sha256:")
        assert len(result) == len("sha256:") + 64
