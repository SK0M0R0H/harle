"""Tests for harle.config — Settings, coercion, YAML loading."""

from __future__ import annotations

import os
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

import pytest

from harle.config import Settings, _coerce, _load_yaml, load_settings


# ---------------------------------------------------------------------------
# _coerce
# ---------------------------------------------------------------------------

class TestCoerce:
    def test_none_passthrough(self) -> None:
        assert _coerce(None, int) is None

    def test_int_from_string(self) -> None:
        assert _coerce("8080", int) == 8080

    def test_int_from_int(self) -> None:
        assert _coerce(42, int) == 42

    def test_float_from_string(self) -> None:
        assert _coerce("3.14", float) == pytest.approx(3.14)

    def test_bool_true_variants(self) -> None:
        for val in ("1", "true", "True", "TRUE", "yes", "Yes"):
            assert _coerce(val, bool) is True

    def test_bool_false_variants(self) -> None:
        for val in ("0", "false", "no", "nope"):
            assert _coerce(val, bool) is False

    def test_optional_str(self) -> None:
        result = _coerce("hello", str | None)
        assert result == "hello"

    def test_optional_none(self) -> None:
        result = _coerce(None, str | None)
        assert result is None

    def test_string_passthrough(self) -> None:
        assert _coerce("hello", str) == "hello"


# ---------------------------------------------------------------------------
# _load_yaml
# ---------------------------------------------------------------------------

class TestLoadYaml:
    def test_missing_file(self, tmp_path: Path) -> None:
        result = _load_yaml(tmp_path / "nonexistent.yaml")
        assert result == {}

    def test_valid_yaml(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.yaml"
        cfg.write_text("HARLE_HOST: '0.0.0.0'\nHARLE_PORT: 9000\n", encoding="utf-8")
        result = _load_yaml(cfg)
        assert result == {"HARLE_HOST": "0.0.0.0", "HARLE_PORT": 9000}

    def test_invalid_yaml(self, tmp_path: Path) -> None:
        cfg = tmp_path / "bad.yaml"
        cfg.write_text(":\n  :\n    - [invalid", encoding="utf-8")
        result = _load_yaml(cfg)
        assert result == {}

    def test_non_dict_yaml(self, tmp_path: Path) -> None:
        cfg = tmp_path / "list.yaml"
        cfg.write_text("- item1\n- item2\n", encoding="utf-8")
        result = _load_yaml(cfg)
        assert result == {}


# ---------------------------------------------------------------------------
# Settings defaults
# ---------------------------------------------------------------------------

class TestSettingsDefaults:
    def test_default_values(self) -> None:
        s = Settings()
        assert s.HARLE_HOST == "127.0.0.1"
        assert s.HARLE_PORT == 8000
        assert s.HARLE_LLM_PROVIDER == "openai"
        assert s.HARLE_LLM_MODEL == "gpt-4o-mini"
        assert s.HARLE_DATASET_PATH is None
        assert s.DATABASE_URL is None

    def test_frozen(self) -> None:
        s = Settings()
        with pytest.raises(AttributeError):
            s.HARLE_HOST = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# load_settings
# ---------------------------------------------------------------------------

class TestLoadSettings:
    def test_defaults_when_no_config(self, tmp_path: Path) -> None:
        """With no config file and no env vars, all defaults apply."""
        fake_config = tmp_path / "nonexistent.yaml"
        env = {"HARLE_CONFIG_PATH": str(fake_config)}
        with patch.dict(os.environ, env, clear=False):
            # Clear any env vars that would interfere
            for key in ("HARLE_HOST", "HARLE_PORT", "HARLE_LLM_PROVIDER",
                        "HARLE_LLM_MODEL", "HARLE_DATASET_PATH", "DATABASE_URL"):
                os.environ.pop(key, None)
            s = load_settings()
        assert s.HARLE_HOST == "127.0.0.1"
        assert s.HARLE_PORT == 8000

    def test_config_file_overrides_defaults(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.yaml"
        cfg.write_text(dedent("""\
            HARLE_HOST: "0.0.0.0"
            HARLE_PORT: 9999
        """), encoding="utf-8")
        env = {"HARLE_CONFIG_PATH": str(cfg)}
        with patch.dict(os.environ, env, clear=False):
            for key in ("HARLE_HOST", "HARLE_PORT"):
                os.environ.pop(key, None)
            s = load_settings()
        assert s.HARLE_HOST == "0.0.0.0"
        assert s.HARLE_PORT == 9999

    def test_env_var_fallback(self, tmp_path: Path) -> None:
        fake_config = tmp_path / "nonexistent.yaml"
        env = {
            "HARLE_CONFIG_PATH": str(fake_config),
            "HARLE_HOST": "10.0.0.1",
        }
        with patch.dict(os.environ, env, clear=False):
            s = load_settings()
        assert s.HARLE_HOST == "10.0.0.1"

    def test_config_file_wins_over_env(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.yaml"
        cfg.write_text("HARLE_HOST: from_file\n", encoding="utf-8")
        env = {
            "HARLE_CONFIG_PATH": str(cfg),
            "HARLE_HOST": "from_env",
        }
        with patch.dict(os.environ, env, clear=False):
            s = load_settings()
        assert s.HARLE_HOST == "from_file"
