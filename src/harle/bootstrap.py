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
# Default vault Markdown — ``harle/bootstrap_data/agent_prompts/*.md`` (role prompts)
# and ``harle/bootstrap_data/vault_seeds/<path>`` (policies, examples, knowledge).
# Packaged with the ``harle`` distribution; agent prompts are also copied into E2E vaults.
# ---------------------------------------------------------------------------

_AGENT_PROMPT_ROLES: tuple[str, ...] = (
    "assistant",
    "researcher",
    "secretary",
    "specialist",
    "writer",
)


def _agent_prompts_dir() -> Path:
    """Directory containing ``{role}.md`` files copied to ``prompts/`` in the vault."""
    return Path(__file__).resolve().parent / "bootstrap_data" / "agent_prompts"


def agent_prompts_source_dir() -> Path:
    """Public path to packaged role prompt ``*.md`` files (bootstrap seeds and E2E copies)."""
    return _agent_prompts_dir()


# Exposed for tests / tooling that must stay in sync with :func:`_load_agent_prompt_seeds`.
AGENT_PROMPT_SEED_ROLES: tuple[str, ...] = _AGENT_PROMPT_ROLES


def _load_agent_prompt_seeds() -> dict[str, str]:
    """Read agent role prompts from disk for :data:`SEED_FILES`."""
    base = _agent_prompts_dir()
    out: dict[str, str] = {}
    for role in _AGENT_PROMPT_ROLES:
        path = base / f"{role}.md"
        if not path.is_file():
            raise FileNotFoundError(
                f"Missing agent prompt seed file: {path}",
            )
        out[f"prompts/{role}.md"] = path.read_text(encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Other default vault Markdown — ``harle/bootstrap_data/vault_seeds/<path>``
# (same relative paths as under the vault root).
# ---------------------------------------------------------------------------

_VAULT_SEED_RELATIVE_PATHS: tuple[str, ...] = (
    "policies/privacy.md",
    "policies/tools-allowlist.md",
    "examples/good-goals.md",
    "knowledge/work/getting-started.md",
)


def _vault_seeds_dir() -> Path:
    return Path(__file__).resolve().parent / "bootstrap_data" / "vault_seeds"


def _load_vault_seed_files() -> dict[str, str]:
    """Read non-prompt seed Markdown from disk for :data:`SEED_FILES`."""
    base = _vault_seeds_dir()
    out: dict[str, str] = {}
    for rel in _VAULT_SEED_RELATIVE_PATHS:
        path = base / rel
        if not path.is_file():
            raise FileNotFoundError(
                f"Missing vault seed file: {path}",
            )
        out[rel] = path.read_text(encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Seed files — minimal dataset that demonstrates the vault structure
# and gives agents something to work with on day one.
# ---------------------------------------------------------------------------

SEED_FILES: dict[str, str] = {
    **_load_agent_prompt_seeds(),
    **_load_vault_seed_files(),
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
