"""Profile Writer — write capture results to the vault with frontmatter and merge.

Handles directory creation, frontmatter generation, and section-based
merge when updating existing vault files.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from harle.dataset.frontmatter import parse_frontmatter


@dataclass
class CaptureOutput:
    """A single vault document produced by the Capture Engine."""

    topic_id: str
    title: str
    content: str
    tags: list[str]
    context: str
    vault_path: str
    is_update: bool = False


def _frontmatter_to_yaml(fm: dict) -> str:
    """Serialize frontmatter dict to YAML string (no document start)."""
    return yaml.dump(
        fm,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    ).strip()


def _section_heading(line: str) -> str | None:
    """Return the heading text for a line if it is a ## or # heading, else None."""
    m = re.match(r"^#{1,6}\s+(.+)$", line.strip())
    return m.group(1).strip() if m else None


def _split_sections(body: str) -> list[tuple[str, str]]:
    """Split body into (heading, section_content) by ## or #.

    First element may have empty heading if content before first heading.
    """
    sections: list[tuple[str, str]] = []
    current_heading = ""
    current_lines: list[str] = []
    for line in body.split("\n"):
        h = _section_heading(line)
        if h is not None:
            if current_heading or current_lines:
                sections.append((current_heading, "\n".join(current_lines).strip()))
            current_heading = h
            current_lines = [line]
        else:
            current_lines.append(line)
    if current_heading or current_lines:
        sections.append((current_heading, "\n".join(current_lines).strip()))
    return sections


def _merge_sections(
    existing_sections: list[tuple[str, str]],
    new_sections: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Merge new sections into existing by heading. Replace same heading, append new."""
    new_by_heading = {h: c for h, c in new_sections}
    result: list[tuple[str, str]] = [
        (h, new_by_heading.get(h, c)) for h, c in existing_sections
    ]
    existing_headings = {h for h, _ in existing_sections}
    for h, c in new_sections:
        if h not in existing_headings:
            result.append((h, c))
    return result


def _sections_to_body(sections: list[tuple[str, str]]) -> str:
    """Reassemble sections into a single body string."""
    parts: list[str] = []
    for heading, content in sections:
        if content:
            parts.append(content)
    return "\n\n".join(parts)


class ProfileWriter:
    """Writes capture outputs to the vault; merges with existing content when is_update."""

    def __init__(self, vault_root: Path | str) -> None:
        self._vault_root = Path(vault_root).resolve()

    def _path_inside_vault(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self._vault_root)
            return True
        except ValueError:
            return False

    async def write(
        self,
        output: CaptureOutput,
        vault_path: Path | None = None,
    ) -> str:
        """Write a capture output to the vault.

        If the file exists and is_update is True, merge new content with
        existing (section-based). If the file does not exist, create it
        with full frontmatter.

        vault_path: vault root; defaults to self._vault_root.

        Returns the vault-relative path of the written file.
        """
        root = vault_path if vault_path is not None else self._vault_root
        root = Path(root).resolve()
        file_path = root / output.vault_path
        if not self._path_inside_vault(file_path):
            raise ValueError(f"Path outside vault: {output.vault_path}")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        today = date.today().isoformat()
        if file_path.exists() and output.is_update:
            existing_raw = file_path.read_text(encoding="utf-8")
            merged_body = await self.merge_content(
                existing_raw,
                output.content,
                output.topic_id,
            )
            meta, _ = parse_frontmatter(existing_raw)
            meta["last_updated"] = today
            if "title" not in meta:
                meta["title"] = output.title
            if "tags" not in meta:
                meta["tags"] = output.tags
            if "context" not in meta:
                meta["context"] = output.context
            if "summary" not in meta:
                summary = (output.content[:200] + "…") if len(output.content) > 200 else output.content
                meta["summary"] = summary
            full = "---\n" + _frontmatter_to_yaml(meta) + "\n---\n\n" + merged_body
            file_path.write_text(full, encoding="utf-8")
        else:
            summary = (output.content[:200] + "…") if len(output.content) > 200 else output.content
            fm = {
                "title": output.title,
                "tags": output.tags,
                "context": output.context,
                "last_updated": today,
                "summary": summary,
            }
            full = "---\n" + _frontmatter_to_yaml(fm) + "\n---\n\n" + output.content
            file_path.write_text(full, encoding="utf-8")
        return output.vault_path

    async def merge_content(
        self,
        existing: str,
        new_content: str,
        topic_id: str,
    ) -> str:
        """Merge new capture content with an existing vault file.

        Strategy: parse both into sections by heading; for each new section,
        replace matching section in existing or append; preserve existing
        frontmatter (caller updates last_updated). Phase 1 does not detect
        manually edited sections — all matching headings are replaced.
        """
        _, existing_body = parse_frontmatter(existing)
        new_body = new_content
        if not new_body.strip():
            return existing_body
        existing_sections = _split_sections(existing_body)
        new_sections = _split_sections(new_body)
        merged = _merge_sections(existing_sections, new_sections)
        return _sections_to_body(merged)
