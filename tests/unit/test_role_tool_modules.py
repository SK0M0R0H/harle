"""Tests for :mod:`harle.orchestrator.role_tool_modules` JSON loading."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harle.orchestrator.role_tool_modules import (
    DEFAULT_ROLE_TOOL_MODULES,
    load_role_tool_modules_json,
    merge_with_defaults,
    resolve_role_tool_modules,
)


def test_merge_partial_override_keeps_other_roles() -> None:
    merged = merge_with_defaults({"researcher": ["vault"]})
    assert merged["researcher"] == ["vault"]
    assert merged["assistant"] == DEFAULT_ROLE_TOOL_MODULES["assistant"]


def test_load_json_skips_underscore_keys(tmp_path: Path) -> None:
    p = tmp_path / "m.json"
    p.write_text(
        json.dumps(
            {
                "_comment": "ignored",
                "writer": ["vault", "think"],
            },
        ),
        encoding="utf-8",
    )
    loaded = load_role_tool_modules_json(p)
    assert "_comment" not in loaded
    assert loaded["writer"] == ["vault", "think"]


def test_resolve_uses_explicit_path(tmp_path: Path) -> None:
    p = tmp_path / "custom.json"
    p.write_text(
        json.dumps({"specialist": ["vault", "web_search", "think"]}),
        encoding="utf-8",
    )
    r = resolve_role_tool_modules(
        explicit_path=str(p),
        dataset_path=None,
    )
    assert r["specialist"] == ["vault", "web_search", "think"]
    assert r["assistant"] == DEFAULT_ROLE_TOOL_MODULES["assistant"]


def test_resolve_prefers_explicit_over_dataset(tmp_path: Path) -> None:
    explicit = tmp_path / "a.json"
    explicit.write_text(json.dumps({"writer": ["vault"]}), encoding="utf-8")
    dataset = tmp_path / "vault"
    dataset.mkdir()
    (dataset / "role_tool_modules.json").write_text(
        json.dumps({"writer": ["vault", "think"]}),
        encoding="utf-8",
    )
    r = resolve_role_tool_modules(
        explicit_path=str(explicit),
        dataset_path=str(dataset),
    )
    assert r["writer"] == ["vault"]


def test_resolve_dataset_file_when_explicit_missing(tmp_path: Path) -> None:
    dataset = tmp_path / "vault"
    dataset.mkdir()
    (dataset / "role_tool_modules.json").write_text(
        json.dumps({"secretary": ["vault", "think"]}),
        encoding="utf-8",
    )
    r = resolve_role_tool_modules(explicit_path=None, dataset_path=str(dataset))
    assert r["secretary"] == ["vault", "think"]


def test_resolve_invalid_json_falls_back_to_defaults(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{ not json", encoding="utf-8")
    r = resolve_role_tool_modules(explicit_path=str(p), dataset_path=None)
    assert r == DEFAULT_ROLE_TOOL_MODULES
