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
