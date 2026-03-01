"""Conversion pipeline: ImportItem → vault-ready Markdown.

Transforms raw ImportItems from sources into full Markdown documents
with frontmatter, normalized content, and resolved vault paths.
Image processing is optional and can be injected; when absent,
IMAGE/STRUCTURED items are passed through with content as-is.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone

import yaml

from harle.vault_imports.base import (
    AccessInfo,
    ContentType,
    ImportItem,
)

logger = logging.getLogger(__name__)


@dataclass
class ConvertedItem:
    """A single item ready for the Vault Writer.

    Has a vault-relative path and full Markdown content (including
    frontmatter). source_id is used for deduplication and reporting.
    """

    relative_path: str
    content: str
    source_id: str


def _normalize_content(content: str) -> str:
    """Clean up content: strip, normalize newlines, remove leading/trailing blank lines."""
    if not content:
        return ""
    return content.strip().replace("\r\n", "\n").replace("\r", "\n")


def _build_frontmatter(
    item: ImportItem,
    source_name: str,
) -> dict:
    """Build YAML frontmatter for a vault file from an ImportItem."""
    fm: dict = {
        "title": item.title,
        "tags": list(item.tags) if item.tags else [],
        "context": item.context,
        "last_updated": date.today().isoformat(),
        "summary": (item.content[:200] + "…") if len(item.content) > 200 else item.content,
        "import_source": source_name,
        "import_source_id": item.source_id,
        "import_date": date.today().isoformat(),
    }
    if item.content_type == ContentType.REFERENCE and item.access_info is not None:
        fm["import_type"] = "reference"
        fm["access_via"] = item.access_info.tool_module
        fm["access_params"] = item.access_info.params
        if item.access_info.default_filter is not None:
            fm["access_params"] = {**fm["access_params"], "default_filter": item.access_info.default_filter}
    return fm


def _frontmatter_to_yaml(fm: dict) -> str:
    """Serialize frontmatter dict to YAML string (no document start)."""
    return yaml.dump(
        fm,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    ).strip()


def _resolve_path(suggested_path: str, target_dir: str) -> str:
    """Resolve vault-relative path: ensure under target_dir and ends with .md."""
    path = suggested_path.strip().strip("/")
    if not path:
        path = "imported.md"
    if not path.endswith(".md"):
        path = path.rstrip("/") + ".md"
    base = target_dir.strip().strip("/")
    if base:
        path = f"{base}/{path}" if base else path
    return path


def convert_item(
    item: ImportItem,
    source_name: str,
    target_dir: str = "knowledge/",
) -> ConvertedItem:
    """Convert a single ImportItem into a ConvertedItem.

    Applies content normalization, frontmatter generation, and path
    resolution. Does not run image processing (caller can inject that
    before calling this, or leave IMAGE content as-is).
    """
    content_normalized = _normalize_content(item.content)
    frontmatter = _build_frontmatter(item, source_name)
    body = f"# {item.title}\n\n{content_normalized}" if content_normalized else f"# {item.title}\n"
    yaml_block = _frontmatter_to_yaml(frontmatter)
    full_content = f"---\n{yaml_block}\n---\n\n{body}"
    relative_path = _resolve_path(item.suggested_path, target_dir)
    return ConvertedItem(
        relative_path=relative_path,
        content=full_content,
        source_id=item.source_id,
    )


def run_pipeline(
    items: list[ImportItem],
    source_name: str,
    target_dir: str = "knowledge/",
) -> list[ConvertedItem]:
    """Run the conversion pipeline on a list of ImportItems.

    Each item is normalized, given frontmatter, and a resolved path.
    Image processing is not applied (Phase 1: no image processor).
    """
    return [
        convert_item(item, source_name, target_dir)
        for item in items
    ]
