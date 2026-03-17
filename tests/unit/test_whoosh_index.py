"""Tests for harle.search.whoosh_index."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from harle.search import whoosh_index


class TestWhooshIndex:
    def test_build_from_scratch_creates_index(self, tmp_path: Path) -> None:
        reader = MagicMock()
        reader.read_all.return_value = [
            MagicMock(
                relative_path="a.md",
                title="Title A",
                tags=["x", "y"],
                content="body a",
                context="work",
                raw_content="",
            ),
        ]
        reader.dataset_path = tmp_path
        (tmp_path / "a.md").write_text("body a")

        whoosh_index.build_from_scratch(reader, tmp_path / "idx")

        assert (tmp_path / "idx").exists()
        assert whoosh_index.exists_in(str(tmp_path / "idx"))

    def test_search_returns_paths_and_scores(self, tmp_path: Path) -> None:
        reader = MagicMock()
        reader.read_all.return_value = [
            MagicMock(
                relative_path="doc.md",
                title="Trello tasks",
                tags=["trello"],
                content="stalled tasks in Trello",
                context="work",
                raw_content="",
            ),
        ]
        reader.dataset_path = tmp_path
        whoosh_index.build_from_scratch(reader, tmp_path / "idx")

        results = whoosh_index.search(
            tmp_path / "idx",
            whoosh_terms=["trello", "task"],
            candidate_paths={"doc.md"},
            limit=10,
        )

        assert len(results) == 1
        assert results[0][0] == "doc.md"
        assert results[0][1] > 0

    def test_search_empty_terms_returns_empty(self, tmp_path: Path) -> None:
        reader = MagicMock()
        reader.read_all.return_value = []
        reader.dataset_path = tmp_path
        whoosh_index.build_from_scratch(reader, tmp_path / "idx")

        results = whoosh_index.search(
            tmp_path / "idx",
            whoosh_terms=[],
            candidate_paths={"doc.md"},
            limit=10,
        )

        assert results == []

    def test_search_filtered_by_candidate_paths(self, tmp_path: Path) -> None:
        reader = MagicMock()
        reader.read_all.return_value = [
            MagicMock(
                relative_path="a.md",
                title="Doc A",
                tags=[],
                content="word",
                context="work",
                raw_content="",
            ),
            MagicMock(
                relative_path="b.md",
                title="Doc B",
                tags=[],
                content="word",
                context="work",
                raw_content="",
            ),
        ]
        reader.dataset_path = tmp_path
        whoosh_index.build_from_scratch(reader, tmp_path / "idx")

        results = whoosh_index.search(
            tmp_path / "idx",
            whoosh_terms=["word"],
            candidate_paths={"a.md"},
            limit=10,
        )

        assert len(results) == 1
        assert results[0][0] == "a.md"
