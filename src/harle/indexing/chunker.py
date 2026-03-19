"""Vault file chunking per Data Layer Best Practices §5.

Splits Markdown by file type and size: whole-file for prompts/policies/examples
and short knowledge; H2 sections for workflows and long knowledge;
paragraph chunks for logs. Produces cascading heading paths and optional
context blocks for indexing and assembly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from harle.context.tokenizer import count_tokens

# Default knowledge threshold (tokens) — below = whole file.
DEFAULT_KNOWLEDGE_TOKEN_THRESHOLD = 2000
DEFAULT_PARAGRAPH_MAX_TOKENS = 600


class ChunkStrategy(str, Enum):
    """How to split a file for indexing and retrieval."""

    WHOLE = "whole"
    SECTION_H2 = "section_h2"
    PARAGRAPH = "paragraph"


@dataclass(frozen=True)
class Chunk:
    """One searchable / retrievable unit."""

    file_path: str
    chunk_index: int
    heading_path: str
    content: str
    context_block: str
    token_count: int


def get_strategy(
    relative_path: str,
    token_count: int,
    *,
    chunking_enabled: bool = True,
    knowledge_token_threshold: int = DEFAULT_KNOWLEDGE_TOKEN_THRESHOLD,
) -> ChunkStrategy:
    """Return chunking strategy for a vault-relative path and size."""
    if not chunking_enabled:
        return ChunkStrategy.WHOLE

    path = relative_path.replace("\\", "/")
    if path.startswith("prompts/") or path.startswith("policies/") or path.startswith(
        "examples/"
    ):
        return ChunkStrategy.WHOLE
    if path.startswith("workflows/"):
        return ChunkStrategy.SECTION_H2
    if path.startswith("knowledge/"):
        if token_count < knowledge_token_threshold:
            return ChunkStrategy.WHOLE
        return ChunkStrategy.SECTION_H2
    if path.startswith("logs/"):
        return ChunkStrategy.PARAGRAPH
    return ChunkStrategy.WHOLE


def _document_title(body: str, frontmatter_title: str | None) -> str:
    if frontmatter_title and frontmatter_title.strip():
        return frontmatter_title.strip()
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            return stripped[2:].strip()
    return ""


def _first_sentence(text: str, max_len: int = 200) -> str:
    text = text.strip()
    if not text:
        return ""
    for sep in ".!?\n":
        idx = text.find(sep)
        if 0 < idx < max_len:
            return text[: idx + 1].strip()
    return (text[:max_len] + ("…" if len(text) > max_len else "")).strip()


def build_context_block(
    *,
    file_path: str,
    heading_path: str,
    tags: list[str],
    context: str | None,
    summary_line: str,
    contextual_enrichment: bool,
) -> str:
    """Build TRD §5.3-style metadata prefix for indexing."""
    if not contextual_enrichment:
        return ""
    tags_s = ", ".join(tags) if tags else ""
    ctx = (context or "").strip()
    parts = [
        f"[Source] {file_path}",
        f"[Section] {heading_path}",
        f"[Tags] {tags_s}",
        f"[Context] {ctx}",
        f"[Summary] {summary_line}",
    ]
    return "\n".join(parts) + "\n\n"


def chunk_file(
    *,
    content: str,
    title: str | None,
    tags: list[str],
    context: str | None,
    relative_path: str,
    strategy: ChunkStrategy,
    contextual_enrichment: bool = True,
    paragraph_max_tokens: int = DEFAULT_PARAGRAPH_MAX_TOKENS,
) -> list[Chunk]:
    """Produce chunks for body *content* (frontmatter already stripped)."""
    doc_title = _document_title(content, title) or relative_path
    if strategy == ChunkStrategy.WHOLE:
        return _whole_file_chunks(
            content=content,
            file_path=relative_path,
            doc_title=doc_title,
            tags=tags,
            context=context,
            contextual_enrichment=contextual_enrichment,
        )
    if strategy == ChunkStrategy.SECTION_H2:
        return _section_h2_chunks(
            content=content,
            file_path=relative_path,
            doc_title=doc_title,
            tags=tags,
            context=context,
            contextual_enrichment=contextual_enrichment,
        )
    return _paragraph_chunks(
        content=content,
        file_path=relative_path,
        doc_title=doc_title,
        tags=tags,
        context=context,
        contextual_enrichment=contextual_enrichment,
        paragraph_max_tokens=paragraph_max_tokens,
    )


def _whole_file_chunks(
    *,
    content: str,
    file_path: str,
    doc_title: str,
    tags: list[str],
    context: str | None,
    contextual_enrichment: bool,
) -> list[Chunk]:
    body = content.strip()
    summary = _first_sentence(body) or doc_title
    block = build_context_block(
        file_path=file_path,
        heading_path=doc_title,
        tags=tags,
        context=context,
        summary_line=summary,
        contextual_enrichment=contextual_enrichment,
    )
    tok = count_tokens(body)
    return [
        Chunk(
            file_path=file_path,
            chunk_index=0,
            heading_path=doc_title,
            content=body,
            context_block=block,
            token_count=tok,
        )
    ]


# Split on H2 at line start (Markdown ## heading).
_H2_SPLIT = re.compile(r"(?m)^## .+$")


def _section_h2_chunks(
    *,
    content: str,
    file_path: str,
    doc_title: str,
    tags: list[str],
    context: str | None,
    contextual_enrichment: bool,
) -> list[Chunk]:
    text = content
    matches = list(_H2_SPLIT.finditer(text))
    if not matches:
        return _whole_file_chunks(
            content=content,
            file_path=file_path,
            doc_title=doc_title,
            tags=tags,
            context=context,
            contextual_enrichment=contextual_enrichment,
        )

    chunks: list[Chunk] = []
    chunk_index = 0

    # Preamble before first ##
    first_h2_start = matches[0].start()
    preamble = text[:first_h2_start].strip()
    if preamble:
        hp = doc_title
        summary = _first_sentence(preamble) or hp
        block = build_context_block(
            file_path=file_path,
            heading_path=hp,
            tags=tags,
            context=context,
            summary_line=summary,
            contextual_enrichment=contextual_enrichment,
        )
        body = preamble.strip()
        chunks.append(
            Chunk(
                file_path=file_path,
                chunk_index=chunk_index,
                heading_path=hp,
                content=body,
                context_block=block,
                token_count=count_tokens(body),
            )
        )
        chunk_index += 1

    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section_text = text[start:end].strip()
        if not section_text:
            continue
        first_line = section_text.split("\n", 1)[0].strip()
        h2_title = first_line[3:].strip() if first_line.startswith("## ") else first_line
        heading_path = f"{doc_title} > {h2_title}" if doc_title else h2_title
        summary = _first_sentence(
            section_text.split("\n", 1)[1] if "\n" in section_text else section_text
        ) or heading_path
        block = build_context_block(
            file_path=file_path,
            heading_path=heading_path,
            tags=tags,
            context=context,
            summary_line=summary,
            contextual_enrichment=contextual_enrichment,
        )
        chunks.append(
            Chunk(
                file_path=file_path,
                chunk_index=chunk_index,
                heading_path=heading_path,
                content=section_text,
                context_block=block,
                token_count=count_tokens(section_text),
            )
        )
        chunk_index += 1

    if not chunks:
        return _whole_file_chunks(
            content=content,
            file_path=file_path,
            doc_title=doc_title,
            tags=tags,
            context=context,
            contextual_enrichment=contextual_enrichment,
        )
    return chunks


def _paragraph_chunks(
    *,
    content: str,
    file_path: str,
    doc_title: str,
    tags: list[str],
    context: str | None,
    contextual_enrichment: bool,
    paragraph_max_tokens: int,
) -> list[Chunk]:
    raw = content.strip()
    if not raw:
        return _whole_file_chunks(
            content=content,
            file_path=file_path,
            doc_title=doc_title,
            tags=tags,
            context=context,
            contextual_enrichment=contextual_enrichment,
        )

    paragraphs = re.split(r"\n\s*\n+", raw)
    merged: list[str] = []
    buf: list[str] = []
    buf_tokens = 0
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        t = count_tokens(p)
        if buf and buf_tokens + t > paragraph_max_tokens:
            merged.append("\n\n".join(buf))
            buf = [p]
            buf_tokens = t
        else:
            buf.append(p)
            buf_tokens += t
    if buf:
        merged.append("\n\n".join(buf))

    chunks: list[Chunk] = []
    for i, body in enumerate(merged):
        first_line = body.split("\n", 1)[0].strip()
        summary = first_line[:200] + ("…" if len(first_line) > 200 else "")
        hp = f"{doc_title} > Paragraph {i + 1}" if doc_title else f"Paragraph {i + 1}"
        block = build_context_block(
            file_path=file_path,
            heading_path=hp,
            tags=tags,
            context=context,
            summary_line=summary or hp,
            contextual_enrichment=contextual_enrichment,
        )
        chunks.append(
            Chunk(
                file_path=file_path,
                chunk_index=i,
                heading_path=hp,
                content=body,
                context_block=block,
                token_count=count_tokens(body),
            )
        )
    return chunks


def whoosh_doc_path(file_path: str, chunk_index: int, num_chunks: int) -> str:
    """Unique Whoosh document id for a chunk."""
    if num_chunks <= 1:
        return file_path
    return f"{file_path}#{chunk_index}"


def parse_whoosh_doc_path(doc_path: str) -> tuple[str, int | None]:
    """Split composite Whoosh path into (file_path, chunk_index or None)."""
    if "#" in doc_path:
        base, _, idx_s = doc_path.rpartition("#")
        try:
            return base, int(idx_s)
        except ValueError:
            return doc_path, None
    return doc_path, None
