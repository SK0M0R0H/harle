"""Tests for harle.llm.providers — EchoProvider."""

from __future__ import annotations

from harle.llm.providers import EchoProvider


class TestEchoProvider:
    def test_returns_string(self) -> None:
        provider = EchoProvider()
        result = provider.generate(
            prompt="hello",
            context="personal",
            conversation_id=None,
        )
        assert isinstance(result, str)

    def test_contains_prompt(self) -> None:
        provider = EchoProvider()
        result = provider.generate(
            prompt="my test message",
            context="work",
            conversation_id=None,
        )
        assert "my test message" in result

    def test_contains_context(self) -> None:
        provider = EchoProvider()
        result = provider.generate(
            prompt="hi",
            context="work",
            conversation_id=None,
        )
        assert "context=work" in result

    def test_mentions_missing_api_key(self) -> None:
        provider = EchoProvider()
        result = provider.generate(
            prompt="hi",
            context="personal",
            conversation_id=None,
        )
        assert "OPENAI_API_KEY" in result

    def test_conversation_id_ignored(self) -> None:
        provider = EchoProvider()
        r1 = provider.generate(prompt="hi", context="personal", conversation_id=None)
        r2 = provider.generate(prompt="hi", context="personal", conversation_id="conv-1")
        # Both contain same prompt/context info
        assert "message=hi" in r1
        assert "message=hi" in r2

    def test_system_prompt_ignored(self) -> None:
        """EchoProvider accepts but ignores the system_prompt parameter."""
        provider = EchoProvider()
        result = provider.generate(
            prompt="hi",
            context="work",
            conversation_id=None,
            system_prompt="Custom system prompt",
        )
        assert "message=hi" in result
        assert "context=work" in result

    def test_system_prompt_defaults_to_none(self) -> None:
        """Calling without system_prompt still works (backward compat)."""
        provider = EchoProvider()
        result = provider.generate(
            prompt="hello",
            context="personal",
            conversation_id=None,
        )
        assert isinstance(result, str)
        assert "hello" in result
