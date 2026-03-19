"""System initialisation: database tables, dataset seeding, and first index.

Provides both a programmatic API (called from the ``/init`` endpoint)
and a standalone CLI entry-point (``harle-init``) for first-time setup.

Seed files follow the Section 2 guidelines from
``data_layer_best_practices.md``: YAML frontmatter, heading hierarchy,
one-sentence summaries, and structured content.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from sqlalchemy import inspect, select

from harle.dataset.reader import DatasetReader
from harle.db.connection import Database
from harle.db.models import Base, FileIndex
from harle.indexing.indexer import Indexer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Seed files — minimal dataset that demonstrates the vault structure
# and gives agents something to work with on day one.
# ---------------------------------------------------------------------------

SEED_FILES: dict[str, str] = {
    "prompts/researcher.md": """\
---
title: "Researcher Agent Prompt"
tags: [prompt, researcher, agent, role]
context: global
priority: P0
last_updated: 2026-02-17
---

# Researcher Agent Prompt

Defines the identity, behaviour, and constraints of the Researcher agent role.

## Role Definition

You are a Researcher agent for Harle. Your primary function is to find,
analyse, and synthesise information from the user's dataset and external
sources to produce structured research outputs.

## Core Behaviours

- Search the dataset thoroughly before using external sources
- Cite specific files when referencing dataset content
- For simple factual questions (e.g. "When will X be available?", "Is Y supported?"), give the answer in the first sentence or two, then optionally add brief detail
- For broad or multi-topic research, present findings in structured format with clear sections
- Flag when information is insufficient and suggest what additional data would help only when it is actually missing
- Maintain objectivity — present evidence, not opinions

## Output Format

- Use Markdown with clear heading hierarchy when the response is long or multi-topic
- For short factual answers: state the answer first (e.g. "Private L3 is planned for Q4 2026"), then one or two sentences of context if needed; do not use Executive Summary / Key Findings / Suggested Additional Data for every reply
- For research reports only: include a one-paragraph executive summary at the top, bullet points for key findings, and a "Sources" section listing files and URLs used

## Constraints

- Do not fabricate information — clearly distinguish facts from inferences
- Respect context boundaries (work data stays in work scope)
- Request approval before writing research outputs to the dataset
""",
    "prompts/secretary.md": """\
---
title: "Secretary Agent Prompt"
tags: [prompt, secretary, agent, role]
context: global
priority: P0
last_updated: 2026-02-17
---

# Secretary Agent Prompt

Defines the identity, behaviour, and constraints of the Secretary agent role.

## Role Definition

You are a Secretary agent for Harle. Your primary function is to help the
user manage tasks, organise information, and handle routine operational work.

## Core Behaviours

- Check the user's task boards and calendars before answering scheduling questions
- Use the user's preferred formats and conventions (check memories and policies)
- Proactively surface relevant context from the dataset
- Keep responses concise and actionable
- Ask for clarification when a request is ambiguous

## Output Format

- Use bullet points for task lists and action items
- Include deadlines and priorities when available
- Provide brief status summaries, not lengthy reports

## Constraints

- Follow all policies in the policies/ directory
- Do not modify prompts/ or policies/ files without explicit approval
- Log significant actions to the logs/ directory
""",
    "policies/privacy.md": """\
---
title: "Privacy Policy"
tags: [policy, privacy, security, data-protection]
context: global
priority: P0
last_updated: 2026-02-17
---

# Privacy Policy

Core privacy rules that all agents must follow during every operation.

## General Rules

- Never share personal data with external services unless explicitly approved
- Work context data must not appear in personal context responses
- Personal context data must not appear in work context responses
- Do not include real names in any content shared externally

## Data Classification

- **Private**: Health notes, financial data, personal credentials — never include in any agent output
- **Internal**: Work project details, internal decisions — share only within the matching context scope
- **Open**: General knowledge, public information — can be referenced freely

## Agent Behaviour

- When uncertain about data sensitivity, ask the user before including it
- Log which files were accessed in each run for auditability
- Do not cache or store conversation content beyond the current session unless explicitly saving to the dataset
""",
    "policies/tools-allowlist.md": """\
---
title: "Tools Allowlist"
tags: [policy, tools, security, permissions]
context: global
priority: P0
last_updated: 2026-02-17
---

# Tools Allowlist

Defines which external tools and integrations each agent role is permitted to use.

## Researcher Agent

- **Dataset search**: always allowed
- **Web search**: allowed for work and personal contexts
- **File write**: requires approval (writes to knowledge/ or logs/)

## Secretary Agent

- **Dataset search**: always allowed
- **Trello integration**: allowed for work context only
- **File write**: allowed for logs/ without approval; requires approval for other directories

## All Agents

- **Dataset read**: always allowed for files matching the active context scope
- **External API calls**: require explicit user approval on first use per session
- **File deletion**: never allowed without explicit approval
""",
    "examples/good-goals.md": """\
---
title: "Examples of Well-Defined Task Requests"
tags: [example, goals, best-practices]
context: global
priority: P2
last_updated: 2026-02-17
---

# Examples of Well-Defined Task Requests

Reference examples showing how to write clear, actionable requests for Harle agents.

## Good Request Format

A well-defined request includes:

- **Action**: what you want done (research, summarise, create, update)
- **Scope**: what data or domain to focus on
- **Output**: what the result should look like
- **Constraints**: any limits or requirements

## Examples

### Research Request

> "Research potential privacy solutions for institutional clients that are
> compatible with our L2 architecture. Focus on zero-knowledge approaches.
> Output a structured report with pros/cons for each option."

### Task Management Request

> "Check all Trello cards in the 'Work Q1' board that have been in
> 'In Progress' for more than 7 days. Summarise each stalled task with
> the card name, assignee, and days stalled."

### Knowledge Update Request

> "Update the Japan trip planning document with flight options from Tokyo
> to Osaka on March 15-16. Include bullet-train alternatives with
> approximate costs."
""",
    "knowledge/work/getting-started.md": """\
---
title: "Getting Started with Harle"
tags: [knowledge, harle, onboarding, getting-started]
context: work
priority: P1
last_updated: 2026-02-17
---

# Getting Started with Harle

A quick reference for how to use the Harle personal assistant system.

## What Harle Does

Harle is a personal AI assistant that operates over your own dataset. Unlike
generic chatbots, Harle knows your files, rules, preferences, and past decisions.

## Key Concepts

- **Dataset**: Your Markdown files organised in prompts/, policies/, workflows/, knowledge/, examples/, and logs/
- **Context**: Every request runs in a scope — work or personal — that controls which files the agent can see
- **Agents**: Researcher, Secretary, and Specialist roles each optimised for different tasks

## How to Add Your Own Content

1. Create Markdown files in the appropriate directory
2. Add YAML frontmatter with title, tags, and context
3. Run re-indexing to make new files searchable
""",
}

# Directories that must exist in the vault even if no seed files live there.
SEED_DIRECTORIES: list[str] = [
    "prompts",
    "policies",
    "workflows",
    "knowledge",
    "knowledge/work",
    "knowledge/personal",
    "examples",
    "logs",
]


def create_tables(db: Database) -> None:
    """Create all PostgreSQL tables defined in :mod:`harle.db.models`.

    Safe to call repeatedly — existing tables are not dropped.

    Args:
        db: Initialised :class:`Database` instance.
    """
    db.create_tables()
    logger.info("Database tables ensured.")


def seed_dataset(dataset_path: str) -> int:
    """Create the vault directory structure and write seed files.

    Skips files that already exist so calling this multiple times is
    safe.

    Args:
        dataset_path: Absolute path to the vault root.

    Returns:
        Number of seed files written (excludes already-existing files).
    """
    root = Path(dataset_path)

    for directory in SEED_DIRECTORIES:
        (root / directory).mkdir(parents=True, exist_ok=True)

    written = 0
    for relative_path, content in SEED_FILES.items():
        target = root / relative_path
        if target.exists():
            logger.debug("Seed file already exists, skipping: %s", relative_path)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        logger.info("Created seed file: %s", relative_path)
        written += 1

    return written


def _sync_index(
    db: Database,
    dataset_path: str,
    whoosh_index_path: str | Path | None = None,
) -> int:
    """Run one indexer sync pass for *dataset_path* and return change count.

    When *whoosh_index_path* is set (Phase 2), the indexer will update
    the Whoosh index for added/updated/deleted files.
    """
    reader = DatasetReader(dataset_path)
    indexer = Indexer(db, reader, whoosh_index_path=whoosh_index_path)
    return indexer.sync()


def run_initial_index(
    db: Database,
    dataset_path: str,
    whoosh_index_path: str | Path | None = None,
) -> int:
    """Index all dataset files into the ``file_index`` table.

    Args:
        db: Initialised :class:`Database` instance.
        dataset_path: Absolute path to the vault root.
        whoosh_index_path: Optional Whoosh index path for Phase 2 sync.

    Returns:
        Number of file_index rows added or updated.
    """
    return _sync_index(db, dataset_path, whoosh_index_path=whoosh_index_path)


def _dataset_seed_ready(dataset_path: str) -> bool:
    """Return whether the expected vault structure and seed files already exist."""
    root = Path(dataset_path)
    if not root.exists() or not root.is_dir():
        return False

    directories_ready = all((root / directory).is_dir() for directory in SEED_DIRECTORIES)
    files_ready = all((root / relative_path).is_file() for relative_path in SEED_FILES)
    return directories_ready and files_ready


def _tables_exist(db: Database) -> bool:
    """Return whether all ORM tables are present in the configured database."""
    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())
    expected_tables = set(Base.metadata.tables)
    return expected_tables.issubset(existing_tables)


def _file_index_populated(db: Database) -> bool:
    """Return whether the ``file_index`` table contains at least one row."""
    if not _tables_exist(db):
        return False

    with db.session() as session:
        first_row = session.scalars(select(FileIndex.id).limit(1)).first()
    return first_row is not None


def ensure_initialized(db: Database, dataset_path: str) -> dict[str, object]:
    """Ensure DB tables, dataset seed, and initial index are in place.

    This is safe to run on every startup. It always ensures tables exist,
    then runs seeding/indexing only when the current environment indicates
    they are still missing.
    """
    create_tables(db)

    dataset_seed_ready = _dataset_seed_ready(dataset_path)
    files_seeded = 0 if dataset_seed_ready else seed_dataset(dataset_path)

    file_index_populated = _file_index_populated(db)
    should_index = files_seeded > 0 or not file_index_populated

    whoosh_path = _whoosh_index_path_if_enabled()
    files_indexed = (
        run_initial_index(db, dataset_path, whoosh_index_path=whoosh_path)
        if should_index
        else 0
    )
    if whoosh_path:
        _ensure_whoosh_index(dataset_path, whoosh_path)

    reader = DatasetReader(dataset_path)
    total_files = len(reader.list_files())

    return {
        "tables_created": True,
        "files_seeded": files_seeded,
        "files_indexed": files_indexed,
        "total_files": total_files,
        "dataset_path": dataset_path,
        "already_initialized": files_seeded == 0 and not should_index,
    }


def init_system(db: Database, dataset_path: str) -> dict[str, object]:
    """Run the complete first-time initialisation sequence.

    1. Create database tables.
    2. Seed the dataset with starter files.
    3. Index all files into PostgreSQL.

    Args:
        db: Initialised :class:`Database` instance.
        dataset_path: Absolute path to the vault root.

    Returns:
        Summary dict with counts of tables, seed files, and indexed files.
    """
    return ensure_initialized(db, dataset_path)


def _whoosh_index_path_if_enabled() -> Path | None:
    """Return Whoosh index path if search engine is whoosh, else None."""
    try:
        from harle.config import get_search_config
        config = get_search_config()
        if getattr(config, "engine", "whoosh") != "whoosh":
            return None
        path = getattr(config, "whoosh_index_path", "") or ""
        return Path(path).expanduser() if path else None
    except Exception:  # noqa: S110
        return None


def _ensure_whoosh_index(dataset_path: str, index_path: Path) -> None:
    """Build Whoosh from scratch if missing or on-disk schema is not current."""
    from harle.search import whoosh_index

    present = index_path.exists() and whoosh_index.exists_in(str(index_path))
    need_build = not present or not whoosh_index.disk_index_schema_current(index_path)
    if need_build:
        try:
            reader = DatasetReader(dataset_path)
            whoosh_index.build_from_scratch(reader, index_path)
            logger.info("Whoosh index built at %s", index_path)
        except Exception as e:
            logger.warning("Whoosh index build failed: %s", e)


def reindex_dataset(db: Database, dataset_path: str) -> dict[str, object]:
    """Re-index all dataset files without seeding or recreating tables.

    A lightweight alternative to :func:`init_system` for when new files
    have been added to the vault and just need to be picked up. When
    search engine is whoosh, the Whoosh index is updated and rebuilt
    if missing.

    Args:
        db: Initialised :class:`Database` instance.
        dataset_path: Absolute path to the vault root.

    Returns:
        Summary dict with the number of index changes and total files.
    """
    whoosh_path = _whoosh_index_path_if_enabled()
    changes = _sync_index(db, dataset_path, whoosh_index_path=whoosh_path)
    if whoosh_path:
        _ensure_whoosh_index(dataset_path, whoosh_path)
    reader = DatasetReader(dataset_path)
    total_files = len(reader.list_files())

    return {
        "files_indexed": changes,
        "total_files": total_files,
        "dataset_path": dataset_path,
    }


def run_init() -> None:
    """Standalone CLI entry-point for ``harle-init``.

    Reads settings from config, creates tables, seeds the dataset, and
    runs indexing.  Exits with code 1 on configuration errors.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    from harle.config import load_settings

    settings = load_settings()

    if not settings.DATABASE_URL:
        logger.error("DATABASE_URL is not configured. Set it in config.yaml or as an env var.")
        sys.exit(1)

    if not settings.HARLE_DATASET_PATH:
        logger.error(
            "HARLE_DATASET_PATH is not configured. Set it in config.yaml or as an env var."
        )
        sys.exit(1)

    db = Database(settings.DATABASE_URL)
    result = init_system(db, settings.HARLE_DATASET_PATH)

    logger.info("Initialisation complete.")
    logger.info("  Tables created: %s", result["tables_created"])
    logger.info("  Seed files written: %s", result["files_seeded"])
    logger.info("  Files indexed: %s", result["files_indexed"])
    logger.info("  Total files in dataset: %s", result["total_files"])
    logger.info("  Dataset path: %s", result["dataset_path"])


def run_reindex() -> None:
    """Standalone CLI entry-point for ``harle-reindex``.

    Reads settings from config and re-indexes the dataset without
    seeding or recreating tables.  Exits with code 1 on configuration
    errors.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    from harle.config import load_settings

    settings = load_settings()

    if not settings.DATABASE_URL:
        logger.error("DATABASE_URL is not configured. Set it in config.yaml or as an env var.")
        sys.exit(1)

    if not settings.HARLE_DATASET_PATH:
        logger.error(
            "HARLE_DATASET_PATH is not configured. Set it in config.yaml or as an env var."
        )
        sys.exit(1)

    db = Database(settings.DATABASE_URL)
    result = reindex_dataset(db, settings.HARLE_DATASET_PATH)

    logger.info("Re-index complete.")
    logger.info("  Files indexed: %s", result["files_indexed"])
    logger.info("  Total files in dataset: %s", result["total_files"])
    logger.info("  Dataset path: %s", result["dataset_path"])
