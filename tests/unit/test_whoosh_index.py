"""Tests for harle.search.whoosh_index."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from whoosh.fields import DATETIME, ID, KEYWORD, Schema, TEXT
from whoosh.index import create_in, open_dir

from harle.config import ChunkingConfig
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

    def test_search_empty_candidate_paths_returns_empty(self, tmp_path: Path) -> None:
        reader = MagicMock()
        reader.read_all.return_value = [
            MagicMock(
                relative_path="z.md",
                title="Z",
                tags=[],
                content="termhere",
                context="work",
                raw_content="termhere",
            ),
        ]
        reader.dataset_path = tmp_path
        whoosh_index.build_from_scratch(reader, tmp_path / "idx")
        assert (
            whoosh_index.search(
                tmp_path / "idx",
                whoosh_terms=["termhere"],
                candidate_paths=set(),
                limit=10,
            )
            == []
        )

    def test_update_document_without_file_obj(self, tmp_path: Path) -> None:
        chunking = ChunkingConfig(
            enabled=False,
            knowledge_token_threshold=10_000,
            contextual_enrichment=False,
            paragraph_max_tokens=600,
            max_chunks_per_file_in_results=3,
        )
        idx = tmp_path / "ud"
        idx.mkdir(parents=True, exist_ok=True)
        ix = create_in(str(idx), whoosh_index.SCHEMA)
        writer = ix.writer()
        whoosh_index.update_document(
            writer,
            path="only.md",
            title="Hi",
            tags=["t"],
            content="uniqueblob xyz",
            context="work",
            modified=datetime.now(timezone.utc),
            file_obj=None,
            chunking=chunking,
        )
        writer.commit()
        ix.close()
        hits = whoosh_index.search(
            idx,
            whoosh_terms=["uniqueblob"],
            candidate_paths={"only.md"},
            limit=5,
        )
        assert hits

    def test_update_document_uses_default_chunking_when_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[int] = []

        def track_default():
            calls.append(1)
            return ChunkingConfig(
                enabled=False,
                knowledge_token_threshold=10_000,
                contextual_enrichment=False,
                paragraph_max_tokens=600,
                max_chunks_per_file_in_results=3,
            )

        monkeypatch.setattr(whoosh_index, "_default_chunking", track_default)
        idx = tmp_path / "ud2"
        idx.mkdir(parents=True, exist_ok=True)
        ix = create_in(str(idx), whoosh_index.SCHEMA)
        writer = ix.writer()
        whoosh_index.update_document(
            writer,
            path="p.md",
            title="T",
            tags=[],
            content="body",
            context="work",
            modified=datetime.now(timezone.utc),
            file_obj=None,
            chunking=None,
        )
        writer.commit()
        ix.close()
        assert calls == [1]

    def test_remove_document_deletes_by_path(self, tmp_path: Path) -> None:
        reader = MagicMock()
        reader.read_all.return_value = [
            MagicMock(
                relative_path="r.md",
                title="R",
                tags=[],
                content="keepme",
                context="work",
                raw_content="keepme",
            ),
        ]
        reader.dataset_path = tmp_path
        whoosh_index.build_from_scratch(reader, tmp_path / "idx")
        ix = open_dir(str(tmp_path / "idx"))
        writer = ix.writer()
        whoosh_index.remove_document(writer, "r.md")
        writer.commit()
        ix.close()
        assert not whoosh_index.search(
            tmp_path / "idx",
            whoosh_terms=["keepme"],
            candidate_paths={"r.md"},
            limit=5,
        )

    def test_build_from_scratch_cancel_on_write_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        reader = MagicMock()
        reader.read_all.return_value = [
            MagicMock(
                relative_path="a.md",
                title="T",
                tags=[],
                content="x",
                context="work",
                raw_content="x",
            ),
        ]
        reader.dataset_path = tmp_path
        (tmp_path / "a.md").write_text("x", encoding="utf-8")

        def boom(*_a, **_k):
            raise RuntimeError("write fail")

        monkeypatch.setattr(whoosh_index, "write_file_to_index", boom)
        with pytest.raises(RuntimeError, match="write fail"):
            whoosh_index.build_from_scratch(reader, tmp_path / "idx")

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

    def test_disk_index_schema_current_true_when_path_has_no_whoosh_index(
        self, tmp_path: Path
    ) -> None:
        empty = tmp_path / "plain_dir"
        empty.mkdir()
        assert whoosh_index.disk_index_schema_current(empty) is True

    def test_disk_index_schema_current_false_when_open_dir_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(_p: str):
            raise OSError("cannot open index")

        monkeypatch.setattr(whoosh_index, "_whoosh_exists_in", lambda _p: True)
        monkeypatch.setattr(whoosh_index, "open_dir", boom)
        assert whoosh_index.disk_index_schema_current(tmp_path) is False

    def test_get_or_create_index_new_directory_returns_not_reset(self, tmp_path: Path) -> None:
        idx_path = tmp_path / "fresh"
        ix, schema_reset = whoosh_index.get_or_create_index(idx_path)
        try:
            assert schema_reset is False
            assert frozenset(ix.schema.names()) == frozenset(whoosh_index.SCHEMA.names())
        finally:
            ix.close()

    def test_whoosh_schema_matches_false_when_names_raises(self) -> None:
        ix = MagicMock()
        ix.schema.names.side_effect = RuntimeError("bad schema")
        assert whoosh_index._whoosh_schema_matches(ix) is False

    def test_build_from_scratch_uses_utc_now_when_stat_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        reader = MagicMock()
        reader.read_all.return_value = [
            MagicMock(
                relative_path="a.md",
                title="T",
                tags=[],
                content="body",
                context="work",
                raw_content="body",
            ),
        ]
        reader.dataset_path = tmp_path
        (tmp_path / "a.md").write_text("body", encoding="utf-8")

        real_stat = Path.stat

        def stat_raises(self, *args, **kwargs):
            if self.name == "a.md":
                raise OSError("no stat")
            return real_stat(self, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", stat_raises)
        whoosh_index.build_from_scratch(reader, tmp_path / "ix")
        results = whoosh_index.search(
            tmp_path / "ix",
            whoosh_terms=["body"],
            candidate_paths={"a.md"},
            limit=5,
        )
        assert results
