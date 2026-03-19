"""Tests for harle.indexing.indexer — DB sync and Whoosh integration."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from whoosh.fields import DATETIME, ID, KEYWORD, TEXT, Schema
from whoosh.index import create_in

from harle.config import ChunkingConfig
from harle.dataset.reader import DatasetReader
from harle.indexing.hasher import compute_hash
from harle.indexing.indexer import Indexer, _sync_whoosh
from harle.search import whoosh_index


def _legacy_whoosh_dir(idx_path: Path) -> None:
    idx_path.mkdir(parents=True, exist_ok=True)
    legacy = Schema(
        path=ID(stored=True, unique=True),
        title=TEXT(stored=True),
        tags=KEYWORD(stored=True, commas=True),
        content=TEXT(stored=False),
        context=ID(stored=True),
        modified=DATETIME(stored=True),
    )
    ix = create_in(str(idx_path), legacy)
    ix.close()


def _rows_matching_reader(reader: DatasetReader) -> list[MagicMock]:
    rows: list[MagicMock] = []
    for f in reader.read_all():
        m = MagicMock()
        m.file_path = f.relative_path
        m.content_hash = compute_hash(f.raw_content)
        m.title = f.title
        m.tags = f.tags if f.tags else None
        m.context = f.context
        rows.append(m)
    return rows


def _make_db(rows_ref: list) -> MagicMock:
    @contextmanager
    def session_cm():
        class Inner:
            def scalars(self, _stmt):
                m = MagicMock()
                m.all.return_value = list(rows_ref)
                return m

            def add(self, obj):
                rows_ref.append(obj)

            def delete(self, obj):
                rows_ref.remove(obj)

        yield Inner()

    db = MagicMock()
    db.session = session_cm
    return db


@pytest.fixture()
def chunking() -> ChunkingConfig:
    return ChunkingConfig(
        enabled=False,
        knowledge_token_threshold=10_000,
        contextual_enrichment=False,
        paragraph_max_tokens=600,
        max_chunks_per_file_in_results=3,
    )


class TestIndexerDbMutations:
    def test_sync_updates_row_when_hash_changes(
        self, dataset_dir: Path, tmp_path: Path, chunking: ChunkingConfig
    ) -> None:
        idx = tmp_path / "whoosh"
        reader = DatasetReader(str(dataset_dir))
        whoosh_index.build_from_scratch(reader, idx, chunking=chunking)
        rows = _rows_matching_reader(reader)
        rows[0].content_hash = "intentionally_wrong_hash"
        db = _make_db(rows)
        indexer = Indexer(db, reader, whoosh_index_path=idx, chunking=chunking)
        assert indexer.sync() >= 1

    def test_sync_removes_deleted_file_and_whoosh_entry(
        self, dataset_dir: Path, tmp_path: Path, chunking: ChunkingConfig
    ) -> None:
        idx = tmp_path / "whoosh"
        reader = DatasetReader(str(dataset_dir))
        whoosh_index.build_from_scratch(reader, idx, chunking=chunking)
        rows = _rows_matching_reader(reader)
        ghost = MagicMock()
        ghost.file_path = "deleted/ghost.md"
        ghost.content_hash = "deadbeef"
        rows.append(ghost)
        db = _make_db(rows)
        indexer = Indexer(db, reader, whoosh_index_path=idx, chunking=chunking)
        assert indexer.sync() >= 1


class TestIndexerWhooshSchema:
    def test_sync_full_rebuild_when_whoosh_schema_stale_and_no_file_changes(
        self, dataset_dir: Path, tmp_path: Path, chunking: ChunkingConfig
    ) -> None:
        idx = tmp_path / "whoosh"
        _legacy_whoosh_dir(idx)
        reader = DatasetReader(str(dataset_dir))
        rows = _rows_matching_reader(reader)
        db = _make_db(rows)
        indexer = Indexer(db, reader, whoosh_index_path=idx, chunking=chunking)

        changes = indexer.sync()
        assert changes == 0
        ix, reset = whoosh_index.get_or_create_index(idx)
        try:
            assert reset is False
            assert frozenset(ix.schema.names()) == frozenset(whoosh_index.SCHEMA.names())
        finally:
            ix.close()
        with ix.searcher() as s:
            assert s.doc_count() >= 1

    def test_sync_incremental_when_schema_current(
        self, dataset_dir: Path, tmp_path: Path, chunking: ChunkingConfig
    ) -> None:
        idx = tmp_path / "whoosh"
        reader = DatasetReader(str(dataset_dir))
        whoosh_index.build_from_scratch(reader, idx, chunking=chunking)
        rows: list = []
        db = _make_db(rows)
        indexer = Indexer(db, reader, whoosh_index_path=idx, chunking=chunking)
        assert indexer.sync() == len(reader.read_all())


class TestSyncWhoosh:
    def test_skips_when_index_path_missing(self, dataset_dir: Path) -> None:
        reader = DatasetReader(str(dataset_dir))
        _sync_whoosh(
            Path("/nonexistent/harle_whoosh_xyz"),
            reader,
            reader.read_all()[:1],
            [],
            datetime.now(timezone.utc),
            ChunkingConfig(enabled=False),
        )

    def test_skips_when_directory_not_a_whoosh_index(self, tmp_path: Path, dataset_dir: Path) -> None:
        empty = tmp_path / "not_ix"
        empty.mkdir()
        reader = DatasetReader(str(dataset_dir))
        _sync_whoosh(
            empty,
            reader,
            reader.read_all()[:1],
            [],
            datetime.now(timezone.utc),
            ChunkingConfig(enabled=False),
        )

    def test_schema_reset_triggers_build_from_scratch(
        self, tmp_path: Path, dataset_dir: Path, chunking: ChunkingConfig
    ) -> None:
        idx = tmp_path / "whoosh"
        _legacy_whoosh_dir(idx)
        reader = DatasetReader(str(dataset_dir))
        f0 = reader.read_all()[0]
        _sync_whoosh(
            idx,
            reader,
            [f0],
            [],
            datetime.now(timezone.utc),
            chunking,
        )
        ix, _ = whoosh_index.get_or_create_index(idx)
        try:
            assert frozenset(ix.schema.names()) == frozenset(whoosh_index.SCHEMA.names())
        finally:
            ix.close()

    def test_logs_warning_when_update_raises(
        self,
        tmp_path: Path,
        dataset_dir: Path,
        chunking: ChunkingConfig,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        idx = tmp_path / "whoosh"
        reader = DatasetReader(str(dataset_dir))
        whoosh_index.build_from_scratch(reader, idx, chunking=chunking)

        def boom(**_kwargs):
            raise RuntimeError("whoosh write failed")

        monkeypatch.setattr("harle.search.whoosh_index.update_document", boom)
        caplog.set_level(logging.WARNING)
        _sync_whoosh(
            idx,
            reader,
            reader.read_all()[:1],
            [],
            datetime.now(timezone.utc),
            chunking,
        )
        assert any("Whoosh index update failed" in r.message for r in caplog.records)
