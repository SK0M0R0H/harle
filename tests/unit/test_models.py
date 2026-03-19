"""Tests for harle.api.models — Pydantic request/response validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from harle.api.models import (
    HealthResponse,
    InitResponse,
    ReindexResponse,
    RunRequest,
    RunResponse,
    SearchResponse,
    SearchResultItem,
)


class TestRunRequest:
    def test_valid_request(self) -> None:
        req = RunRequest(message="Hello", context="work")
        assert req.message == "Hello"
        assert req.context == "work"

    def test_default_context(self) -> None:
        req = RunRequest(message="Hi")
        assert req.context == "personal"

    def test_empty_message_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RunRequest(message="")

    def test_invalid_context_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RunRequest(message="Hi", context="invalid")  # type: ignore[arg-type]

    def test_conversation_id_optional(self) -> None:
        req = RunRequest(message="Hi")
        assert req.conversation_id is None

    def test_conversation_id_set(self) -> None:
        req = RunRequest(message="Hi", conversation_id="conv-123")
        assert req.conversation_id == "conv-123"


class TestRunResponse:
    def test_valid_response(self) -> None:
        resp = RunResponse(
            run_id="run_abc",
            status="completed",
            result="Answer",
            context="personal",
        )
        assert resp.run_id == "run_abc"
        assert resp.status == "completed"

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RunResponse(
                run_id="run_abc",
                status="pending",  # type: ignore[arg-type]
                result="x",
                context="personal",
            )


class TestHealthResponse:
    def test_defaults(self) -> None:
        resp = HealthResponse()
        assert resp.status == "ok"


class TestInitResponse:
    def test_valid(self) -> None:
        resp = InitResponse(
            status="initialized",
            tables_created=True,
            files_seeded=5,
            files_indexed=10,
            total_files=10,
            dataset_path="/tmp/vault",
        )
        assert resp.files_seeded == 5
        assert resp.tables_created is True


class TestReindexResponse:
    def test_valid(self) -> None:
        resp = ReindexResponse(
            status="reindexed",
            files_indexed=3,
            total_files=10,
            dataset_path="/tmp/vault",
        )
        assert resp.files_indexed == 3


class TestSearchResultItem:
    def test_valid(self) -> None:
        item = SearchResultItem(
            file_path="notes/test.md",
            title="Test",
            score=5.5,
            context="work",
            tags=["python"],
            snippet="...match...",
        )
        assert item.score == 5.5

    def test_defaults(self) -> None:
        item = SearchResultItem(file_path="a.md", title="A", score=1.0)
        assert item.context is None
        assert item.tags == []
        assert item.snippet is None
        assert item.chunk_index is None
        assert item.heading_path is None

    def test_chunk_fields(self) -> None:
        item = SearchResultItem(
            file_path="w.md",
            title="W",
            score=1.0,
            chunk_index=2,
            heading_path="W > Beta",
        )
        assert item.chunk_index == 2
        assert item.heading_path == "W > Beta"


class TestSearchResponse:
    def test_valid(self) -> None:
        resp = SearchResponse(query="test", total=1, results=[
            SearchResultItem(file_path="a.md", title="A", score=1.0),
        ])
        assert resp.total == 1
        assert len(resp.results) == 1

    def test_defaults(self) -> None:
        resp = SearchResponse(query="test")
        assert resp.total == 0
        assert resp.results == []
        assert resp.context is None
