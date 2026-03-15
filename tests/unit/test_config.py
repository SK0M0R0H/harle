"""Tests for harle.config — Settings, coercion, YAML loading."""

from __future__ import annotations

import os
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

import pytest

from harle.config import (
    Settings,
    _coerce,
    _load_yaml,
    get_vault_imports_config,
    load_environment,
    load_settings,
)


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


# ---------------------------------------------------------------------------
# get_vault_imports_config
# ---------------------------------------------------------------------------

class TestGetVaultImportsConfig:
    def test_returns_vault_imports_section(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.yaml"
        cfg.write_text(dedent("""\
            HARLE_HOST: "127.0.0.1"
            vault_imports:
              notion:
                max_block_depth: 5
                page_size: 50
        """), encoding="utf-8")
        env = {"HARLE_CONFIG_PATH": str(cfg)}
        with patch.dict(os.environ, env, clear=False):
            result = get_vault_imports_config()
        assert result.get("notion", {}).get("max_block_depth") == 5
        assert result.get("notion", {}).get("page_size") == 50

    def test_returns_empty_dict_when_section_missing(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.yaml"
        cfg.write_text("HARLE_HOST: localhost\n", encoding="utf-8")
        env = {"HARLE_CONFIG_PATH": str(cfg)}
        with patch.dict(os.environ, env, clear=False):
            result = get_vault_imports_config()
        assert result == {}

    def test_returns_empty_dict_when_file_missing(self, tmp_path: Path) -> None:
        fake = tmp_path / "nonexistent.yaml"
        env = {"HARLE_CONFIG_PATH": str(fake)}
        with patch.dict(os.environ, env, clear=False):
            result = get_vault_imports_config()
        assert result == {}


# ---------------------------------------------------------------------------
# load_environment
# ---------------------------------------------------------------------------

class TestLoadEnvironment:
    def test_loads_from_default_dotenv_in_cwd(self, tmp_path: Path) -> None:
        dotenv = tmp_path / ".env"
        dotenv.write_text("HARLE_LLM_MODEL=from_dotenv\n", encoding="utf-8")

        with patch.dict(os.environ, {}, clear=True), patch("harle.config._DOTENV_LOADED", False):
            previous_cwd = Path.cwd()
            try:
                os.chdir(tmp_path)
                load_environment(force=True)
                assert os.getenv("HARLE_LLM_MODEL") == "from_dotenv"
            finally:
                os.chdir(previous_cwd)

    def test_process_env_overrides_dotenv(self, tmp_path: Path) -> None:
        dotenv = tmp_path / ".env"
        dotenv.write_text("OPENAI_API_KEY=from_dotenv\n", encoding="utf-8")

        env = {
            "OPENAI_API_KEY": "from_process",
            "HARLE_DOTENV_PATH": str(dotenv),
        }
        with patch.dict(os.environ, env, clear=True), patch("harle.config._DOTENV_LOADED", False):
            load_environment(force=True)
            assert os.getenv("OPENAI_API_KEY") == "from_process"

    def test_custom_dotenv_path(self, tmp_path: Path) -> None:
        dotenv = tmp_path / "custom.env"
        dotenv.write_text("TAVILY_API_KEY=tvly-custom\n", encoding="utf-8")

        env = {"HARLE_DOTENV_PATH": str(dotenv)}
        with patch.dict(os.environ, env, clear=True), patch("harle.config._DOTENV_LOADED", False):
            load_environment(force=True)
            assert os.getenv("TAVILY_API_KEY") == "tvly-custom"
