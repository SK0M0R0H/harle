"""Tests for the Tool Module Layer — Phase 4 skills system.

Covers:
- SkillLoaderConfig construction and from_config factory
- Skill resolution (vault override vs built-in)
- Loading, frontmatter stripping, token budget enforcement
- Registry skill integration (get_skills_for_tools, get_module_skills)
"""

from __future__ import annotations

import asyncio
import os
import textwrap
from pathlib import Path
from typing import Callable

import pytest

from harle.tools.base import BaseToolModule
from harle.tools.registry import ToolRegistry
from harle.tools.skills import (
    LoadedSkill,
    SkillLoaderConfig,
    _read_skill_file,
    _resolve_skill_path,
    _truncate_to_budget,
    get_builtin_skills_dir,
    load_module_skills,
)


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------


class _SkillTestModule(BaseToolModule):
    """Minimal module for skills tests."""

    def __init__(self, name: str = "skillmod") -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "Module for testing skills"

    async def initialize(self, config: dict) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    def get_tools(self) -> list[Callable]:
        async def skillmod_read(item_id: str) -> str:
            """Read an item.

            Args:
                item_id: The item identifier.
            """
            return item_id

        return [skillmod_read]


class _SecondModule(BaseToolModule):
    """Second module to test multi-module skill deduplication."""

    @property
    def name(self) -> str:
        return "second"

    @property
    def description(self) -> str:
        return "Second module"

    async def initialize(self, config: dict) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    def get_tools(self) -> list[Callable]:
        async def second_action(text: str) -> str:
            """Perform an action.

            Args:
                text: Input text.
            """
            return text

        return [second_action]


def _write_skill(base: Path, module: str, name: str, content: str) -> Path:
    """Write a skill file and return its path."""
    skill_dir = base / module / "skills" if "skills" not in str(base) else base / module
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / f"{name}.md"
    path.write_text(content, encoding="utf-8")
    return path


def _make_frontmatter_skill(title: str = "Test Skill", body: str = "# Heading\n\nBody text.") -> str:
    return f"---\ntitle: \"{title}\"\ntags: [test]\n---\n\n{body}"


# ===================================================================
# SkillLoaderConfig
# ===================================================================


class TestSkillLoaderConfig:
    """Tests for SkillLoaderConfig dataclass."""

    def test_defaults(self) -> None:
        cfg = SkillLoaderConfig()
        assert cfg.user_skills_dir is None
        assert cfg.max_tokens_per_module == 2000

    def test_custom_values(self) -> None:
        cfg = SkillLoaderConfig(user_skills_dir="/vault/tool_skills", max_tokens_per_module=500)
        assert cfg.user_skills_dir == "/vault/tool_skills"
        assert cfg.max_tokens_per_module == 500

    def test_from_config_none(self) -> None:
        cfg = SkillLoaderConfig.from_config(None)
        assert cfg == SkillLoaderConfig()

    def test_from_config_empty(self) -> None:
        cfg = SkillLoaderConfig.from_config({})
        assert cfg == SkillLoaderConfig()

    def test_from_config_with_values(self) -> None:
        cfg = SkillLoaderConfig.from_config({
            "user_skills_dir": "/vault/tool_skills",
            "max_tokens_per_module": 1000,
        })
        assert cfg.user_skills_dir == "/vault/tool_skills"
        assert cfg.max_tokens_per_module == 1000

    def test_from_config_env_expansion(self, tmp_path: Path) -> None:
        os.environ["_TEST_VAULT"] = str(tmp_path)
        try:
            cfg = SkillLoaderConfig.from_config({
                "user_skills_dir": "${_TEST_VAULT}/tool_skills",
            })
            assert cfg.user_skills_dir == f"{tmp_path}/tool_skills"
        finally:
            del os.environ["_TEST_VAULT"]

    def test_frozen(self) -> None:
        cfg = SkillLoaderConfig()
        with pytest.raises(AttributeError):
            cfg.max_tokens_per_module = 100  # type: ignore[misc]


# ===================================================================
# _read_skill_file — frontmatter stripping
# ===================================================================


class TestReadSkillFile:
    """Tests for frontmatter stripping."""

    def test_strips_frontmatter(self, tmp_path: Path) -> None:
        path = tmp_path / "skill.md"
        path.write_text(_make_frontmatter_skill(body="Real content."), encoding="utf-8")
        content = _read_skill_file(path)
        assert "---" not in content
        assert "title:" not in content
        assert content.startswith("Real content.")

    def test_no_frontmatter(self, tmp_path: Path) -> None:
        path = tmp_path / "skill.md"
        text = "# Just Markdown\n\nNo frontmatter here."
        path.write_text(text, encoding="utf-8")
        assert _read_skill_file(path) == text

    def test_single_separator(self, tmp_path: Path) -> None:
        path = tmp_path / "skill.md"
        text = "---\nThis is a horizontal rule, not frontmatter."
        path.write_text(text, encoding="utf-8")
        assert _read_skill_file(path) == text

    def test_empty_frontmatter(self, tmp_path: Path) -> None:
        path = tmp_path / "skill.md"
        path.write_text("---\n---\n\nBody.", encoding="utf-8")
        content = _read_skill_file(path)
        assert content == "Body."


# ===================================================================
# _resolve_skill_path
# ===================================================================


class TestResolveSkillPath:
    """Tests for skill path resolution (vault override vs built-in)."""

    def test_builtin_only(self, tmp_path: Path) -> None:
        builtin = tmp_path / "builtin" / "skills"
        builtin.mkdir(parents=True)
        (builtin / "intro.md").write_text("builtin intro", encoding="utf-8")

        path, source = _resolve_skill_path("intro", "mymod", builtin, None)
        assert path == builtin / "intro.md"
        assert source == "builtin"

    def test_user_overrides_builtin(self, tmp_path: Path) -> None:
        builtin = tmp_path / "builtin" / "skills"
        builtin.mkdir(parents=True)
        (builtin / "intro.md").write_text("builtin intro", encoding="utf-8")

        user_dir = tmp_path / "vault" / "tool_skills"
        user_mod = user_dir / "mymod"
        user_mod.mkdir(parents=True)
        (user_mod / "intro.md").write_text("user intro", encoding="utf-8")

        path, source = _resolve_skill_path("intro", "mymod", builtin, str(user_dir))
        assert path == user_mod / "intro.md"
        assert source == "user"

    def test_not_found(self, tmp_path: Path) -> None:
        builtin = tmp_path / "builtin" / "skills"
        builtin.mkdir(parents=True)

        path, source = _resolve_skill_path("nonexistent", "mymod", builtin, None)
        assert path is None
        assert source == ""

    def test_user_dir_without_matching_file(self, tmp_path: Path) -> None:
        builtin = tmp_path / "builtin" / "skills"
        builtin.mkdir(parents=True)
        (builtin / "intro.md").write_text("builtin", encoding="utf-8")

        user_dir = tmp_path / "vault" / "tool_skills"
        user_dir.mkdir(parents=True)

        path, source = _resolve_skill_path("intro", "mymod", builtin, str(user_dir))
        assert path == builtin / "intro.md"
        assert source == "builtin"

    def test_user_only_skill(self, tmp_path: Path) -> None:
        """Skill exists only in user vault (no built-in equivalent)."""
        builtin = tmp_path / "builtin" / "skills"
        builtin.mkdir(parents=True)

        user_dir = tmp_path / "vault" / "tool_skills"
        user_mod = user_dir / "mymod"
        user_mod.mkdir(parents=True)
        (user_mod / "custom.md").write_text("custom content", encoding="utf-8")

        path, source = _resolve_skill_path("custom", "mymod", builtin, str(user_dir))
        assert path == user_mod / "custom.md"
        assert source == "user"


# ===================================================================
# _truncate_to_budget
# ===================================================================


class TestTruncateToBudget:
    """Tests for token-budget truncation."""

    def test_within_budget(self) -> None:
        text = "Short text."
        result, truncated = _truncate_to_budget(text, 1000)
        assert result == text
        assert truncated is False

    def test_over_budget(self) -> None:
        text = "word " * 500
        result, truncated = _truncate_to_budget(text, 10)
        assert truncated is True
        assert "[truncated" in result


# ===================================================================
# load_module_skills
# ===================================================================


class TestLoadModuleSkills:
    """Tests for the main skill loading function."""

    def test_load_builtin(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "mymod" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "intro.md").write_text("# Intro\n\nHello.", encoding="utf-8")

        result = load_module_skills(
            "mymod", ["intro"], skills_dir,
            config=SkillLoaderConfig(),
        )
        assert len(result) == 1
        assert result[0].name == "intro"
        assert result[0].module_name == "mymod"
        assert result[0].source == "builtin"
        assert "Hello" in result[0].content
        assert result[0].token_count > 0

    def test_missing_skill_skipped(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        skills_dir = tmp_path / "mymod" / "skills"
        skills_dir.mkdir(parents=True)

        import logging
        with caplog.at_level(logging.WARNING):
            result = load_module_skills(
                "mymod", ["nonexistent"], skills_dir,
                config=SkillLoaderConfig(),
            )
        assert len(result) == 0
        assert "not found" in caplog.text

    def test_user_override(self, tmp_path: Path) -> None:
        builtin = tmp_path / "builtin" / "skills"
        builtin.mkdir(parents=True)
        (builtin / "guide.md").write_text("Built-in guide.", encoding="utf-8")

        user_dir = tmp_path / "vault" / "tool_skills"
        user_mod = user_dir / "mymod"
        user_mod.mkdir(parents=True)
        (user_mod / "guide.md").write_text("User guide override.", encoding="utf-8")

        cfg = SkillLoaderConfig(user_skills_dir=str(user_dir))
        result = load_module_skills("mymod", ["guide"], builtin, config=cfg)

        assert len(result) == 1
        assert result[0].source == "user"
        assert "User guide override" in result[0].content

    def test_multiple_skills(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "mymod" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "a.md").write_text("Skill A.", encoding="utf-8")
        (skills_dir / "b.md").write_text("Skill B.", encoding="utf-8")

        result = load_module_skills(
            "mymod", ["a", "b"], skills_dir,
            config=SkillLoaderConfig(),
        )
        assert len(result) == 2
        assert result[0].name == "a"
        assert result[1].name == "b"

    def test_preserves_order(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "mymod" / "skills"
        skills_dir.mkdir(parents=True)
        for name in ["z", "a", "m"]:
            (skills_dir / f"{name}.md").write_text(f"Skill {name}.", encoding="utf-8")

        result = load_module_skills(
            "mymod", ["z", "a", "m"], skills_dir,
            config=SkillLoaderConfig(),
        )
        assert [s.name for s in result] == ["z", "a", "m"]

    def test_frontmatter_stripped(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "mymod" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "fm.md").write_text(
            _make_frontmatter_skill(body="Only this body."),
            encoding="utf-8",
        )

        result = load_module_skills("mymod", ["fm"], skills_dir)
        assert "---" not in result[0].content
        assert "Only this body." in result[0].content

    def test_token_budget_truncates(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "mymod" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "big.md").write_text("word " * 5000, encoding="utf-8")

        cfg = SkillLoaderConfig(max_tokens_per_module=20)
        result = load_module_skills("mymod", ["big"], skills_dir, config=cfg)
        assert len(result) == 1
        assert "[truncated" in result[0].content

    def test_token_budget_exhaustion_skips_later_skills(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        skills_dir = tmp_path / "mymod" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "first.md").write_text("word " * 500, encoding="utf-8")
        (skills_dir / "second.md").write_text("another " * 500, encoding="utf-8")

        cfg = SkillLoaderConfig(max_tokens_per_module=10)
        import logging
        with caplog.at_level(logging.WARNING):
            result = load_module_skills(
                "mymod", ["first", "second"], skills_dir, config=cfg,
            )
        assert len(result) <= 1

    def test_empty_skill_names(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "mymod" / "skills"
        skills_dir.mkdir(parents=True)
        result = load_module_skills("mymod", [], skills_dir)
        assert result == []

    def test_default_config_when_none(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "mymod" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "x.md").write_text("Content.", encoding="utf-8")

        result = load_module_skills("mymod", ["x"], skills_dir, config=None)
        assert len(result) == 1


# ===================================================================
# get_builtin_skills_dir
# ===================================================================


class TestGetBuiltinSkillsDir:
    """Tests for the builtin skills directory helper."""

    def test_returns_correct_path(self) -> None:
        result = get_builtin_skills_dir("trello")
        assert result.name == "skills"
        assert result.parent.name == "trello"
        assert "harle/tools/trello/skills" in str(result)

    def test_dummy_module_exists(self) -> None:
        result = get_builtin_skills_dir("dummy")
        assert result.is_dir()
        assert (result / "usage.md").is_file()


# ===================================================================
# Registry Integration — Skills
# ===================================================================


class TestRegistrySkillsIntegration:
    """Tests for skill loading through the registry."""

    def test_register_with_skills(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skillmod" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "guide.md").write_text("Guide content.", encoding="utf-8")

        # Patch get_builtin_skills_dir to use tmp_path
        import harle.tools.registry as reg_mod
        original = reg_mod.get_builtin_skills_dir
        reg_mod.get_builtin_skills_dir = lambda name: tmp_path / name / "skills"
        try:
            registry = ToolRegistry()
            _run((_mod := _SkillTestModule()).initialize({}))
            registry.register_module(_mod, skill_names=["guide"])
            skills = registry.get_module_skills("skillmod")
            assert len(skills) == 1
            assert skills[0].name == "guide"
            assert skills[0].content == "Guide content."
        finally:
            reg_mod.get_builtin_skills_dir = original

    def test_register_without_skills(self) -> None:
        registry = ToolRegistry()
        mod = _SkillTestModule()
        _run(mod.initialize({}))
        registry.register_module(mod)
        assert registry.get_module_skills("skillmod") == []

    def test_get_skills_for_tools(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skillmod" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "guide.md").write_text("Guide.", encoding="utf-8")

        import harle.tools.registry as reg_mod
        original = reg_mod.get_builtin_skills_dir
        reg_mod.get_builtin_skills_dir = lambda name: tmp_path / name / "skills"
        try:
            registry = ToolRegistry()
            mod = _SkillTestModule()
            _run(mod.initialize({}))
            registry.register_module(mod, skill_names=["guide"])

            skills = registry.get_skills_for_tools(["skillmod_read"])
            assert len(skills) == 1
            assert skills[0].name == "guide"
        finally:
            reg_mod.get_builtin_skills_dir = original

    def test_get_skills_for_tools_deduplicates(self, tmp_path: Path) -> None:
        """Multiple tools from the same module should produce skills only once."""
        skills_dir = tmp_path / "skillmod" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "guide.md").write_text("Guide.", encoding="utf-8")

        import harle.tools.registry as reg_mod
        original = reg_mod.get_builtin_skills_dir
        reg_mod.get_builtin_skills_dir = lambda name: tmp_path / name / "skills"
        try:
            registry = ToolRegistry()
            mod = _SkillTestModule()
            _run(mod.initialize({}))
            registry.register_module(mod, skill_names=["guide"])

            skills = registry.get_skills_for_tools(["skillmod_read", "skillmod_read"])
            assert len(skills) == 1
        finally:
            reg_mod.get_builtin_skills_dir = original

    def test_get_skills_for_tools_unknown_tool(self) -> None:
        registry = ToolRegistry()
        mod = _SkillTestModule()
        _run(mod.initialize({}))
        registry.register_module(mod)
        skills = registry.get_skills_for_tools(["unknown_tool"])
        assert skills == []

    def test_get_skills_for_tools_multi_module(self, tmp_path: Path) -> None:
        """Skills from different modules are returned in request order."""
        for mod_name in ["skillmod", "second"]:
            sdir = tmp_path / mod_name / "skills"
            sdir.mkdir(parents=True)
            (sdir / "intro.md").write_text(f"{mod_name} intro.", encoding="utf-8")

        import harle.tools.registry as reg_mod
        original = reg_mod.get_builtin_skills_dir
        reg_mod.get_builtin_skills_dir = lambda name: tmp_path / name / "skills"
        try:
            registry = ToolRegistry()
            mod1 = _SkillTestModule()
            _run(mod1.initialize({}))
            registry.register_module(mod1, skill_names=["intro"])

            mod2 = _SecondModule()
            _run(mod2.initialize({}))
            registry.register_module(mod2, skill_names=["intro"])

            skills = registry.get_skills_for_tools(["second_action", "skillmod_read"])
            assert len(skills) == 2
            assert skills[0].module_name == "second"
            assert skills[1].module_name == "skillmod"
        finally:
            reg_mod.get_builtin_skills_dir = original

    def test_skill_loader_config_passed_to_loader(self, tmp_path: Path) -> None:
        """Registry passes its SkillLoaderConfig to load_module_skills."""
        skills_dir = tmp_path / "skillmod" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "big.md").write_text("word " * 5000, encoding="utf-8")

        import harle.tools.registry as reg_mod
        original = reg_mod.get_builtin_skills_dir
        reg_mod.get_builtin_skills_dir = lambda name: tmp_path / name / "skills"
        try:
            cfg = SkillLoaderConfig(max_tokens_per_module=15)
            registry = ToolRegistry(skill_loader_config=cfg)
            mod = _SkillTestModule()
            _run(mod.initialize({}))
            registry.register_module(mod, skill_names=["big"])

            skills = registry.get_module_skills("skillmod")
            assert len(skills) == 1
            assert "[truncated" in skills[0].content
        finally:
            reg_mod.get_builtin_skills_dir = original

    def test_dummy_module_builtin_skill(self) -> None:
        """The real dummy module's usage.md skill loads correctly."""
        from harle.tools.dummy.module import DummyModule

        registry = ToolRegistry()
        mod = DummyModule()
        _run(mod.initialize({}))
        registry.register_module(mod, skill_names=["usage"])

        skills = registry.get_module_skills("dummy")
        assert len(skills) == 1
        assert skills[0].name == "usage"
        assert skills[0].source == "builtin"
        assert "dummy_read" in skills[0].content

    def test_get_module_skills_unregistered(self) -> None:
        registry = ToolRegistry()
        assert registry.get_module_skills("nonexistent") == []
