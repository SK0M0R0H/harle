"""Input validation constraints for tool functions (Security Layer 3).

Constraints are declared per-module in ``config.yaml`` under
``tool_modules.<module>.constraints``.  The registry calls
:func:`validate_inputs` **before** executing any tool function so that
dangerous inputs are rejected regardless of the tool's own implementation.

Supported constraint types
--------------------------
- ``allowed_commands``  — allowlist of executable names.
- ``blocked_patterns``  — regex patterns rejected if found in any argument.
- ``allowed_paths``     — filesystem paths the tool may access.
- ``blocked_paths``     — paths the tool must never access.
- ``allowed_hosts``     — network hosts the tool may contact.
- ``max_input_length``  — max character length for any single argument.

Design principles (from the TRD):
    * **Fail closed** — if a constraint check itself errors (e.g. a bad
      regex), the call is blocked, not allowed.
    * **Visible policy** — all constraints live in config, not in code.
    * **Defense in depth** — constraints are one layer; permissions,
      approval gates, and the execution sandbox are others.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ConstraintViolation(Exception):
    """Raised when a tool input violates a configured constraint.

    Attributes:
        constraint_type: Which constraint was violated
            (e.g. ``"blocked_patterns"``).
        detail: Human-readable explanation suitable for returning to
            the LLM.
    """

    def __init__(self, constraint_type: str, detail: str) -> None:
        self.constraint_type = constraint_type
        self.detail = detail
        super().__init__(f"[{constraint_type}] {detail}")


@dataclass(frozen=True)
class ConstraintConfig:
    """Parsed constraint configuration for a single module.

    All fields are optional.  An empty :class:`ConstraintConfig` imposes
    no restrictions (Layers 1 and 2 still apply).

    Args:
        allowed_commands: Allowlisted executable names.
        blocked_patterns: Regex patterns that reject matching arguments.
        allowed_paths: Filesystem prefixes the tool may access.
        blocked_paths: Filesystem prefixes the tool must never access.
        allowed_hosts: Network hosts the tool may contact.
        max_input_length: Max character length for any single argument.
    """

    allowed_commands: list[str] = field(default_factory=list)
    blocked_patterns: list[str] = field(default_factory=list)
    allowed_paths: list[str] = field(default_factory=list)
    blocked_paths: list[str] = field(default_factory=list)
    allowed_hosts: list[str] = field(default_factory=list)
    max_input_length: int | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> ConstraintConfig:
        """Build a :class:`ConstraintConfig` from a raw config dict.

        Environment variables in path values (``${VAR}``) are expanded.
        Missing or ``None`` input yields an empty (no-constraint) config.

        Args:
            raw: The ``constraints`` sub-dict from module config, or
                ``None``.

        Returns:
            A validated :class:`ConstraintConfig`.
        """
        if not raw:
            return cls()
        return cls(
            allowed_commands=raw.get("allowed_commands", []),
            blocked_patterns=raw.get("blocked_patterns", []),
            allowed_paths=[_expand(p) for p in raw.get("allowed_paths", [])],
            blocked_paths=[_expand(p) for p in raw.get("blocked_paths", [])],
            allowed_hosts=raw.get("allowed_hosts", []),
            max_input_length=raw.get("max_input_length"),
        )

    @property
    def is_empty(self) -> bool:
        """Return ``True`` when no constraints are configured."""
        return (
            not self.allowed_commands
            and not self.blocked_patterns
            and not self.allowed_paths
            and not self.blocked_paths
            and not self.allowed_hosts
            and self.max_input_length is None
        )

    def merge(self, override: ConstraintConfig) -> ConstraintConfig:
        """Merge *override* on top of this config (the defaults).

        For each field, if *override* has a non-empty / non-None value
        it replaces the default; otherwise the default is kept.  This
        lets modules ship safe defaults while users can tighten or
        replace individual constraint fields via ``config.yaml``.

        Args:
            override: User-provided constraints from config.

        Returns:
            A new :class:`ConstraintConfig` with merged values.
        """
        return ConstraintConfig(
            allowed_commands=override.allowed_commands or self.allowed_commands,
            blocked_patterns=override.blocked_patterns or self.blocked_patterns,
            allowed_paths=override.allowed_paths or self.allowed_paths,
            blocked_paths=override.blocked_paths or self.blocked_paths,
            allowed_hosts=override.allowed_hosts or self.allowed_hosts,
            max_input_length=(
                override.max_input_length
                if override.max_input_length is not None
                else self.max_input_length
            ),
        )


def _expand(path_str: str) -> str:
    """Expand ``${VAR}`` references and ``~`` in a path string."""
    expanded = os.path.expandvars(path_str)
    expanded = os.path.expanduser(expanded)
    return expanded


# ---------------------------------------------------------------------------
# Individual constraint checks
# ---------------------------------------------------------------------------


def check_allowed_commands(
    command: str,
    allowed: list[str],
) -> None:
    """Verify *command* is in the allowlist.

    Args:
        command: The executable name or path to check.
        allowed: Allowlisted command names.

    Raises:
        ConstraintViolation: If *command* is not allowed.
    """
    if not allowed:
        return
    base_command = Path(command).name
    if base_command not in allowed and command not in allowed:
        raise ConstraintViolation(
            "allowed_commands",
            f"Command '{command}' is not in the allowed commands list "
            f"{allowed}.",
        )


def check_blocked_patterns(
    args: dict[str, Any],
    patterns: list[str],
) -> None:
    """Reject inputs that match any blocked regex pattern.

    Every string value in *args* (including nested values converted via
    ``str()``) is tested against each pattern.  The check **fails
    closed**: if a regex is malformed the call is blocked.

    Args:
        args: The tool's keyword arguments.
        patterns: Regex patterns to test against.

    Raises:
        ConstraintViolation: If any argument matches a blocked pattern.
    """
    if not patterns:
        return
    for pattern_str in patterns:
        try:
            compiled = re.compile(pattern_str)
        except re.error as exc:
            raise ConstraintViolation(
                "blocked_patterns",
                f"Malformed constraint regex '{pattern_str}': {exc}. "
                f"Blocking call to be safe (fail-closed).",
            ) from exc

        for key, value in args.items():
            text = str(value)
            if compiled.search(text):
                raise ConstraintViolation(
                    "blocked_patterns",
                    f"Argument '{key}' contains a disallowed pattern "
                    f"(matched '{pattern_str}'). This input is not "
                    f"permitted.",
                )


def check_allowed_paths(
    path_str: str,
    allowed: list[str],
) -> None:
    """Verify *path_str* resolves to a location within *allowed* prefixes.

    Symlinks are resolved to prevent escape attacks.

    Args:
        path_str: The path to validate.
        allowed: Allowed directory prefixes.

    Raises:
        ConstraintViolation: If the resolved path is outside all
            allowed prefixes.
    """
    if not allowed:
        return
    try:
        resolved = Path(path_str).resolve(strict=False)
    except (OSError, ValueError) as exc:
        raise ConstraintViolation(
            "allowed_paths",
            f"Cannot resolve path '{path_str}': {exc}. Blocking call.",
        ) from exc

    for prefix in allowed:
        prefix_resolved = Path(prefix).resolve(strict=False)
        try:
            resolved.relative_to(prefix_resolved)
            return
        except ValueError:
            continue

    raise ConstraintViolation(
        "allowed_paths",
        f"Path '{path_str}' (resolved: {resolved}) is outside the "
        f"allowed paths {allowed}.",
    )


def check_blocked_paths(
    path_str: str,
    blocked: list[str],
) -> None:
    """Reject *path_str* if it resolves to a blocked location.

    Args:
        path_str: The path to validate.
        blocked: Blocked directory prefixes.

    Raises:
        ConstraintViolation: If the resolved path falls within a
            blocked prefix.
    """
    if not blocked:
        return
    try:
        resolved = Path(path_str).resolve(strict=False)
    except (OSError, ValueError) as exc:
        raise ConstraintViolation(
            "blocked_paths",
            f"Cannot resolve path '{path_str}': {exc}. Blocking call.",
        ) from exc

    for prefix in blocked:
        prefix_resolved = Path(prefix).resolve(strict=False)
        try:
            resolved.relative_to(prefix_resolved)
            raise ConstraintViolation(
                "blocked_paths",
                f"Path '{path_str}' (resolved: {resolved}) is within "
                f"the blocked path '{prefix}'.",
            )
        except ValueError:
            continue


def check_allowed_hosts(
    host: str,
    allowed: list[str],
) -> None:
    """Verify *host* is in the allowlist.

    Args:
        host: Hostname or domain to validate.
        allowed: Allowlisted hostnames.

    Raises:
        ConstraintViolation: If *host* is not allowed.
    """
    if not allowed:
        return
    host_lower = host.lower()
    for allowed_host in allowed:
        if host_lower == allowed_host.lower():
            return
        if host_lower.endswith("." + allowed_host.lower()):
            return
    raise ConstraintViolation(
        "allowed_hosts",
        f"Host '{host}' is not in the allowed hosts list {allowed}.",
    )


def check_max_input_length(
    args: dict[str, Any],
    max_length: int | None,
) -> None:
    """Reject arguments that exceed *max_length* characters.

    Args:
        args: The tool's keyword arguments.
        max_length: Maximum allowed character length, or ``None`` to skip.

    Raises:
        ConstraintViolation: If any argument exceeds *max_length*.
    """
    if max_length is None:
        return
    for key, value in args.items():
        text = str(value)
        if len(text) > max_length:
            raise ConstraintViolation(
                "max_input_length",
                f"Argument '{key}' has {len(text)} characters, exceeding "
                f"the maximum of {max_length}.",
            )


# ---------------------------------------------------------------------------
# Composite validation
# ---------------------------------------------------------------------------


def validate_inputs(
    args: dict[str, Any],
    config: ConstraintConfig,
    *,
    command: str | None = None,
    paths: list[str] | None = None,
    host: str | None = None,
) -> dict[str, str]:
    """Run all applicable constraint checks on *args*.

    Returns a results dict mapping each checked constraint type to
    ``"pass"`` or ``"skip"`` (when the constraint is not configured).
    Raises :class:`ConstraintViolation` on the first failure.

    Args:
        args: The tool function's keyword arguments.
        config: The module's constraint configuration.
        command: If the tool executes a command, the executable name
            to validate against ``allowed_commands``.
        paths: If the tool accesses the filesystem, paths to validate
            against ``allowed_paths`` and ``blocked_paths``.
        host: If the tool contacts a network host, the hostname to
            validate against ``allowed_hosts``.

    Returns:
        A dict of ``{constraint_type: "pass" | "skip"}`` for logging.

    Raises:
        ConstraintViolation: On the first constraint failure.
    """
    results: dict[str, str] = {}

    if command is not None and config.allowed_commands:
        check_allowed_commands(command, config.allowed_commands)
        results["allowed_commands"] = "pass"
    else:
        results["allowed_commands"] = "skip"

    if config.blocked_patterns:
        check_blocked_patterns(args, config.blocked_patterns)
        results["blocked_patterns"] = "pass"
    else:
        results["blocked_patterns"] = "skip"

    if paths is not None:
        for p in paths:
            if config.allowed_paths:
                check_allowed_paths(p, config.allowed_paths)
            if config.blocked_paths:
                check_blocked_paths(p, config.blocked_paths)
        results["allowed_paths"] = "pass" if config.allowed_paths else "skip"
        results["blocked_paths"] = "pass" if config.blocked_paths else "skip"
    else:
        results["allowed_paths"] = "skip"
        results["blocked_paths"] = "skip"

    if host is not None and config.allowed_hosts:
        check_allowed_hosts(host, config.allowed_hosts)
        results["allowed_hosts"] = "pass"
    else:
        results["allowed_hosts"] = "skip"

    if config.max_input_length is not None:
        check_max_input_length(args, config.max_input_length)
        results["max_input_length"] = "pass"
    else:
        results["max_input_length"] = "skip"

    return results
