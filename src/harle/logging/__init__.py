"""Logging components for the Orchestrator.

Run Logger records each execution to the vault ``logs/`` directory
and (when the indexer is available) to the ``runs`` table.
"""

from harle.logging.run_logger import log_run_to_vault

__all__ = ["log_run_to_vault"]
