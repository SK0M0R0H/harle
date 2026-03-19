"""Tests for harle.search.whoosh_index."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from whoosh.fields import DATETIME, ID, KEYWORD, Schema, TEXT
from whoosh.index import create_in

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
                raw_content="---\n---\nbody a",
            ),
        ]
        reader.dataset_path = tmp_path
        (tmp_path / "a.md").write_text("body a")

        whoosh_index.build_from_scratch(reader, tmp_path / "idx")

        assert (tmp_path / "idx").exists()
        assert whoosh_index.exists_in(str(tmp_path / "idx"))

    def test_search_returns_hits_with_paths(self, tmp_path: Path) -> None:
        reader = MagicMock()
        reader.read_all.return_value = [
            MagicMock(
                relative_path="doc.md",
                title="Trello tasks",
                tags=["trello"],
                content="stalled tasks in Trello",
                context="work",
                raw_content="---\n---\nstalled tasks in Trello",
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
        assert results[0].doc_path == "doc.md"
        assert results[0].file_path == "doc.md"
        assert results[0].chunk_index is None
        assert results[0].score > 0

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
                raw_content="word",
            ),
            MagicMock(
                relative_path="b.md",
                title="Doc B",
                tags=[],
                content="word",
                context="work",
                raw_content="word",
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
        assert results[0].file_path == "a.md"

    def test_workflow_multi_chunk_doc_paths(self, tmp_path: Path) -> None:
        reader = MagicMock()
        body = """# W

Intro.

## One

first section uniquephrase

## Two

second section
"""
        reader.read_all.return_value = [
            MagicMock(
                relative_path="workflows/w.md",
                title="W",
                tags=[],
                content=body,
                context="work",
                raw_content=body,
            ),
        ]
        reader.dataset_path = tmp_path
        whoosh_index.build_from_scratch(reader, tmp_path / "idx")

        results = whoosh_index.search(
            tmp_path / "idx",
            whoosh_terms=["uniquephrase"],
            candidate_paths={"workflows/w.md"},
            limit=10,
        )
        assert results, "expected BM25 hit on chunked workflow"
        paths = {r.doc_path for r in results}
        assert any(p.startswith("workflows/w.md#") for p in paths)
        hit = next(r for r in results if r.chunk_index is not None)
        assert hit.file_path == "workflows/w.md"

    def test_get_or_create_index_rebuilds_when_schema_differs(self, tmp_path: Path) -> None:
        """Pre-chunking Whoosh layouts must not break incremental updates."""
        idx_path = tmp_path / "legacy"
        idx_path.mkdir(parents=True, exist_ok=True)
        legacy = Schema(
            path=ID(stored=True, unique=True),
            title=TEXT(stored=True),
            tags=KEYWORD(stored=True, commas=True),
            content=TEXT(stored=False),
            context=ID(stored=True),
            modified=DATETIME(stored=True),
        )
        ix_old = create_in(str(idx_path), legacy)
        ix_old.close()

        ix, schema_reset = whoosh_index.get_or_create_index(idx_path)
        try:
            assert schema_reset is True
            assert frozenset(ix.schema.names()) == frozenset(whoosh_index.SCHEMA.names())
        finally:
            ix.close()
