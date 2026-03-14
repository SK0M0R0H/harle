"""Convert Notion API objects to Markdown.

Handles block trees, rich-text arrays, property values, and
full database-to-Markdown rendering (table or per-page).
"""

from __future__ import annotations

from typing import Any

MAX_CELL_LENGTH = 200


# ---------------------------------------------------------------------------
# Rich-text helpers
# ---------------------------------------------------------------------------


def rich_text_to_markdown(rich_text: list[dict[str, Any]]) -> str:
    """Convert a Notion ``rich_text`` array to a Markdown string.

    Handles bold, italic, code, strikethrough, underline, links,
    and color annotations.
    """
    parts: list[str] = []
    for segment in rich_text:
        text = segment.get("plain_text", "")
        if not text:
            continue

        href = segment.get("href")
        annotations = segment.get("annotations", {})

        if annotations.get("code"):
            text = f"`{text}`"
        if annotations.get("bold"):
            text = f"**{text}**"
        if annotations.get("italic"):
            text = f"*{text}*"
        if annotations.get("strikethrough"):
            text = f"~~{text}~~"
        if annotations.get("underline") and not href:
            text = f"<u>{text}</u>"

        if href:
            text = f"[{text}]({href})"

        parts.append(text)
    return "".join(parts)


def rich_text_to_plain(rich_text: list[dict[str, Any]]) -> str:
    """Extract plain text from a ``rich_text`` array (no formatting)."""
    return "".join(seg.get("plain_text", "") for seg in rich_text)


# ---------------------------------------------------------------------------
# Block → Markdown
# ---------------------------------------------------------------------------

def _indent(text: str, level: int) -> str:
    """Indent every line of *text* by *level* x 4 spaces."""
    if level <= 0:
        return text
    prefix = "    " * level
    return "\n".join(prefix + line for line in text.split("\n"))


def _convert_block(block: dict[str, Any], depth: int = 0) -> str:
    """Convert a single Notion block (and its children) to Markdown."""
    btype = block.get("type", "")
    data = block.get(btype, {})

    text = ""
    if btype == "paragraph":
        text = rich_text_to_markdown(data.get("rich_text", []))

    elif btype in ("heading_1", "heading_2", "heading_3"):
        level = int(btype[-1])
        content = rich_text_to_markdown(data.get("rich_text", []))
        text = f"{'#' * level} {content}"

    elif btype == "bulleted_list_item":
        content = rich_text_to_markdown(data.get("rich_text", []))
        text = f"- {content}"

    elif btype == "numbered_list_item":
        content = rich_text_to_markdown(data.get("rich_text", []))
        text = f"1. {content}"

    elif btype == "to_do":
        content = rich_text_to_markdown(data.get("rich_text", []))
        checked = "x" if data.get("checked") else " "
        text = f"- [{checked}] {content}"

    elif btype == "toggle":
        content = rich_text_to_markdown(data.get("rich_text", []))
        text = f"<details><summary>{content}</summary>\n"

    elif btype == "code":
        content = rich_text_to_plain(data.get("rich_text", []))
        lang = data.get("language", "")
        text = f"```{lang}\n{content}\n```"

    elif btype == "quote":
        content = rich_text_to_markdown(data.get("rich_text", []))
        text = "\n".join(f"> {line}" for line in content.split("\n"))

    elif btype == "callout":
        icon = data.get("icon", {})
        emoji = icon.get("emoji", "") if icon else ""
        content = rich_text_to_markdown(data.get("rich_text", []))
        text = f"> {emoji} {content}".strip()

    elif btype == "divider":
        text = "---"

    elif btype == "image":
        img_data = data.get("file", data.get("external", {}))
        url = img_data.get("url", "")
        caption = rich_text_to_plain(data.get("caption", []))
        text = f"![{caption}]({url})"

    elif btype == "bookmark":
        url = data.get("url", "")
        caption = rich_text_to_plain(data.get("caption", []))
        label = caption or url
        text = f"[{label}]({url})"

    elif btype == "table":
        text = _convert_table_block(block)

    elif btype == "equation":
        expression = data.get("expression", "")
        text = f"$$\n{expression}\n$$"

    elif btype == "child_page":
        title = data.get("title", "")
        text = f"**[Child page: {title}]**"

    elif btype == "child_database":
        title = data.get("title", "")
        text = f"**[Child database: {title}]**"

    elif btype == "table_row":
        return ""

    else:
        content = rich_text_to_markdown(data.get("rich_text", []))
        if content:
            text = content

    children = block.get("children", [])
    if children:
        child_md = blocks_to_markdown(children, depth=depth + 1)
        if btype == "toggle":
            text += f"\n{child_md}\n</details>"
        elif child_md:
            text += "\n" + _indent(child_md, 1)

    return text


def _convert_table_block(block: dict[str, Any]) -> str:
    """Convert a Notion table block (with table_row children) to Markdown."""
    rows = block.get("children", [])
    if not rows:
        return ""

    md_rows: list[str] = []
    for i, row_block in enumerate(rows):
        cells = row_block.get("table_row", {}).get("cells", [])
        cell_texts = [rich_text_to_markdown(cell) for cell in cells]
        md_rows.append("| " + " | ".join(cell_texts) + " |")
        if i == 0:
            md_rows.append("| " + " | ".join("---" for _ in cell_texts) + " |")

    return "\n".join(md_rows)


def blocks_to_markdown(
    blocks: list[dict[str, Any]],
    depth: int = 0,
) -> str:
    """Convert a list of Notion blocks into a Markdown string.

    Args:
        blocks: List of Notion block objects (with optional ``children``).
        depth: Nesting depth for indentation.

    Returns:
        Rendered Markdown string.
    """
    parts: list[str] = []
    for block in blocks:
        md = _convert_block(block, depth=depth)
        if md:
            parts.append(md)
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Property value → string
# ---------------------------------------------------------------------------


def property_value_to_string(
    property_type: str,
    value: Any,
) -> str:
    """Convert a Notion property value to a display string.

    Args:
        property_type: The Notion property type name (e.g. ``"title"``,
            ``"rich_text"``, ``"select"``).
        value: The raw property value payload from the Notion API.

    Returns:
        Human-readable string representation.
    """
    if value is None:
        return ""

    if property_type in ("title", "rich_text"):
        if isinstance(value, list):
            return rich_text_to_plain(value)
        rt = value.get("results", value.get("rich_text", []))
        if isinstance(rt, list):
            return rich_text_to_plain(rt)
        return str(value)

    if property_type == "number":
        num = value if not isinstance(value, dict) else value.get("number")
        return str(num) if num is not None else ""

    if property_type == "select":
        sel = value
        if isinstance(sel, dict) and "select" in sel:
            sel = sel["select"]
        if isinstance(sel, dict):
            return sel.get("name", "")
        return ""

    if property_type == "multi_select":
        opts = value if isinstance(value, list) else value.get("multi_select", [])
        if isinstance(opts, list):
            return ", ".join(o.get("name", "") for o in opts if isinstance(o, dict))
        return ""

    if property_type == "date":
        d = value
        if isinstance(d, dict) and "date" in d:
            d = d["date"]
        if isinstance(d, dict):
            start = d.get("start", "")
            end = d.get("end")
            return f"{start} → {end}" if end else str(start)
        return ""

    if property_type == "checkbox":
        val = value if isinstance(value, bool) else value.get("checkbox", False)
        return "Yes" if val else "No"

    if property_type in ("url", "email", "phone_number"):
        if isinstance(value, str):
            return value
        return str(value.get(property_type, ""))

    if property_type == "people":
        people = value if isinstance(value, list) else value.get("results", value.get("people", []))
        if isinstance(people, list):
            names = []
            for p in people:
                if isinstance(p, dict):
                    names.append(p.get("name", p.get("id", "")))
            return ", ".join(names)
        return ""

    if property_type == "files":
        files = value if isinstance(value, list) else value.get("files", [])
        if isinstance(files, list):
            urls: list[str] = []
            for f in files:
                if isinstance(f, dict):
                    url = f.get("file", f.get("external", {})).get("url", "")
                    if url:
                        urls.append(url)
            return ", ".join(urls)
        return ""

    if property_type == "formula":
        f = value if not isinstance(value, dict) else value.get("formula", value)
        if isinstance(f, dict):
            ftype = f.get("type", "")
            return str(f.get(ftype, ""))
        return str(f)

    if property_type == "relation":
        rels = value if isinstance(value, list) else value.get("results", value.get("relation", []))
        if isinstance(rels, list):
            return ", ".join(r.get("id", "") for r in rels if isinstance(r, dict))
        return ""

    if property_type == "rollup":
        r = value if not isinstance(value, dict) else value.get("rollup", value)
        if isinstance(r, dict):
            rtype = r.get("type", "")
            return str(r.get(rtype, ""))
        return str(r)

    if property_type == "status":
        s = value
        if isinstance(s, dict) and "status" in s:
            s = s["status"]
        if isinstance(s, dict):
            return s.get("name", "")
        return ""

    if property_type in ("created_time", "last_edited_time"):
        if isinstance(value, str):
            return value
        return str(value.get(property_type, ""))

    if property_type in ("created_by", "last_edited_by"):
        user = value if not isinstance(value, dict) else value.get(property_type, value)
        if isinstance(user, dict):
            return user.get("name", user.get("id", ""))
        return ""

    return str(value) if value else ""


# ---------------------------------------------------------------------------
# Page property metadata extraction
# ---------------------------------------------------------------------------


def extract_page_title(page: dict[str, Any]) -> str:
    """Extract the title from a Notion page object.

    Searches through ``properties`` for the title-type property.
    """
    props = page.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "title":
            return rich_text_to_plain(prop.get("title", []))
    return "Untitled"


def extract_database_title(db: dict[str, Any]) -> str:
    """Extract the title from a Notion database object.

    Database API returns ``title`` as a rich_text array.
    """
    title_arr = db.get("title", [])
    if isinstance(title_arr, list) and title_arr:
        return "".join(t.get("plain_text", "") for t in title_arr)
    return "Untitled Database"


def page_properties_to_metadata(
    resolved_props: dict[str, Any],
    schema: dict[str, dict],
) -> dict[str, str]:
    """Convert resolved property values to a flat metadata dict.

    Args:
        resolved_props: Mapping of column name to resolved property value.
        schema: Database schema mapping column name to ``{id, type, ...}``.

    Returns:
        Flat dict suitable for frontmatter metadata.
    """
    meta: dict[str, str] = {}
    for col_name, value in resolved_props.items():
        col_type = schema.get(col_name, {}).get("type", "rich_text")
        rendered = property_value_to_string(col_type, value)
        if rendered:
            meta[col_name] = rendered
    return meta


# ---------------------------------------------------------------------------
# Database → Markdown
# ---------------------------------------------------------------------------


def _truncate(text: str, max_len: int = MAX_CELL_LENGTH) -> str:
    """Truncate *text* to *max_len* characters with ellipsis."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _escape_pipe(text: str) -> str:
    """Escape pipe characters for Markdown tables."""
    return text.replace("|", "\\|")


def database_to_markdown_table(
    schema: dict[str, dict],
    rows: list[dict[str, Any]],
) -> str:
    """Render a Notion database as a Markdown table.

    Args:
        schema: Database schema mapping column name to ``{id, type, ...}``.
        rows: List of enriched row dicts (column name → resolved value).

    Returns:
        Markdown table string.
    """
    columns = list(schema.keys())
    if not columns:
        return ""

    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    lines = [header, separator]

    for row in rows:
        cells: list[str] = []
        for col in columns:
            col_type = schema[col].get("type", "rich_text")
            raw = row.get(col)
            rendered = property_value_to_string(col_type, raw)
            cells.append(_escape_pipe(_truncate(rendered)))
        lines.append("| " + " | ".join(cells) + " |")

    return "\n".join(lines)
