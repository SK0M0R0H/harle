"""Agent Runner vs legacy LLM execution (orchestrator mixin)."""

from __future__ import annotations

from harle.orchestrator.reflection import ReflectionConfig
from harle.orchestrator.state import DEFAULT_AGENT_ROLE, AgentResult

TOOL_THINKING_INSTRUCTION: str = (
    "\n\nBefore calling any tool, briefly state what you know so far, "
    "what you still need, and why you are calling this specific tool. "
    "This helps maintain reasoning coherence across multiple steps."
)


class ExecutionMixin:
    """Route chat execution to the Agents SDK or the legacy provider."""

    def _reflection_config(self) -> ReflectionConfig | None:
        """Level 4 reflection settings for the Agents SDK path only."""
        if not self.use_agent_runner:
            return None
        return ReflectionConfig.from_settings_strings(
            enabled=self.reflection_enabled,
            model=self.reflection_model,
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

    def _execute_with_runner(
        self,
        *,
        user_message: str,
        system_prompt: str | None,
    ) -> AgentResult:
        """Execute via the Agents SDK Runner with optional tool support."""
        from harle.orchestrator.runner_execution import run_agent_execution

        r = run_agent_execution(
            user_message=user_message,
            system_prompt=system_prompt,
            build_instructions=self._build_instructions,
            tool_registry=self.tool_registry,
            model=self.model,
            max_iterations=self.max_iterations,
            planning_enabled=self.planning_enabled,
            planning_model=self.planning_model,
            planning_max_turns=self.planning_max_turns,
            planned_max_turns=self.planned_max_turns,
            reflection_config=self._reflection_config(),
            reflection_model=self.reflection_model,
            agent_role=DEFAULT_AGENT_ROLE,
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
    ) -> AgentResult:
        """Route execution to the Runner or the legacy provider."""
        if self.use_agent_runner:
            return self._execute_with_runner(
                user_message=user_message,
                system_prompt=system_prompt,
            )
        return self._execute_with_provider(
            user_message=user_message,
            context=context,
            conversation_id=conversation_id,
            system_prompt=system_prompt,
        )
