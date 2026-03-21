"""Central tool registry for the Tool Module Layer.

The :class:`ToolRegistry` discovers modules, indexes their tool functions,
and bridges between :class:`BaseToolModule` instances and the OpenAI Agents
SDK's ``FunctionTool`` objects.

Typical lifecycle::

    registry = ToolRegistry()

    # Startup — register each enabled module
    await module.initialize(config)
    registry.register_module(module)

    # Request time — get SDK-compatible tools for the agent
    tools = registry.get_agent_tools(["search_web", "fetch_page"])

    # Validate tool inputs before execution
    results = registry.validate_tool_inputs("run_script", {"script": "analyze.py"}, command="python")

    # Shutdown
    await registry.shutdown_all()
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
from typing import Any, Callable

from agents import FunctionTool, function_tool

from harle.debug import etrace
from harle.tools.base import BaseToolModule
from harle.tools.constraints import ConstraintConfig, ConstraintViolation, validate_inputs
from harle.tools.permissions import OperationMode, check_permission
from harle.tools.skills import (
    LoadedSkill,
    SkillLoaderConfig,
    get_builtin_skills_dir,
    load_module_skills,
)

logger = logging.getLogger(__name__)


class ToolRegistryError(Exception):
    """Raised for registry-level errors (e.g. naming conflicts)."""


def _make_traced_tool(tool_name: str, fn: Callable[..., Any], module_name: str) -> Callable[..., Any]:
    """Wrap a tool function so each invocation is traced with etrace.

    The wrapper preserves fn's __name__, __doc__, and signature so that
    the agents SDK can build the correct tool schema and description.
    """
    if asyncio.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def traced_async(*args: Any, **kwargs: Any) -> Any:
            with etrace.span(
                f"Tool: {tool_name}",
                level=etrace.STEP,
                module=module_name,
            ):
                etrace.detail(
                    "Tool invoked",
                    module=module_name,
                    tool=tool_name,
                )
                result = await fn(*args, **kwargs)
                etrace.detail(
                    "Tool completed",
                    module=module_name,
                    tool=tool_name,
                )
                return result
        try:
            traced_async.__signature__ = inspect.signature(fn)
        except (ValueError, TypeError):
            pass
        return traced_async  # type: ignore[return-value]

    @functools.wraps(fn)
    def traced_sync(*args: Any, **kwargs: Any) -> Any:
        with etrace.span(
            f"Tool: {tool_name}",
            level=etrace.STEP,
            module=module_name,
        ):
            etrace.detail(
                "Tool invoked",
                module=module_name,
                tool=tool_name,
            )
            result = fn(*args, **kwargs)
            etrace.detail(
                "Tool completed",
                module=module_name,
                tool=tool_name,
            )
            return result
    try:
        traced_sync.__signature__ = inspect.signature(fn)
    except (ValueError, TypeError):
        pass
    return traced_sync


class ToolRegistry:
    """Central catalog of all registered tool modules and their functions.

    Attributes:
        _modules: Mapping from module name → module instance.
        _tools: Mapping from function name → (module, function) tuple.
        _sdk_tools: Cached ``FunctionTool`` objects, keyed by function name.
        _module_modes: Mapping from module name → operation mode.
        _module_constraints: Mapping from module name → constraint config.
        _module_skills: Mapping from module name → loaded skills.
        _skill_loader_config: Global skill loader configuration.
    """

    def __init__(
        self,
        skill_loader_config: SkillLoaderConfig | None = None,
    ) -> None:
        self._modules: dict[str, BaseToolModule] = {}
        self._tools: dict[str, tuple[BaseToolModule, Callable]] = {}
        self._sdk_tools: dict[str, FunctionTool] = {}
        self._module_modes: dict[str, OperationMode] = {}
        self._module_constraints: dict[str, ConstraintConfig] = {}
        self._module_skills: dict[str, list[LoadedSkill]] = {}
        self._skill_loader_config = skill_loader_config or SkillLoaderConfig()

    def register_module(
        self,
        module: BaseToolModule,
        *,
        mode: OperationMode | str = OperationMode.PROPOSE,
        constraints: ConstraintConfig | dict | None = None,
        skill_names: list[str] | None = None,
    ) -> None:
        """Register a module and index its tool functions.

        Raises :class:`ToolRegistryError` if a tool function name conflicts
        with an already-registered tool.

        Args:
            module: An initialised :class:`BaseToolModule` instance.
            mode: The operation mode for this module (controls approval
                behaviour).  Defaults to ``propose``.
            constraints: Security constraints for this module's tools.
                Accepts a :class:`ConstraintConfig`, a raw dict (from
                config YAML), or ``None`` (no constraints).
            skill_names: List of skill filenames (without ``.md``) to
                load for this module.  Corresponds to the ``skills``
                list in the module's config block.  ``None`` or ``[]``
                means no skills.
        """
        if module.name in self._modules:
            raise ToolRegistryError(
                f"Module '{module.name}' is already registered."
            )

        resolved_mode = (
            OperationMode(mode) if isinstance(mode, str) else mode
        )
        self._module_modes[module.name] = resolved_mode
        self._modules[module.name] = module

        user_config: ConstraintConfig
        if isinstance(constraints, dict):
            user_config = ConstraintConfig.from_dict(constraints)
        elif isinstance(constraints, ConstraintConfig):
            user_config = constraints
        else:
            user_config = ConstraintConfig()

        module_defaults = module.default_constraints()
        if module_defaults is not None:
            self._module_constraints[module.name] = module_defaults.merge(user_config)
        else:
            self._module_constraints[module.name] = user_config

        if skill_names:
            builtin_dir = get_builtin_skills_dir(module.name)
            self._module_skills[module.name] = load_module_skills(
                module_name=module.name,
                skill_names=skill_names,
                builtin_skills_dir=builtin_dir,
                config=self._skill_loader_config,
            )
        else:
            self._module_skills[module.name] = []

        for fn in module.get_tools():
            fn_name = fn.__name__
            if fn_name in self._tools:
                existing_module, _ = self._tools[fn_name]
                raise ToolRegistryError(
                    f"Tool name '{fn_name}' is already registered by module "
                    f"'{existing_module.name}'. Rename the function in module "
                    f"'{module.name}'."
                )
            self._tools[fn_name] = (module, fn)
            traced = _make_traced_tool(fn_name, fn, module.name)
            self._sdk_tools[fn_name] = function_tool(traced, strict_mode=False)

        logger.info(
            "Registered module '%s' with %d tool(s): %s",
            module.name,
            len(module.get_tools()),
            [fn.__name__ for fn in module.get_tools()],
        )

    def get_module(self, module_name: str) -> BaseToolModule | None:
        """Return a registered module by name, or ``None``.

        Args:
            module_name: The unique module identifier.

        Returns:
            The module instance, or ``None`` if not found.
        """
        return self._modules.get(module_name)

    async def health_check_all(self) -> dict[str, bool]:
        """Run health_check() on each registered module.

        Returns:
            Mapping from module name to healthy (True/False).
        """
        result: dict[str, bool] = {}
        for name, module in self._modules.items():
            try:
                result[name] = await module.health_check()
            except Exception:
                result[name] = False
        return result

    def get_module_for_tool(self, tool_name: str) -> BaseToolModule | None:
        """Return the module that owns *tool_name*, or ``None``.

        Args:
            tool_name: The tool function's ``__name__``.

        Returns:
            The owning module, or ``None`` if not found.
        """
        entry = self._tools.get(tool_name)
        return entry[0] if entry else None

    def get_module_tool_names(self, module_name: str) -> list[str]:
        """Return registered tool function names owned by *module_name*.

        Args:
            module_name: The module's :attr:`~harle.tools.base.BaseToolModule.name`.

        Returns:
            Sorted list of tool function names (``__name__`` values).
        """
        result: list[str] = []
        for tool_name, (mod, _fn) in self._tools.items():
            if mod.name == module_name:
                result.append(tool_name)
        result.sort()
        return result

    def get_agent_tools(self, tool_names: list[str]) -> list[FunctionTool]:
        """Return ``FunctionTool`` objects for the requested tool names.

        Unknown names are skipped with a warning.

        Args:
            tool_names: Function names to look up.

        Returns:
            A list of SDK-compatible ``FunctionTool`` objects.
        """
        result: list[FunctionTool] = []
        for name in tool_names:
            sdk_tool = self._sdk_tools.get(name)
            if sdk_tool is None:
                logger.warning("Requested tool '%s' is not registered.", name)
                continue
            result.append(sdk_tool)
        return result

    def get_skills_for_tools(self, tool_names: list[str]) -> list[LoadedSkill]:
        """Return loaded skills for the modules that own *tool_names*.

        If multiple tools belong to the same module, skills for that
        module are included only once.  Unknown tool names are silently
        skipped (they already produce a warning in :meth:`get_agent_tools`).

        Args:
            tool_names: Function names whose owning modules' skills
                should be returned.

        Returns:
            A deduplicated list of :class:`LoadedSkill` objects, ordered
            by the first occurrence of each module in *tool_names*.
        """
        seen_modules: set[str] = set()
        result: list[LoadedSkill] = []
        for name in tool_names:
            module = self.get_module_for_tool(name)
            if module is None or module.name in seen_modules:
                continue
            seen_modules.add(module.name)
            result.extend(self._module_skills.get(module.name, []))
        return result

    def get_module_skills(self, module_name: str) -> list[LoadedSkill]:
        """Return the loaded skills for *module_name*.

        Args:
            module_name: The unique module identifier.

        Returns:
            List of :class:`LoadedSkill` for the module, or ``[]``
            if the module has no skills or is not registered.
        """
        return self._module_skills.get(module_name, [])

    def check_tool_permission(self, tool_name: str) -> dict:
        """Check whether *tool_name* is allowed under its module's mode.

        Delegates to :func:`harle.tools.permissions.check_permission`.

        Args:
            tool_name: The tool function's ``__name__``.

        Returns:
            A dict with ``allowed``, ``needs_approval``, ``permission``,
            ``mode``, and optionally ``reason`` keys.

        Raises:
            KeyError: If *tool_name* is not registered.
        """
        if tool_name not in self._tools:
            raise KeyError(f"Tool '{tool_name}' is not registered.")
        module, fn = self._tools[tool_name]
        mode = self._module_modes[module.name]
        return check_permission(fn, mode)

    def get_module_constraints(self, module_name: str) -> ConstraintConfig:
        """Return the constraint config for *module_name*.

        Args:
            module_name: The unique module identifier.

        Returns:
            The module's :class:`ConstraintConfig` (empty if none
            configured).

        Raises:
            KeyError: If *module_name* is not registered.
        """
        if module_name not in self._module_constraints:
            raise KeyError(f"Module '{module_name}' is not registered.")
        return self._module_constraints[module_name]

    def validate_tool_inputs(
        self,
        tool_name: str,
        args: dict[str, Any],
        *,
        command: str | None = None,
        paths: list[str] | None = None,
        host: str | None = None,
    ) -> dict[str, str]:
        """Validate *args* against the constraints of the module that owns *tool_name*.

        This is Security Layer 3.  Call this **before** executing the
        tool function.

        Args:
            tool_name: The tool function's ``__name__``.
            args: The tool function's keyword arguments.
            command: Executable name to check against
                ``allowed_commands``.
            paths: Filesystem paths to check against
                ``allowed_paths`` / ``blocked_paths``.
            host: Network host to check against ``allowed_hosts``.

        Returns:
            A dict of ``{constraint_type: "pass" | "skip"}`` for
            audit logging.

        Raises:
            KeyError: If *tool_name* is not registered.
            ConstraintViolation: If any constraint check fails.
        """
        if tool_name not in self._tools:
            raise KeyError(f"Tool '{tool_name}' is not registered.")
        module, _fn = self._tools[tool_name]
        config = self._module_constraints[module.name]
        return validate_inputs(
            args, config, command=command, paths=paths, host=host,
        )

    def list_all_tools(self) -> list[str]:
        """Return names of all registered tools (for logging / debugging).

        Returns:
            Sorted list of tool function names.
        """
        return sorted(self._tools.keys())

    def list_modules(self) -> list[str]:
        """Return names of all registered modules.

        Returns:
            Sorted list of module names.
        """
        return sorted(self._modules.keys())

    async def shutdown_all(self) -> None:
        """Call ``shutdown()`` on every registered module.

        Errors during shutdown are logged but do not prevent other modules
        from shutting down.
        """
        for name, module in self._modules.items():
            try:
                await module.shutdown()
                logger.info("Module '%s' shut down.", name)
            except Exception:
                logger.exception("Error shutting down module '%s'.", name)

    def __len__(self) -> int:
        """Return the number of registered tools."""
        return len(self._tools)

    def __contains__(self, tool_name: str) -> bool:
        """Check whether *tool_name* is registered."""
        return tool_name in self._tools
