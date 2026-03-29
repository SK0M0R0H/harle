"""Logging components for the Orchestrator.

Run Logger registers each execution (`RunArtifact`) for merge into a single vault
``logs/`` file (with the execution trace when vault tracing is enabled).
Run metadata is persisted to the ``runs`` table when the indexer is available.
"""

from harle.logging.run_logger import log_run_to_vault

__all__ = ["log_run_to_vault"]
