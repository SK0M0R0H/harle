"""Skill loader for the Tool Module Layer.

Skills are Markdown files that provide the LLM with domain knowledge
about *how* to use a module's tools effectively.  They are resolved
from two sources with vault overrides taking precedence:

1. **User vault** — ``<vault>/tool_skills/<module>/<name>.md``
2. **Built-in** — ``src/harle/tools/<module>/skills/<name>.md``

Which skills are active is controlled by the ``skills`` list in each
module's config block, not by the module class.

Typical usage::

    loader_cfg = SkillLoaderConfig(
        user_skills_dir="/home/user/vault/tool_skills",
        max_tokens_per_module=2000,
    )
    skills = load_module_skills(
        module_name="trello",
        skill_names=["triage", "conventions"],
        builtin_skills_dir=Path("src/harle/tools/trello/skills"),
        config=loader_cfg,
    )
"""

from __future__ import annotations

import importlib.util
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from harle.context.tokenizer import count_tokens

logger = logging.getLogger(__name__)

_DEFAULT_MAX_TOKENS_PER_MODULE: int = 2000


@dataclass(frozen=True)
class SkillLoaderConfig:
    """Global configuration for the skill loading system.

    Args:
        user_skills_dir: Root directory for user-provided skill
            overrides (``<vault>/tool_skills/``).  ``None`` disables
            vault overrides.
        max_tokens_per_module: Token budget for all skills belonging
            to a single module.  Skills exceeding this are truncated.
    """

    user_skills_dir: str | None = None
    max_tokens_per_module: int = _DEFAULT_MAX_TOKENS_PER_MODULE

    @classmethod
    def from_config(cls, raw: dict | None) -> SkillLoaderConfig:
        """Build from the ``tool_skills`` section of ``config.yaml``.

        Args:
            raw: The ``tool_skills`` dict, or ``None``.

        Returns:
            A :class:`SkillLoaderConfig`.
        """
        if not raw:
            return cls()
        user_dir = raw.get("user_skills_dir")
        if user_dir:
            user_dir = os.path.expandvars(user_dir)
            user_dir = os.path.expanduser(user_dir)
        return cls(
            user_skills_dir=user_dir,
            max_tokens_per_module=raw.get(
                "max_tokens_per_module", _DEFAULT_MAX_TOKENS_PER_MODULE,
            ),
        )


@dataclass(frozen=True)
class LoadedSkill:
    """A single loaded skill file.

    Args:
        name: Skill name (filename without ``.md``).
        module_name: The module this skill belongs to.
        source: ``"user"`` or ``"builtin"``.
        content: The Markdown content of the skill file.
        token_count: Token count of *content*.
    """

    name: str
    module_name: str
    source: str
    content: str
    token_count: int


def _resolve_skill_path(
    skill_name: str,
    module_name: str,
    builtin_skills_dir: Path,
    user_skills_dir: str | None,
) -> tuple[Path | None, str]:
    """Resolve a skill name to a file path.

    Checks the user vault first, then the built-in directory.

    Args:
        skill_name: Skill filename without ``.md``.
        module_name: The owning module's name.
        builtin_skills_dir: Path to the module's ``skills/`` directory.
        user_skills_dir: Root of the user's ``tool_skills/`` tree, or
            ``None``.

    Returns:
        A ``(path, source)`` tuple.  *path* is ``None`` if the skill
        was not found in either location.  *source* is ``"user"`` or
        ``"builtin"``.
    """
    filename = f"{skill_name}.md"

    if user_skills_dir:
        user_path = Path(user_skills_dir) / module_name / filename
        if user_path.is_file():
            return user_path, "user"

    builtin_path = builtin_skills_dir / filename
    if builtin_path.is_file():
        return builtin_path, "builtin"

    return None, ""


def _read_skill_file(path: Path) -> str:
    """Read a skill file, stripping YAML frontmatter.

    If the file starts with ``---``, everything up to and including
    the closing ``---`` is removed so that only the Markdown body is
    injected into the LLM context.

    Args:
        path: Path to the ``.md`` file.

    Returns:
        The Markdown content (without frontmatter).
    """
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2].lstrip("\n")
    return text


def _truncate_to_budget(
    content: str,
    max_tokens: int,
) -> tuple[str, bool]:
    """Truncate *content* to fit within *max_tokens*.

    Uses a binary-search approach on character length to find the
    longest prefix that fits the token budget, since token boundaries
    don't align with character boundaries.

    Args:
        content: The text to potentially truncate.
        max_tokens: Maximum allowed tokens.

    Returns:
        A ``(text, was_truncated)`` tuple.
    """
    token_count = count_tokens(content)
    if token_count <= max_tokens:
        return content, False

    ratio = max_tokens / token_count
    estimated_chars = int(len(content) * ratio * 0.95)
    truncated = content[:estimated_chars]

    while count_tokens(truncated) > max_tokens and len(truncated) > 0:
        estimated_chars = int(len(truncated) * 0.9)
        truncated = truncated[:estimated_chars]

    truncated = truncated.rstrip()
    truncated += "\n\n[truncated — skill content exceeded token budget]"
    return truncated, True


def load_module_skills(
    module_name: str,
    skill_names: list[str],
    builtin_skills_dir: Path,
    config: SkillLoaderConfig | None = None,
) -> list[LoadedSkill]:
    """Load skills for a module by resolving names to Markdown files.

    For each name in *skill_names*:
    1. Check ``<user_skills_dir>/<module_name>/<name>.md`` (vault override).
    2. Fall back to ``<builtin_skills_dir>/<name>.md``.
    3. If neither exists, log a warning and skip.

    The combined token count of all loaded skills is tracked against
    ``config.max_tokens_per_module``.  If the budget is exceeded the
    last skill(s) are truncated.

    Args:
        module_name: The module's unique identifier.
        skill_names: Skill filenames (without ``.md``).
        builtin_skills_dir: Path to the module's built-in ``skills/``
            directory.
        config: Global skill loader settings.  Uses defaults when
            ``None``.

    Returns:
        A list of :class:`LoadedSkill` objects in the order they were
        requested.
    """
    if config is None:
        config = SkillLoaderConfig()

    loaded: list[LoadedSkill] = []
    tokens_used = 0

    for name in skill_names:
        path, source = _resolve_skill_path(
            name, module_name, builtin_skills_dir, config.user_skills_dir,
        )
        if path is None:
            logger.warning(
                "Skill '%s' not found for module '%s' (checked built-in "
                "and user vault). Skipping.",
                name, module_name,
            )
            continue

        content = _read_skill_file(path)
        token_count = count_tokens(content)
        remaining_budget = config.max_tokens_per_module - tokens_used

        if remaining_budget <= 0:
            logger.warning(
                "Token budget exhausted for module '%s'. Skipping "
                "skill '%s' (%d tokens).",
                module_name, name, token_count,
            )
            continue

        if token_count > remaining_budget:
            content, _ = _truncate_to_budget(content, remaining_budget)
            token_count = count_tokens(content)
            logger.warning(
                "Skill '%s' for module '%s' truncated to fit token "
                "budget (%d → %d tokens).",
                name, module_name, count_tokens(_read_skill_file(path)),
                token_count,
            )

        loaded.append(LoadedSkill(
            name=name,
            module_name=module_name,
            source=source,
            content=content,
            token_count=token_count,
        ))
        tokens_used += token_count

    logger.info(
        "Loaded %d skill(s) for module '%s': %s (%d tokens total)",
        len(loaded), module_name,
        [s.name for s in loaded], tokens_used,
    )
    return loaded


def get_builtin_skills_dir(module_name: str) -> Path:
    """Return the conventional built-in skills directory for a module.

    The convention is ``<harle.tools.<module_name>>/skills/`` on disk.

    Resolution prefers the filesystem location of the importable package
    ``harle.tools.<module_name>`` (via :func:`importlib.util.find_spec`).
    That matches editable installs where this file may live under
    ``site-packages`` while tool packages (and their ``skills/*.md`` files)
    still resolve from the source tree.

    If that package is not importable, falls back to
    ``Path(__file__).parent / <module_name> / "skills"``.

    Args:
        module_name: The module's unique identifier.

    Returns:
        Path to the module's built-in ``skills/`` directory (may not
        exist on disk).
    """
    spec = importlib.util.find_spec(f"harle.tools.{module_name}")
    if spec is not None and spec.submodule_search_locations:
        root = Path(next(iter(spec.submodule_search_locations)))
        return root / "skills"
    tools_package_dir = Path(__file__).parent
    return tools_package_dir / module_name / "skills"
