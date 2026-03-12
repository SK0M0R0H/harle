"""Dataset writer — create and update files in the user vault.

Provides write operations for run logs and other agent outputs.
Agents writing to ``logs/`` may auto-approve; writes to
``prompts/`` or ``policies/`` always require user confirmation
(when approval flow is implemented).
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

LOGS_DIR = "logs"


def log_dir_for(timestamp: datetime) -> str:
    """Return vault-relative log directory ``logs/YYYY/MM`` for *timestamp*."""
    return f"{LOGS_DIR}/{timestamp.year:04d}/{timestamp.month:02d}"


def write_log_file(
    dataset_path: Path | str,
    relative_path: str,
    content: str,
) -> None:
    """Write a file under the dataset root, creating parent directories.

    Used by the Run Logger to write result and context files under
    ``logs/YYYY/MM/``. The path must be vault-relative (e.g.
    ``logs/2026/02/run_abc123_result.md``).

    Args:
        dataset_path: Absolute path to the vault root.
        relative_path: Path relative to the dataset root (forward slashes).
        content: Full file content (UTF-8).

    Raises:
        OSError: If the file cannot be written (e.g. permission denied).
    """
    root = Path(dataset_path)
    if not root.is_absolute():
        root = root.resolve()
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    logger.debug("Wrote log file: %s", relative_path)
