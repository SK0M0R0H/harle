"""Permission checking for tool functions.

Reads ``permission`` and ``requires_approval`` attributes from tool
functions and checks them against the module's configured operation mode.

Operation modes
---------------
- ``read_only`` — only tools with ``permission="read"`` may execute.
- ``propose``   — write/delete tools pause for user approval; read tools
  execute freely.
- ``auto``      — all tools execute without approval.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)

_VALID_PERMISSIONS = frozenset({"read", "write", "delete"})


class OperationMode(str, Enum):
    """Module-level operation mode controlling default approval behaviour."""

    READ_ONLY = "read_only"
    PROPOSE = "propose"
    AUTO = "auto"


class PermissionError(Exception):
    """Raised when a tool call is blocked by the permission check."""


def get_tool_permission(fn: Callable) -> str:
    """Return the permission level declared on *fn*.

    Falls back to ``"read"`` when no ``permission`` attribute is set.

    Args:
        fn: A tool function, potentially with a ``permission`` attribute.

    Returns:
        One of ``"read"``, ``"write"``, or ``"delete"``.
    """
    perm = getattr(fn, "permission", "read")
    if perm not in _VALID_PERMISSIONS:
        logger.warning(
            "Tool %s has invalid permission %r; defaulting to 'read'.",
            getattr(fn, "__name__", fn),
            perm,
        )
        return "read"
    return perm


def get_requires_approval(fn: Callable) -> bool:
    """Return whether *fn* requires user approval before execution.

    Falls back to ``False`` when no ``requires_approval`` attribute is set.

    Args:
        fn: A tool function, potentially with a ``requires_approval``
            attribute.

    Returns:
        ``True`` if the tool requires approval.
    """
    return bool(getattr(fn, "requires_approval", False))


def check_permission(
    fn: Callable,
    module_mode: OperationMode | str,
) -> dict[str, Any]:
    """Check whether *fn* is allowed to execute under *module_mode*.

    Returns a dict describing the check result::

        {
            "allowed": True / False,
            "needs_approval": True / False,
            "permission": "read" / "write" / "delete",
            "mode": "read_only" / "propose" / "auto",
            "reason": "..."   # only present when blocked
        }

    Args:
        fn: The tool function to check.
        module_mode: The module's operation mode (from config).

    Returns:
        A dict with the check result.
    """
    mode = OperationMode(module_mode) if isinstance(module_mode, str) else module_mode
    perm = get_tool_permission(fn)
    fn_name = getattr(fn, "__name__", str(fn))

    result: dict[str, Any] = {
        "allowed": True,
        "needs_approval": False,
        "permission": perm,
        "mode": mode.value,
    }

    if mode is OperationMode.READ_ONLY and perm != "read":
        result["allowed"] = False
        result["reason"] = (
            f"Tool '{fn_name}' requires '{perm}' permission but module "
            f"is in read_only mode."
        )
        return result

    if mode is OperationMode.PROPOSE and perm in ("write", "delete"):
        result["needs_approval"] = True
        return result

    if mode is OperationMode.PROPOSE and perm == "read":
        return result

    if mode is OperationMode.AUTO:
        return result

    return result
