"""YAML frontmatter parser for Markdown files.

Extracts the YAML metadata block delimited by ``---`` fences at the
top of a Markdown file and returns it as a dictionary alongside the
remaining body content.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def parse_frontmatter(content: str, source_path: str | None = None) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from a Markdown string.

    Args:
        content: Raw file content, possibly starting with a ``---``
            fenced YAML block.
        source_path: Optional path or identifier for the content (e.g. relative
            file path), used in warning messages when parsing fails.

    Returns:
        A tuple of ``(metadata_dict, body_text)``.  If no valid
        frontmatter is found, ``metadata_dict`` is an empty dict
        and ``body_text`` is the original content unchanged.
    """
    if not content.startswith("---"):
        return {}, content

    lines = content.split("\n")

    # Find the closing --- (must be on its own line after the opening one)
    end_line: int | None = None
    for idx, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_line = idx
            break

    if end_line is None:
        return {}, content

    yaml_block = "\n".join(lines[1:end_line])
    body = "\n".join(lines[end_line + 1 :]).strip()

    try:
        metadata = yaml.safe_load(yaml_block)
    except yaml.YAMLError as e:
        location = f" in {source_path}" if source_path else ""
        logger.warning(
            "Failed to parse YAML frontmatter%s; treating as plain content. %s",
            location,
            e,
        )
        return {}, content

    if not isinstance(metadata, dict):
        return {}, content

    return metadata, body


def dump_frontmatter_fields(data: dict[str, Any]) -> str:
    """Serialize *data* to YAML-safe frontmatter lines.

    String values are emitted as JSON double-quoted scalars so values
    containing ``:`` (e.g. ``Tool: name``) or newlines do not break YAML
    parsing when files are read back.
    """
    lines: list[str] = []
    for key, val in data.items():
        if isinstance(val, str):
            lines.append(f"{key}: {json.dumps(val)}")
        elif isinstance(val, bool):
            lines.append(f"{key}: {'true' if val else 'false'}")
        elif isinstance(val, int):
            lines.append(f"{key}: {val}")
        elif val is None:
            lines.append(f"{key}: null")
        else:
            lines.append(f"{key}: {json.dumps(val, default=str)}")
    return "\n".join(lines)
