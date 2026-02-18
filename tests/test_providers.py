"""Tests for harle.llm.providers — EchoProvider."""

from __future__ import annotations

import pytest

from harle.llm.providers import EchoProvider


class TestEchoProvider:
    def test_returns_string_with_required_metadata(self) -> None:
        provider = EchoProvider()
        result = provider.generate(
            prompt="hello",
            context="personal",
            conversation_id=None,
        )
        assert isinstance(result, str)
        assert "OPENAI_API_KEY" in result
        assert "context=personal" in result
        assert "message=hello" in result

    @pytest.mark.parametrize("conversation_id", [None, "conv-1"])
    @pytest.mark.parametrize("system_prompt", [None, "Custom system prompt"])
    def test_conversation_and_system_prompt_do_not_change_echo_payload(
        self,
        conversation_id: str | None,
        system_prompt: str | None,
    ) -> None:
        provider = EchoProvider()
        result = provider.generate(
            prompt="hi",
            context="work",
            conversation_id=conversation_id,
            system_prompt=system_prompt,
        )
        assert "OPENAI_API_KEY" in result
        assert "message=hi" in result
        assert "context=work" in result
