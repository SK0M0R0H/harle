"""Tests for :mod:`harle.orchestrator.model_tier`."""

from __future__ import annotations

import logging

import pytest

from harle.config import Settings
from harle.orchestrator.model_tier import (
    ModelTierConfig,
    ComplexExecutionTier,
    normalize_complex_execution_tier,
    resolve_model_for_phase,
)


def test_from_settings_reads_all_tiers() -> None:
    s = Settings(
        HARLE_MODEL_CLASSIFIER="c1",
        HARLE_MODEL_PLANNER="p1",
        HARLE_MODEL_EXECUTOR="e1",
    )
    m = ModelTierConfig.from_settings(s)
    assert m.classifier == "c1"
    assert m.planner == "p1"
    assert m.executor == "e1"


def test_from_settings_strips_whitespace() -> None:
    s = Settings(
        HARLE_MODEL_CLASSIFIER="  mini  ",
        HARLE_MODEL_PLANNER="  plan  ",
        HARLE_MODEL_EXECUTOR="  exec  ",
    )
    m = ModelTierConfig.from_settings(s)
    assert m.classifier == "mini"
    assert m.planner == "plan"
    assert m.executor == "exec"


def test_from_settings_rejects_empty_planner() -> None:
    s = Settings(
        HARLE_MODEL_CLASSIFIER="a",
        HARLE_MODEL_PLANNER="   ",
        HARLE_MODEL_EXECUTOR="c",
    )
    with pytest.raises(ValueError, match="HARLE_MODEL_PLANNER"):
        ModelTierConfig.from_settings(s)


def test_model_for_tier_unknown_falls_back_to_executor() -> None:
    m = ModelTierConfig(classifier="a", planner="b", executor="c")
    assert m.model_for_tier("unknown") == "c"


def test_resolve_model_for_phase() -> None:
    m = ModelTierConfig(classifier="c", planner="p", executor="e")
    assert resolve_model_for_phase("planning", m) == "p"
    assert resolve_model_for_phase("execution", m) == "e"
    assert resolve_model_for_phase("reflection", m) == "p"
    assert resolve_model_for_phase("improvement", m) == "e"
    assert resolve_model_for_phase("routing", m) == "c"


def test_resolve_model_for_phase_role_override() -> None:
    m = ModelTierConfig(classifier="c", planner="p", executor="e")
    assert resolve_model_for_phase("execution", m, role_override="planner") == "p"


def test_normalize_complex_execution_tier_invalid(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    assert normalize_complex_execution_tier("bogus") is ComplexExecutionTier.EXECUTOR
    assert any("HARLE_COMPLEX_EXECUTION_TIER" in r.message for r in caplog.records)


def test_normalize_complex_execution_tier_valid() -> None:
    assert normalize_complex_execution_tier("planner") is ComplexExecutionTier.PLANNER
    assert normalize_complex_execution_tier("executor") is ComplexExecutionTier.EXECUTOR
