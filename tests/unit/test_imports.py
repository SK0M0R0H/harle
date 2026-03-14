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
from unittest.mock import AsyncMock

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

    def test_registry_without_connections_has_only_dummy(self) -> None:
        from harle.vault_imports import build_import_registry

        reg = build_import_registry(connections=None)
        assert reg.list_sources() == ["dummy"]

    def test_registry_with_notion_connection_registers_notion_source(self) -> None:
        """When connections has a 'notion' connection, build_import_registry registers NotionImportSource."""
        from harle.connections import ConnectionRegistry
        from harle.connections.base import BaseConnection
        from harle.vault_imports import build_import_registry

        class StubNotionConnection(BaseConnection):
            name = "notion"
            _client = None

            @property
            def service_display_name(self) -> str:
                return "Notion"

            async def initialize(self, config: dict) -> None:
                self._client = object()

            async def shutdown(self) -> None:
                self._client = None

            async def health_check(self):
                from harle.connections.base import ConnectionStatus
                return ConnectionStatus(healthy=True, service_name="Notion", message="ok")

            def get_client(self):
                return self._client

        conn_registry = ConnectionRegistry()
        _run(conn_registry.register(StubNotionConnection(), {}))
        reg = build_import_registry(connections=conn_registry)
        sources = reg.list_sources()
        assert "dummy" in sources
        assert "notion" in sources
        assert reg.get_source("notion").name == "notion"


# ---------------------------------------------------------------------------
# Notion converter
# ---------------------------------------------------------------------------


class TestNotionConverter:
    """Tests for Notion block and property conversion."""

    def test_rich_text_to_markdown_plain(self) -> None:
        from harle.vault_imports.notion.converter import rich_text_to_markdown

        rt = [{"plain_text": "Hello world", "annotations": {}}]
        assert rich_text_to_markdown(rt) == "Hello world"

    def test_rich_text_to_markdown_bold_italic(self) -> None:
        from harle.vault_imports.notion.converter import rich_text_to_markdown

        rt = [{"plain_text": "bold", "annotations": {"bold": True, "italic": True}}]
        result = rich_text_to_markdown(rt)
        assert "**" in result
        assert "*" in result

    def test_rich_text_to_markdown_link(self) -> None:
        from harle.vault_imports.notion.converter import rich_text_to_markdown

        rt = [{"plain_text": "click", "href": "https://example.com", "annotations": {}}]
        assert "[click](https://example.com)" in rich_text_to_markdown(rt)

    def test_blocks_to_markdown_paragraph(self) -> None:
        from harle.vault_imports.notion.converter import blocks_to_markdown

        blocks = [
            {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Hello", "annotations": {}}]}},
        ]
        assert "Hello" in blocks_to_markdown(blocks)

    def test_blocks_to_markdown_heading(self) -> None:
        from harle.vault_imports.notion.converter import blocks_to_markdown

        blocks = [
            {"type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "Title", "annotations": {}}]}},
        ]
        result = blocks_to_markdown(blocks)
        assert "## Title" in result

    def test_blocks_to_markdown_code(self) -> None:
        from harle.vault_imports.notion.converter import blocks_to_markdown

        blocks = [
            {"type": "code", "code": {"rich_text": [{"plain_text": "print(1)"}], "language": "python"}},
        ]
        result = blocks_to_markdown(blocks)
        assert "```python" in result
        assert "print(1)" in result

    def test_blocks_to_markdown_todo(self) -> None:
        from harle.vault_imports.notion.converter import blocks_to_markdown

        blocks = [
            {"type": "to_do", "to_do": {"rich_text": [{"plain_text": "Task", "annotations": {}}], "checked": True}},
        ]
        result = blocks_to_markdown(blocks)
        assert "[x]" in result
        assert "Task" in result

    def test_property_value_to_string_select(self) -> None:
        from harle.vault_imports.notion.converter import property_value_to_string

        assert property_value_to_string("select", {"name": "Done"}) == "Done"

    def test_property_value_to_string_multi_select(self) -> None:
        from harle.vault_imports.notion.converter import property_value_to_string

        result = property_value_to_string("multi_select", [{"name": "A"}, {"name": "B"}])
        assert "A" in result
        assert "B" in result

    def test_property_value_to_string_checkbox(self) -> None:
        from harle.vault_imports.notion.converter import property_value_to_string

        assert property_value_to_string("checkbox", True) == "Yes"
        assert property_value_to_string("checkbox", False) == "No"

    def test_property_value_to_string_date(self) -> None:
        from harle.vault_imports.notion.converter import property_value_to_string

        result = property_value_to_string("date", {"start": "2025-01-01", "end": None})
        assert "2025-01-01" in result

    def test_property_value_to_string_number(self) -> None:
        from harle.vault_imports.notion.converter import property_value_to_string

        assert property_value_to_string("number", 42) == "42"

    def test_property_value_to_string_url(self) -> None:
        from harle.vault_imports.notion.converter import property_value_to_string

        assert property_value_to_string("url", "https://example.com") == "https://example.com"

    def test_property_value_to_string_status(self) -> None:
        from harle.vault_imports.notion.converter import property_value_to_string

        assert property_value_to_string("status", {"name": "In Progress"}) == "In Progress"

    def test_property_value_to_string_title(self) -> None:
        from harle.vault_imports.notion.converter import property_value_to_string

        rt = [{"plain_text": "My Title"}]
        assert property_value_to_string("title", rt) == "My Title"

    def test_database_to_markdown_table(self) -> None:
        from harle.vault_imports.notion.converter import database_to_markdown_table

        schema = {
            "Name": {"id": "title", "type": "title"},
            "Status": {"id": "abc", "type": "select"},
        }
        rows = [
            {"Name": [{"plain_text": "Task 1"}], "Status": {"name": "Done"}},
            {"Name": [{"plain_text": "Task 2"}], "Status": {"name": "Active"}},
        ]
        result = database_to_markdown_table(schema, rows)
        assert "Name" in result
        assert "Status" in result
        assert "Task 1" in result
        assert "Done" in result
        assert "---" in result

    def test_property_value_to_string_formula(self) -> None:
        from harle.vault_imports.notion.converter import property_value_to_string

        assert property_value_to_string("formula", {"type": "string", "string": "=1+1"}) == "=1+1"
        assert property_value_to_string("formula", {"type": "number", "number": 42}) == "42"

    def test_property_value_to_string_rollup(self) -> None:
        from harle.vault_imports.notion.converter import property_value_to_string

        assert property_value_to_string("rollup", {"type": "number", "number": 10}) == "10"
        assert property_value_to_string("rollup", {"type": "array", "array": []}) == "[]"

    def test_property_value_to_string_people(self) -> None:
        from harle.vault_imports.notion.converter import property_value_to_string

        people = [{"name": "Alice"}, {"name": "Bob"}]
        result = property_value_to_string("people", people)
        assert "Alice" in result
        assert "Bob" in result

    def test_property_value_to_string_relation(self) -> None:
        from harle.vault_imports.notion.converter import property_value_to_string

        rels = [{"id": "id1"}, {"id": "id2"}]
        result = property_value_to_string("relation", rels)
        assert "id1" in result
        assert "id2" in result

    def test_property_value_to_string_created_by(self) -> None:
        from harle.vault_imports.notion.converter import property_value_to_string

        assert property_value_to_string("created_by", {"name": "System"}) == "System"

    def test_property_value_to_string_last_edited_by(self) -> None:
        from harle.vault_imports.notion.converter import property_value_to_string

        assert property_value_to_string("last_edited_by", {"name": "Admin"}) == "Admin"

    def test_property_value_to_string_none_or_empty(self) -> None:
        from harle.vault_imports.notion.converter import property_value_to_string

        assert property_value_to_string("rich_text", None) == ""
        assert property_value_to_string("title", []) == ""

    def test_extract_page_title(self) -> None:
        from harle.vault_imports.notion.converter import extract_page_title

        page = {"properties": {"Title": {"type": "title", "title": [{"plain_text": "My Page"}]}}}
        assert extract_page_title(page) == "My Page"

    def test_extract_page_title_untitled_when_no_title_prop(self) -> None:
        from harle.vault_imports.notion.converter import extract_page_title

        page = {"properties": {"Other": {"type": "rich_text", "rich_text": []}}}
        assert extract_page_title(page) == "Untitled"

    def test_extract_database_title(self) -> None:
        from harle.vault_imports.notion.converter import extract_database_title

        db = {"title": [{"plain_text": "My Database"}]}
        assert extract_database_title(db) == "My Database"

    def test_extract_database_title_untitled_when_empty(self) -> None:
        from harle.vault_imports.notion.converter import extract_database_title

        assert extract_database_title({}) == "Untitled Database"
        assert extract_database_title({"title": []}) == "Untitled Database"

    def test_page_properties_to_metadata(self) -> None:
        from harle.vault_imports.notion.converter import page_properties_to_metadata

        schema = {"Name": {"type": "title"}, "Status": {"type": "select"}}
        resolved = {"Name": [{"plain_text": "Task"}], "Status": {"name": "Done"}}
        meta = page_properties_to_metadata(resolved, schema)
        assert "Name" in meta or "Status" in meta


# ---------------------------------------------------------------------------
# Notion import source
# ---------------------------------------------------------------------------


class TestNotionImportSource:
    """Tests for the NotionImportSource."""

    def test_name_and_description(self) -> None:
        from harle.vault_imports.notion import NotionImportSource

        src = NotionImportSource()
        assert src.name == "notion"
        assert "Notion" in src.description

    def test_supported_modes(self) -> None:
        from harle.vault_imports.notion import NotionImportSource

        src = NotionImportSource()
        modes = src.supported_modes()
        assert "api" in modes
        assert "reference" in modes

    def test_validate_input_rejects_reference_mode(self) -> None:
        from harle.vault_imports.notion import NotionImportSource

        src = NotionImportSource()
        errors = _run(src.validate_input({"mode": "reference"}))
        assert len(errors) > 0
        assert "not yet implemented" in errors[0].lower()

    def test_validate_input_rejects_unknown_mode(self) -> None:
        from harle.vault_imports.notion import NotionImportSource

        src = NotionImportSource()
        errors = _run(src.validate_input({"mode": "file"}))
        assert len(errors) > 0

    def test_validate_input_rejects_api_without_connection(self) -> None:
        from harle.vault_imports.notion import NotionImportSource

        src = NotionImportSource()
        errors = _run(src.validate_input({"mode": "api"}))
        assert len(errors) > 0
        assert "not configured" in errors[0].lower()

    def test_default_config(self) -> None:
        from harle.vault_imports.notion import NotionImportSource

        src = NotionImportSource()
        cfg = src.default_config()
        assert cfg["mode"] == "api"
        assert "target_dir" in cfg
        assert cfg["database_import_mode"] == "pages"

    def test_extract_reference_raises(self) -> None:
        from harle.vault_imports.notion import NotionImportSource

        src = NotionImportSource()
        with pytest.raises(NotImplementedError):
            _run(src.extract({"mode": "reference"}))

    def test_extract_api_mode_returns_items_from_mocked_client(self) -> None:
        """With mocked client: one standalone page and one database (table mode) yield expected ImportItems."""
        from harle.vault_imports.notion import NotionImportSource

        async def search_pages():
            return [
                {
                    "id": "standalone-1",
                    "parent": {"type": "page_id"},
                    "url": "https://notion.so/s1",
                    "properties": {"title": {"type": "title", "title": [{"plain_text": "Standalone"}]}},
                    "created_time": "2025-01-01T00:00:00Z",
                    "last_edited_time": "2025-01-02T00:00:00Z",
                },
            ]

        async def search_dbs():
            return [{"id": "db1", "url": "https://notion.so/db1"}]

        async def get_page(page_id):
            return {
                "id": page_id,
                "url": "https://notion.so/s1",
                "properties": {"title": {"type": "title", "title": [{"plain_text": "Standalone"}]}},
            }

        async def get_blocks(block_id):
            return [{"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Body"}]}}]

        async def get_database(db_id):
            return {
                "id": db_id,
                "title": [{"plain_text": "Tasks"}],
                "properties": {"Name": {"id": "n1", "type": "title"}},
            }

        async def get_rows(db_id, schema, filter_obj=None, max_rows=None):
            return [
                {"_page_id": "row1", "_url": "", "Name": [{"plain_text": "Task One"}]},
            ]

        mock_client = AsyncMock()
        mock_client.search_all_pages = search_pages
        mock_client.search_all_databases = search_dbs
        mock_client.get_page = get_page
        mock_client.get_blocks = get_blocks
        mock_client.get_database = get_database
        mock_client.get_database_rows_with_properties = get_rows

        src = NotionImportSource()
        src._client = mock_client

        items = _run(src.extract({"mode": "api", "database_import_mode": "table"}))

        assert len(items) >= 1
        page_items = [i for i in items if "notion/pages/" in i.suggested_path]
        db_items = [i for i in items if "notion/databases/" in i.suggested_path]
        assert len(page_items) == 1
        assert page_items[0].title == "Standalone"
        assert len(db_items) == 1
        assert "Tasks" in db_items[0].title or "tasks" in db_items[0].suggested_path.lower()
