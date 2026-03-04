"""Tests for harle.dataset.reader — DatasetReader."""

from __future__ import annotations

from pathlib import Path

import pytest

from harle.dataset.reader import DatasetFile, DatasetReader


class TestDatasetReader:
    def test_list_files_returns_markdown_only(self, dataset_dir: Path) -> None:
        reader = DatasetReader(str(dataset_dir))
        files = reader.list_files()

        names = {p.name for p in files}
        assert "note.md" in names
        assert "plain.md" in names
        assert "journal.md" in names
        assert "nested.md" in names
        assert "readme.txt" not in names

    def test_list_files_excludes_hidden_dirs(self, dataset_dir: Path) -> None:
        reader = DatasetReader(str(dataset_dir))
        files = reader.list_files()

        paths_str = [str(p) for p in files]
        for p in paths_str:
            assert ".hidden" not in p

    def test_list_files_nonexistent_dir(self, tmp_path: Path) -> None:
        reader = DatasetReader(str(tmp_path / "nope"))
        assert reader.list_files() == []

    def test_list_files_sorted(self, dataset_dir: Path) -> None:
        reader = DatasetReader(str(dataset_dir))
        files = reader.list_files()
        assert files == sorted(files)

    def test_read_file_with_frontmatter(self, dataset_dir: Path) -> None:
        reader = DatasetReader(str(dataset_dir))
        f = reader.read_file("note.md")

        assert isinstance(f, DatasetFile)
        assert f.relative_path == "note.md"
        assert f.title == "Test Note"
        assert f.tags == ["python", "testing"]
        assert f.context == "work"
        assert "body content" in f.content

    def test_read_file_no_frontmatter(self, dataset_dir: Path) -> None:
        reader = DatasetReader(str(dataset_dir))
        f = reader.read_file("plain.md")

        assert f.title is None
        assert f.tags == []
        assert f.context is None
        assert "Plain Note" in f.content

    def test_read_file_nested(self, dataset_dir: Path) -> None:
        reader = DatasetReader(str(dataset_dir))
        f = reader.read_file("sub/nested.md")

        assert f.relative_path == "sub/nested.md"
        assert f.title == "Nested File"
        assert f.tags == ["nested"]

    def test_read_file_not_found(self, dataset_dir: Path) -> None:
        reader = DatasetReader(str(dataset_dir))
        with pytest.raises(FileNotFoundError):
            reader.read_file("nonexistent.md")

    def test_read_all(self, dataset_dir: Path) -> None:
        reader = DatasetReader(str(dataset_dir))
        files = reader.read_all()

        # 4 valid .md files (note, plain, journal, sub/nested)
        assert len(files) == 4
        titles = {f.title for f in files}
        assert "Test Note" in titles
        assert "Personal Journal" in titles
        assert "Nested File" in titles

    def test_read_all_skips_unreadable(self, dataset_dir: Path) -> None:
        # Create a file with invalid encoding
        bad_file = dataset_dir / "bad.md"
        bad_file.write_bytes(b"---\ntitle: Bad\n---\n\xff\xfe invalid utf-8")

        reader = DatasetReader(str(dataset_dir))
        files = reader.read_all()
        # bad.md should be skipped; others still parsed
        paths = {f.relative_path for f in files}
        assert "bad.md" not in paths

    def test_dataset_file_frozen(self) -> None:
        f = DatasetFile(relative_path="a.md", title="A")
        with pytest.raises(AttributeError):
            f.title = "changed"  # type: ignore[misc]

    def test_read_all_empty_dir(self, tmp_path: Path) -> None:
        reader = DatasetReader(str(tmp_path))
        assert reader.read_all() == []
