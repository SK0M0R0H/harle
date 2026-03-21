"""Agent Runner vs legacy LLM execution (orchestrator mixin)."""

from __future__ import annotations

from harle.orchestrator.agents import KNOWN_ROLES, tool_names_for_role
from harle.orchestrator.role_tool_modules import DEFAULT_ROLE_TOOL_MODULES
from harle.orchestrator.reflection import ReflectionConfig
from harle.orchestrator.state import DEFAULT_AGENT_ROLE, AgentResult

TOOL_THINKING_INSTRUCTION: str = (
    "\n\nBefore calling any tool, briefly state what you know so far, "
    "what you still need, and why you are calling this specific tool. "
    "This helps maintain reasoning coherence across multiple steps."
)


class ExecutionMixin:
    """Route chat execution to the Agents SDK or the legacy provider."""

    def _resolved_role_tool_modules(self) -> dict[str, list[str]]:
        """Effective role → module mapping (service override or built-in defaults)."""
        if self.role_tool_modules is not None:
            return self.role_tool_modules
        return dict(DEFAULT_ROLE_TOOL_MODULES)

    def _reflection_config(self) -> ReflectionConfig | None:
        """Level 4 reflection settings for the Agents SDK path only."""
        if not self.use_agent_runner:
            return None
        return ReflectionConfig.from_settings_strings(
            enabled=self.reflection_enabled,
            model=self.effective_reflection_critic_model(),
            min_tool_calls=self.reflection_min_tool_calls,
            trigger_keywords_csv=self.reflection_trigger_keywords,
            trigger_roles_csv=self.reflection_trigger_roles,
            improvement_max_turns=self.reflection_improvement_max_turns,
        )

    def _build_instructions(self, system_prompt: str | None, has_tools: bool) -> str:
        """Build agent instructions from the system prompt and tool metadata."""
        base = system_prompt or (
            "You are Harle, a concise assistant. "
            "Answer directly and keep structure clear."
        )

        if not has_tools or self.tool_registry is None:
            return base

        parts = [base]
        registry = self.tool_registry
        all_tool_names = registry.list_all_tools()
        skills = registry.get_skills_for_tools(all_tool_names)
        if skills:
            skill_sections = [
                f"## Tool Skill: {s.name}\n\n{s.content}" for s in skills
            ]
            parts.append("\n\n".join(skill_sections))

        parts.append(TOOL_THINKING_INSTRUCTION)
        return "\n\n".join(parts)

    def _build_instructions_for_tools(
        self,
        system_prompt: str | None,
        tool_names: list[str],
    ) -> str:
        """Build instructions from *system_prompt* and skills for *tool_names* only."""
        base = system_prompt or (
            "You are Harle, a concise assistant. "
            "Answer directly and keep structure clear."
        )
        if not tool_names or self.tool_registry is None:
            return base
        skills = self.tool_registry.get_skills_for_tools(tool_names)
        parts = [base]
        if skills:
            skill_sections = [
                f"## Tool Skill: {s.name}\n\n{s.content}" for s in skills
            ]
            parts.append("\n\n".join(skill_sections))
        parts.append(TOOL_THINKING_INSTRUCTION)
        return "\n\n".join(parts)

    def _execute_with_runner(
        self,
        *,
        user_message: str,
        system_prompt: str | None,
        context: str,
        agent_role: str,
        routing_method_from_router: str,
    ) -> AgentResult:
        """Execute via the Agents SDK Runner with optional tool support."""
        from harle.orchestrator.runner_execution import run_agent_execution

        role_instructions: dict[str, str] | None = None
        handoff_records_out: list | None = None
        multi_agent = False

        if self.tool_registry is not None and self.context_assembler is not None:
            multi_agent = True
            role_instructions = {}
            for role in KNOWN_ROLES:
                if role == agent_role:
                    base_text = system_prompt
                else:
                    base_text = self.context_assembler.load_role_prompt(
                        role=role,
                        context=context,
                    )
                tnames = tool_names_for_role(
                    self.tool_registry,
                    role,
                    role_tool_modules=self._resolved_role_tool_modules(),
                )
                role_instructions[role] = self._build_instructions_for_tools(
                    base_text,
                    tnames,
                )
            handoff_records_out = []

        r = run_agent_execution(
            user_message=user_message,
            system_prompt=system_prompt,
            build_instructions=self._build_instructions,
            tool_registry=self.tool_registry,
            model_tier_config=self.effective_model_tier_config(),
            complex_execution_tier=self.complex_execution_tier,
            reflection_critic_model=self.effective_reflection_critic_model(),
            max_iterations=self.max_iterations,
            planning_enabled=self.planning_enabled,
            planning_max_turns=self.planning_max_turns,
            planned_max_turns=self.planned_max_turns,
            reflection_config=self._reflection_config(),
            agent_role=agent_role,
            multi_agent=multi_agent,
            role_instructions=role_instructions,
            handoff_records_out=handoff_records_out,
            routing_method_from_router=routing_method_from_router,
            role_tool_modules=self._resolved_role_tool_modules(),
        )
        return AgentResult(
            text=r.text,
            tools_called=r.tools_called,
            turns_used=r.turns_used,
            plan_text=r.plan_text,
            plan_revisions=r.plan_revisions,
            planning_tool_context=r.planning_tool_context,
            routing_method=r.routing_method,
            reflection_triggered=r.reflection_triggered,
            reflection_improved=r.reflection_improved,
            reflection_record=r.reflection_record,
            handoffs=r.handoffs,
            final_agent=r.final_agent,
            models_used=r.models_used or None,
        )

    def _execute_with_provider(
        self,
        *,
        user_message: str,
        context: str,
        conversation_id: str | None,
        system_prompt: str | None,
    ) -> AgentResult:
        """Execute via the legacy LLM provider (single call, no tools)."""
        text = self.llm_provider.generate(
            prompt=user_message,
            context=context,
            conversation_id=conversation_id,
            system_prompt=system_prompt,
        )
        return AgentResult(text=text)

    def _execute(
        self,
        *,
        user_message: str,
        context: str,
        conversation_id: str | None,
        system_prompt: str | None,
        agent_role: str = DEFAULT_AGENT_ROLE,
        routing_method_from_router: str = "default",
    ) -> AgentResult:
        """Route execution to the Runner or the legacy provider."""
        if self.use_agent_runner:
            return self._execute_with_runner(
                user_message=user_message,
                system_prompt=system_prompt,
                context=context,
                agent_role=agent_role,
                routing_method_from_router=routing_method_from_router,
            )
        return self._execute_with_provider(
            user_message=user_message,
            context=context,
            conversation_id=conversation_id,
            system_prompt=system_prompt,
        )
