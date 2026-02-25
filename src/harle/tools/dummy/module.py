"""Dummy tool module for verifying the Tool Module Layer pattern.

This module is intentionally minimal.  It exists so that Phase 1 can be
validated end-to-end: register a module → get ``FunctionTool`` objects →
confirm the OpenAI Agents SDK accepts them.

It also demonstrates module-provided default constraints: the dummy
module ships with a ``blocked_patterns`` safety floor and a
``max_input_length`` cap.  Users can override these via config.
"""

from __future__ import annotations

import logging
from typing import Callable

from harle.tools.base import BaseToolModule
from harle.tools.constraints import ConstraintConfig
from harle.tools.dummy.tools import dummy_create, dummy_delete, dummy_read

logger = logging.getLogger(__name__)


class DummyModule(BaseToolModule):
    """A no-op module used to verify the registry and SDK bridge."""

    @property
    def name(self) -> str:
        return "dummy"

    @property
    def description(self) -> str:
        return "Dummy module for testing the tool infrastructure"

    async def initialize(self, config: dict) -> None:
        logger.info("DummyModule initialised with config keys: %s", list(config.keys()))
        self._config = config

    async def shutdown(self) -> None:
        logger.info("DummyModule shut down.")

    def get_tools(self) -> list[Callable]:
        return [dummy_read, dummy_create, dummy_delete]

    def default_constraints(self) -> ConstraintConfig:
        return ConstraintConfig(
            blocked_patterns=[r"rm\s+-rf", r"sudo\s+"],
            max_input_length=10_000,
        )

    async def health_check(self) -> bool:
        return True
