"""Unit tests for the Import Module Layer.

Covers:
- Base types (ContentType, AccessInfo, ImportItem, ImportResult)
- BaseImportSource contract via DummyImportSource
- Conversion pipeline (convert_item, run_pipeline)
- VaultWriter (create, skip_existing, update_changed, force, path validation)
- ImportRegistry (register, get_source, list_sources, run_import)
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from harle.vault_imports.base import (
    AccessInfo,
    BaseImportSource,
    ContentType,
    ImportItem,
    ImportResult,
)
from harle.vault_imports.dummy import DummyImportSource
from harle.vault_imports.pipeline import (
    ConvertedItem,
    convert_item,
    run_pipeline,
)
from harle.vault_imports.registry import ImportRegistry, ImportSourceNotFound
from harle.vault_imports.writer import VaultWriter, WriteResult


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Base types
# ---------------------------------------------------------------------------


class TestContentType:
    """Tests for ContentType enum."""

    def test_values(self) -> None:
        assert ContentType.MARKDOWN.value == "markdown"
        assert ContentType.IMAGE.value == "image"
        assert ContentType.STRUCTURED.value == "structured"
        assert ContentType.REFERENCE.value == "reference"


class TestAccessInfo:
    """Tests for AccessInfo dataclass."""

    def test_minimal(self) -> None:
        info = AccessInfo(tool_module="notion", params={"database_id": "abc"})
        assert info.tool_module == "notion"
        assert info.params == {"database_id": "abc"}
        assert info.default_filter is None

    def test_with_default_filter(self) -> None:
        info = AccessInfo(
            tool_module="notion",
            params={"database_id": "abc"},
            default_filter={"Status": "Active"},
        )
        assert info.default_filter == {"Status": "Active"}


class TestImportItem:
    """Tests for ImportItem dataclass."""

    def test_minimal(self) -> None:
        item = ImportItem(
            source_id="id-1",
            title="Title",
            content="Body",
            content_type=ContentType.MARKDOWN,
            suggested_path="a/b.md",
        )
        assert item.source_id == "id-1"
        assert item.tags == []
        assert item.context == "personal"
        assert item.metadata == {}
        assert item.images == []
        assert item.access_info is None

    def test_full(self) -> None:
        item = ImportItem(
            source_id="id-2",
            title="Ref",
            content="Summary",
            content_type=ContentType.REFERENCE,
            suggested_path="ref.md",
            tags=["a", "b"],
            context="work",
            metadata={"k": "v"},
            access_info=AccessInfo(tool_module="notion", params={"db": "x"}),
        )
        assert item.access_info is not None
        assert item.access_info.tool_module == "notion"


class TestImportResult:
    """Tests for ImportResult dataclass."""

    def test_defaults(self) -> None:
        r = ImportResult(
            source_name="dummy",
            items_found=2,
            items_imported=2,
            items_skipped=0,
            items_failed=0,
        )
        assert r.errors == []
        assert r.created_paths == []
        assert r.updated_paths == []


# ---------------------------------------------------------------------------
# BaseImportSource (via DummyImportSource)
# ---------------------------------------------------------------------------


class TestBaseImportSource:
    """Tests for the BaseImportSource contract via DummyImportSource."""

    def test_name_and_description(self) -> None:
        src = DummyImportSource()
        assert src.name == "dummy"
        assert "dummy" in src.description.lower()

    def test_supported_modes(self) -> None:
        src = DummyImportSource()
        assert src.supported_modes() == ["file"]

    def test_validate_input_accepts_file_mode(self) -> None:
        src = DummyImportSource()
        errors = _run(src.validate_input({"mode": "file"}))
        assert errors == []

    def test_validate_input_rejects_other_modes(self) -> None:
        src = DummyImportSource()
        errors = _run(src.validate_input({"mode": "api"}))
        assert len(errors) == 1
        assert "file" in errors[0]

    def test_extract_returns_items(self) -> None:
        src = DummyImportSource()
        items = _run(src.extract({}))
        assert len(items) == 2
        assert items[0].source_id == "dummy-1"
        assert items[0].title == "Dummy Import Note"
        assert items[1].source_id == "dummy-2"

    def test_extract_uses_context_from_config(self) -> None:
        src = DummyImportSource()
        items = _run(src.extract({"context": "work"}))
        assert all(item.context == "work" for item in items)

    def test_preview_same_as_extract_by_default(self) -> None:
        src = DummyImportSource()
        preview = _run(src.preview({}))
        extract = _run(src.extract({}))
        assert len(preview) == len(extract)
        assert preview[0].source_id == extract[0].source_id

    def test_default_config(self) -> None:
        src = DummyImportSource()
        cfg = src.default_config()
        assert cfg.get("mode") == "file"
        assert cfg.get("context") == "personal"
        assert "target_dir" in cfg

    def test_initialize_no_op(self) -> None:
        src = DummyImportSource()
        _run(src.initialize({}, connections=None))


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class TestConvertItem:
    """Tests for convert_item and pipeline behaviour."""

    def test_markdown_item_has_frontmatter_and_body(self) -> None:
        item = ImportItem(
            source_id="sid",
            title="My Note",
            content="Body text",
            content_type=ContentType.MARKDOWN,
            suggested_path="notes/one.md",
        )
        out = convert_item(item, "test_source", target_dir="knowledge/")
        assert out.source_id == "sid"
        assert out.relative_path == "knowledge/notes/one.md"
        assert "---" in out.content
        assert "title: My Note" in out.content or "title: \"My Note\"" in out.content
        assert "import_source: test_source" in out.content
        assert "import_source_id: sid" in out.content
        assert "# My Note" in out.content
        assert "Body text" in out.content

    def test_path_resolution_adds_target_dir(self) -> None:
        item = ImportItem(
            source_id="x",
            title="T",
            content="C",
            content_type=ContentType.MARKDOWN,
            suggested_path="sub/file.md",
        )
        out = convert_item(item, "src", target_dir="knowledge/")
        assert out.relative_path == "knowledge/sub/file.md"

    def test_path_resolution_empty_target_dir(self) -> None:
        item = ImportItem(
            source_id="x",
            title="T",
            content="C",
            content_type=ContentType.MARKDOWN,
            suggested_path="only.md",
        )
        out = convert_item(item, "src", target_dir="")
        assert out.relative_path == "only.md"

    def test_path_gets_md_extension(self) -> None:
        item = ImportItem(
            source_id="x",
            title="T",
            content="C",
            content_type=ContentType.MARKDOWN,
            suggested_path="noext",
        )
        out = convert_item(item, "src", target_dir="knowledge/")
        assert out.relative_path.endswith(".md")

    def test_reference_item_has_access_via_and_params(self) -> None:
        item = ImportItem(
            source_id="db-1",
            title="DB Ref",
            content="Summary of database.",
            content_type=ContentType.REFERENCE,
            suggested_path="ref.md",
            access_info=AccessInfo(
                tool_module="notion",
                params={"database_id": "abc"},
                default_filter={"Status": "Active"},
            ),
        )
        out = convert_item(item, "notion", target_dir="knowledge/")
        assert "import_type: reference" in out.content or "import_type: reference" in out.content
        assert "access_via: notion" in out.content or "access_via: notion" in out.content
        assert "database_id" in out.content


class TestRunPipeline:
    """Tests for run_pipeline."""

    def test_empty_list(self) -> None:
        result = run_pipeline([], "src", target_dir="knowledge/")
        assert result == []

    def test_multiple_items(self) -> None:
        items = [
            ImportItem("a", "A", "C1", ContentType.MARKDOWN, "a.md"),
            ImportItem("b", "B", "C2", ContentType.MARKDOWN, "b.md"),
        ]
        result = run_pipeline(items, "mysource", target_dir="knowledge/")
        assert len(result) == 2
        assert result[0].relative_path == "knowledge/a.md"
        assert result[1].relative_path == "knowledge/b.md"
        assert result[0].source_id == "a"
        assert result[1].source_id == "b"


# ---------------------------------------------------------------------------
# VaultWriter
# ---------------------------------------------------------------------------


class TestVaultWriter:
    """Tests for VaultWriter."""

    def test_write_items_creates_files(self, tmp_path: Path) -> None:
        writer = VaultWriter(tmp_path)
        items = [
            ConvertedItem("knowledge/a.md", "---\ntitle: A\n---\n\n# A\n\nBody.", "id-1"),
        ]
        result = writer.write_items(items)
        assert result.created == 1
        assert result.created_paths == ["knowledge/a.md"]
        assert (tmp_path / "knowledge" / "a.md").read_text(encoding="utf-8") == items[0].content

    def test_write_items_skip_existing(self, tmp_path: Path) -> None:
        writer = VaultWriter(tmp_path)
        path = tmp_path / "knowledge" / "a.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("original", encoding="utf-8")
        items = [ConvertedItem("knowledge/a.md", "new content", "id-1")]
        result = writer.write_items(items, strategy="skip_existing")
        assert result.skipped == 1
        assert result.created == 0
        assert path.read_text(encoding="utf-8") == "original"

    def test_write_items_update_changed(self, tmp_path: Path) -> None:
        writer = VaultWriter(tmp_path)
        path = tmp_path / "knowledge" / "a.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("old", encoding="utf-8")
        items = [ConvertedItem("knowledge/a.md", "new", "id-1")]
        result = writer.write_items(items, strategy="update_changed")
        assert result.updated == 1
        assert path.read_text(encoding="utf-8") == "new"

    def test_write_items_update_changed_skips_unchanged(self, tmp_path: Path) -> None:
        writer = VaultWriter(tmp_path)
        path = tmp_path / "knowledge" / "a.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        content = "same"
        path.write_text(content, encoding="utf-8")
        items = [ConvertedItem("knowledge/a.md", content, "id-1")]
        result = writer.write_items(items, strategy="update_changed")
        assert result.skipped == 1
        assert result.updated == 0

    def test_write_items_force_overwrites(self, tmp_path: Path) -> None:
        writer = VaultWriter(tmp_path)
        path = tmp_path / "knowledge" / "a.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("old", encoding="utf-8")
        items = [ConvertedItem("knowledge/a.md", "forced", "id-1")]
        result = writer.write_items(items, strategy="force")
        assert result.updated == 1
        assert path.read_text(encoding="utf-8") == "forced"

    def test_path_outside_vault_rejected(self, tmp_path: Path) -> None:
        writer = VaultWriter(tmp_path)
        # Resolved path ../outside would escape vault when written
        outside = tmp_path / "knowledge"
        outside.mkdir(parents=True, exist_ok=True)
        # Use a path that resolves outside: e.g. knowledge/../../../etc (vault is tmp_path)
        items = [ConvertedItem("../outside.md", "x", "id-1")]
        result = writer.write_items(items)
        assert result.failed == 1
        assert result.errors
        assert "outside" in result.errors[0] or "Path outside" in result.errors[0]

    def test_write_result_defaults(self) -> None:
        r = WriteResult()
        assert r.created == 0
        assert r.updated == 0
        assert r.skipped == 0
        assert r.failed == 0
        assert r.created_paths == []
        assert r.errors == []


# ---------------------------------------------------------------------------
# ImportRegistry
# ---------------------------------------------------------------------------


class TestImportRegistry:
    """Tests for ImportRegistry."""

    def _make_registry(self) -> ImportRegistry:
        reg = ImportRegistry()
        reg.register_source(DummyImportSource())
        return reg

    def test_register_and_list_sources(self) -> None:
        reg = self._make_registry()
        assert reg.list_sources() == ["dummy"]

    def test_get_source(self) -> None:
        reg = self._make_registry()
        src = reg.get_source("dummy")
        assert src.name == "dummy"

    def test_get_source_not_found_raises(self) -> None:
        reg = ImportRegistry()
        with pytest.raises(ImportSourceNotFound, match="not registered"):
            reg.get_source("nonexistent")
        reg.register_source(DummyImportSource())
        with pytest.raises(ImportSourceNotFound, match="nonexistent"):
            reg.get_source("nonexistent")

    def test_run_import_validation_failure_returns_errors(self) -> None:
        reg = self._make_registry()
        result = _run(
            reg.run_import(
                "dummy",
                {"mode": "api"},
                vault_path="/tmp/v",
                dry_run=False,
            )
        )
        assert result.items_found == 0
        assert result.items_imported == 0
        assert len(result.errors) > 0

    def test_run_import_dry_run_returns_preview_paths(self) -> None:
        reg = self._make_registry()
        result = _run(
            reg.run_import(
                "dummy",
                {},
                vault_path="/tmp/v",
                dry_run=True,
            )
        )
        assert result.items_found == 2
        assert result.items_imported == 0
        assert len(result.created_paths) == 2
        assert any("dummy_note" in p for p in result.created_paths)

    def test_run_import_writes_files(self, tmp_path: Path) -> None:
        reg = self._make_registry()
        result = _run(
            reg.run_import(
                "dummy",
                {"target_dir": "knowledge/"},
                vault_path=tmp_path,
                dry_run=False,
            )
        )
        assert result.items_found == 2
        assert result.items_imported == 2
        assert len(result.created_paths) == 2
        assert (tmp_path / "knowledge" / "dummy" / "dummy_note.md").exists()
        assert (tmp_path / "knowledge" / "dummy" / "second_note.md").exists()

    def test_run_import_merge_config(self, tmp_path: Path) -> None:
        reg = self._make_registry()
        result = _run(
            reg.run_import(
                "dummy",
                {"context": "work", "target_dir": "work_notes/"},
                vault_path=tmp_path,
                dry_run=False,
            )
        )
        assert result.items_imported == 2
        assert any("work_notes" in p for p in result.created_paths)
        content = (tmp_path / "work_notes" / "dummy" / "dummy_note.md").read_text(encoding="utf-8")
        assert "context: work" in content or "context: work" in content


# ---------------------------------------------------------------------------
# build_import_registry
# ---------------------------------------------------------------------------


class TestBuildImportRegistry:
    """Tests for build_import_registry."""

    def test_returns_registry_with_dummy(self) -> None:
        from harle.vault_imports import build_import_registry

        reg = build_import_registry()
        assert isinstance(reg, ImportRegistry)
        assert reg.list_sources() == ["dummy"]

    def test_run_import_from_built_registry(self, tmp_path: Path) -> None:
        from harle.vault_imports import build_import_registry

        reg = build_import_registry()
        result = _run(
            reg.run_import("dummy", {}, vault_path=tmp_path, dry_run=False)
        )
        assert result.items_imported == 2
