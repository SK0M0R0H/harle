"""Model tier resolution for dynamic LLM switching (see TRD dynamic_model_switching)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Literal

from harle.config import Settings

logger = logging.getLogger(__name__)

TIER_DEFAULTS: dict[str, str] = {
    "classifier": "gpt-4o-mini",
    "planner": "gpt-4o",
    "executor": "gpt-4o-mini",
}

PhaseName = Literal[
    "routing",
    "classification",
    "planning",
    "execution",
    "handoff",
    "reflection",
    "improvement",
]

# phase -> tier name (algorithmic mapping from TRD)
_PHASE_TIER_MAP: dict[str, str] = {
    "routing": "classifier",
    "classification": "classifier",
    "planning": "planner",
    "execution": "executor",
    "handoff": "executor",
    "reflection": "planner",
    "improvement": "executor",
}

KNOWN_TIERS = frozenset(TIER_DEFAULTS)


class ComplexExecutionTier(str, Enum):
    """Model tier used for the execution phase when complexity is complex."""

    EXECUTOR = "executor"
    PLANNER = "planner"


def normalize_complex_execution_tier(raw: str) -> ComplexExecutionTier:
    """Return :class:`ComplexExecutionTier`; invalid values fall back to ``EXECUTOR``."""
    t = (raw or "").strip().lower()
    if t == ComplexExecutionTier.PLANNER.value:
        return ComplexExecutionTier.PLANNER
    if t == ComplexExecutionTier.EXECUTOR.value:
        return ComplexExecutionTier.EXECUTOR
    if t:
        logger.warning(
            "HARLE_COMPLEX_EXECUTION_TIER=%r is not a known tier; using %r",
            raw,
            ComplexExecutionTier.EXECUTOR.value,
        )
    return ComplexExecutionTier.EXECUTOR


def resolve_model_for_phase(
    phase: str,
    tier_config: ModelTierConfig,
    *,
    role_override: str | None = None,
) -> str:
    """Resolve concrete model name for an execution phase."""
    if role_override and role_override in KNOWN_TIERS:
        return tier_config.model_for_tier(role_override)
    tier = _PHASE_TIER_MAP.get(phase, "executor")
    return tier_config.model_for_tier(tier)


def _require_tier_model(value: str, key: str) -> str:
    """Return stripped model name or raise if missing/blank."""
    s = (value or "").strip()
    if not s:
        raise ValueError(
            f"{key} must be set to a non-empty model name "
            f"(configure in config.yaml or the environment).",
        )
    return s


@dataclass(frozen=True)
class ModelTierConfig:
    """Resolved model names for classifier, planner, and executor tiers."""

    classifier: str
    planner: str
    executor: str

    def model_for_tier(self, tier: str) -> str:
        """Return the concrete model for a tier name."""
        t = tier.lower().strip()
        if t == "classifier":
            return self.classifier
        if t == "planner":
            return self.planner
        if t == "executor":
            return self.executor
        return TIER_DEFAULTS.get(t, self.executor)

    @staticmethod
    def from_settings(settings: Settings) -> ModelTierConfig:
        """Build from :class:`~harle.config.Settings`.

        All three ``HARLE_MODEL_*`` values must be non-empty strings.
        """
        return ModelTierConfig(
            classifier=_require_tier_model(
                settings.HARLE_MODEL_CLASSIFIER,
                "HARLE_MODEL_CLASSIFIER",
            ),
            planner=_require_tier_model(
                settings.HARLE_MODEL_PLANNER,
                "HARLE_MODEL_PLANNER",
            ),
            executor=_require_tier_model(
                settings.HARLE_MODEL_EXECUTOR,
                "HARLE_MODEL_EXECUTOR",
            ),
        )
