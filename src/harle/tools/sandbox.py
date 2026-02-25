"""Execution sandbox for tool calls that spawn subprocesses (Security Layer 4).

Wraps :func:`subprocess.run` with configurable resource limits so that
a tool call cannot exhaust the host's resources even if the LLM produces
a command that loops, allocates unbounded memory, or writes unlimited
output.

Resource limits
---------------
- ``timeout_seconds``  — wall-clock timeout (default 30 s).
- ``max_memory_mb``    — RSS memory cap via :mod:`resource` pre-exec
  hook (default 512 MB).  Linux only; silently skipped on other
  platforms.
- ``max_output_bytes`` — captured stdout + stderr size (default 1 MB).
- ``max_subprocesses`` — ``RLIMIT_NPROC`` delta (default 10).
  Linux only.

The sandbox is used by modules that execute external processes (e.g. the
future scripts module).  API-calling modules do not need it — they rely
on ``httpx`` timeouts instead.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SECONDS: int = 30
_DEFAULT_MAX_MEMORY_MB: int = 512
_DEFAULT_MAX_OUTPUT_BYTES: int = 1_048_576  # 1 MB
_DEFAULT_MAX_SUBPROCESSES: int = 10


@dataclass(frozen=True)
class SandboxConfig:
    """Resource limits for a sandboxed process.

    Args:
        timeout_seconds: Wall-clock timeout.
        max_memory_mb: RSS memory cap in megabytes.
        max_output_bytes: Max combined stdout + stderr capture.
        max_subprocesses: Max child processes (``RLIMIT_NPROC`` delta).
        working_directory: Working directory for the subprocess.
    """

    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS
    max_memory_mb: int = _DEFAULT_MAX_MEMORY_MB
    max_output_bytes: int = _DEFAULT_MAX_OUTPUT_BYTES
    max_subprocesses: int = _DEFAULT_MAX_SUBPROCESSES
    working_directory: str | None = None

    @classmethod
    def from_module_config(cls, config: dict) -> SandboxConfig:
        """Build from a module's config dict.

        Recognised keys: ``timeout_seconds``, ``max_memory_mb``,
        ``max_output_bytes``, ``max_subprocesses``, ``working_directory``.
        Missing keys fall back to defaults.

        Args:
            config: The module's full config dict.

        Returns:
            A :class:`SandboxConfig` instance.
        """
        return cls(
            timeout_seconds=config.get("timeout_seconds", _DEFAULT_TIMEOUT_SECONDS),
            max_memory_mb=config.get("max_memory_mb", _DEFAULT_MAX_MEMORY_MB),
            max_output_bytes=config.get("max_output_bytes", _DEFAULT_MAX_OUTPUT_BYTES),
            max_subprocesses=config.get("max_subprocesses", _DEFAULT_MAX_SUBPROCESSES),
            working_directory=config.get("working_directory"),
        )


class SandboxError(Exception):
    """Raised when a sandboxed process violates a resource limit."""


@dataclass(frozen=True)
class SandboxResult:
    """Outcome of a sandboxed subprocess execution.

    Args:
        return_code: Process exit code.
        stdout: Captured stdout (possibly truncated).
        stderr: Captured stderr (possibly truncated).
        truncated: Whether output was truncated to fit
            ``max_output_bytes``.
        timed_out: Whether the process was killed due to timeout.
    """

    return_code: int
    stdout: str
    stderr: str
    truncated: bool = False
    timed_out: bool = False


def _make_preexec_fn(
    max_memory_mb: int,
    max_subprocesses: int,
) -> object | None:
    """Return a ``preexec_fn`` that sets resource limits, or ``None``.

    Resource limits are only available on Linux/macOS (POSIX).  On other
    platforms this returns ``None`` and the sandbox relies on timeout +
    output limits alone.
    """
    if sys.platform == "win32":
        return None

    def _set_limits() -> None:
        import resource

        mem_bytes = max_memory_mb * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        except (ValueError, OSError):
            pass

        try:
            soft, hard = resource.getrlimit(resource.RLIMIT_NPROC)
            new_soft = min(soft, max_subprocesses) if soft != resource.RLIM_INFINITY else max_subprocesses
            resource.setrlimit(resource.RLIMIT_NPROC, (new_soft, hard))
        except (ValueError, OSError):
            pass

    return _set_limits


def run_sandboxed(
    command: Sequence[str],
    *,
    config: SandboxConfig | None = None,
    env: dict[str, str] | None = None,
) -> SandboxResult:
    """Execute *command* inside a resource-limited sandbox.

    Args:
        command: The command and arguments to execute
            (e.g. ``["python3", "script.py"]``).
        config: Resource limits.  Uses defaults when ``None``.
        env: Optional environment variables for the subprocess.
            When ``None``, inherits the parent's environment.

    Returns:
        A :class:`SandboxResult` with captured output and status.

    Raises:
        SandboxError: If the process exceeds the memory limit and is
            killed by the OS (exit code -9).
    """
    if config is None:
        config = SandboxConfig()

    cwd: str | None = config.working_directory
    if cwd is not None:
        cwd_path = Path(cwd)
        if not cwd_path.is_dir():
            raise SandboxError(
                f"Working directory '{cwd}' does not exist."
            )

    preexec_fn = _make_preexec_fn(config.max_memory_mb, config.max_subprocesses)

    timed_out = False
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            timeout=config.timeout_seconds,
            cwd=cwd,
            env=env,
            preexec_fn=preexec_fn,
        )
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout_raw = exc.stdout or b""
        stderr_raw = exc.stderr or b""
        stdout = _decode_and_truncate(stdout_raw, config.max_output_bytes)
        stderr = _decode_and_truncate(stderr_raw, config.max_output_bytes)
        truncated = (
            len(stdout_raw) > config.max_output_bytes
            or len(stderr_raw) > config.max_output_bytes
        )
        return SandboxResult(
            return_code=-1,
            stdout=stdout,
            stderr=stderr,
            truncated=truncated,
            timed_out=True,
        )
    except OSError as exc:
        raise SandboxError(f"Failed to start process: {exc}") from exc

    stdout_raw = proc.stdout or b""
    stderr_raw = proc.stderr or b""
    truncated = (
        len(stdout_raw) > config.max_output_bytes
        or len(stderr_raw) > config.max_output_bytes
    )
    stdout = _decode_and_truncate(stdout_raw, config.max_output_bytes)
    stderr = _decode_and_truncate(stderr_raw, config.max_output_bytes)

    if proc.returncode == -9:
        raise SandboxError(
            f"Process was killed (signal 9), likely exceeding the "
            f"{config.max_memory_mb} MB memory limit. "
            f"Partial stderr: {stderr[:500]}"
        )

    return SandboxResult(
        return_code=proc.returncode,
        stdout=stdout,
        stderr=stderr,
        truncated=truncated,
        timed_out=timed_out,
    )


def _decode_and_truncate(data: bytes, max_bytes: int) -> str:
    """Decode bytes to UTF-8 and truncate to *max_bytes*.

    Adds a ``[truncated]`` marker when output exceeds the limit.
    """
    if len(data) > max_bytes:
        truncated = data[:max_bytes]
        text = truncated.decode("utf-8", errors="replace")
        return text + "\n[truncated — output exceeded limit]"
    return data.decode("utf-8", errors="replace")
