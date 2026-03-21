"""Think tool — no-op scratchpad for agent reasoning (Level 4)."""

from __future__ import annotations

import logging
from typing import Callable

from harle.tools.base import BaseToolModule

logger = logging.getLogger(__name__)


async def think(reasoning: str) -> str:
    """Use this tool to think through a problem step by step.

    Call this tool before making decisions, between tool calls when you need
    to reason about results, or when facing a complex judgment. The reasoning
    is logged but does not appear in the final response.

    Args:
        reasoning: Your step-by-step thinking about the problem.

    Returns:
        Empty string — this is a scratchpad only.
    """
    return ""


think.permission = "read"  # type: ignore[attr-defined]
think.requires_approval = False  # type: ignore[attr-defined]


class ThinkToolModule(BaseToolModule):
    """Registers the no-op ``think`` tool for explicit reasoning traces."""

    @property
    def name(self) -> str:
        return "think"

    @property
    def description(self) -> str:
        return "Optional scratchpad tool for step-by-step reasoning (logged, not shown to user)"

    async def initialize(self, config: dict, connections: object | None = None) -> None:
        logger.debug("ThinkToolModule initialized")

    async def shutdown(self) -> None:
        logger.debug("ThinkToolModule shut down")

    def get_tools(self) -> list[Callable]:
        return [think]
