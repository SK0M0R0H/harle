"""Dummy import source — produces hardcoded ImportItems for testing the pipeline."""

from __future__ import annotations

from harle.vault_imports.base import (
    BaseImportSource,
    ContentType,
    ImportItem,
)


class DummyImportSource(BaseImportSource):
    """A minimal import source used to verify the registry and pipeline.

    Supports 'file' mode only. Produces one or two fixed Markdown items
    so that run_import can be exercised end-to-end without external data.
    """

    @property
    def name(self) -> str:
        return "dummy"

    @property
    def description(self) -> str:
        return "Dummy import source for testing the import infrastructure"

    def supported_modes(self) -> list[str]:
        return ["file"]

    async def validate_input(self, config: dict) -> list[str]:
        errors: list[str] = []
        mode = config.get("mode", "file")
        if mode != "file":
            errors.append("Dummy source only supports mode 'file'")
        return errors

    async def extract(self, config: dict) -> list[ImportItem]:
        # suggested_path is relative; pipeline will prepend target_dir
        items = [
            ImportItem(
                source_id="dummy-1",
                title="Dummy Import Note",
                content="This is a dummy import item for testing the pipeline.",
                content_type=ContentType.MARKDOWN,
                suggested_path="dummy/dummy_note.md",
                tags=["dummy", "imported", "test"],
                context=config.get("context", "personal"),
                metadata={"dummy": True},
            ),
            ImportItem(
                source_id="dummy-2",
                title="Second Dummy Note",
                content="Another hardcoded item to verify multi-item import.",
                content_type=ContentType.MARKDOWN,
                suggested_path="dummy/second_note.md",
                tags=["dummy", "imported"],
                context=config.get("context", "personal"),
            ),
        ]
        return items

    def default_config(self) -> dict:
        return {
            "mode": "file",
            "context": "personal",
            "target_dir": "knowledge/",
        }
