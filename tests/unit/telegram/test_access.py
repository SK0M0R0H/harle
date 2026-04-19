"""Tests for Telegram access policy."""

from __future__ import annotations

from harle.config import Settings
from harle.telegram.access import AccessPolicy


def test_open_allows_any() -> None:
    s = Settings(HARLE_TELEGRAM_ACCESS_POLICY="open", HARLE_TELEGRAM_ALLOWED_USER_IDS="")
    p = AccessPolicy(s)
    assert p.is_allowed(1)
    assert p.is_allowed(999)


def test_allowlist_accepts_listed() -> None:
    s = Settings(
        HARLE_TELEGRAM_ACCESS_POLICY="allowlist",
        HARLE_TELEGRAM_ALLOWED_USER_IDS="10, 20 ,30",
    )
    p = AccessPolicy(s)
    assert p.is_allowed(10)
    assert p.is_allowed(20)
    assert p.is_allowed(30)
    assert not p.is_allowed(11)


def test_allowlist_empty_denies() -> None:
    s = Settings(HARLE_TELEGRAM_ACCESS_POLICY="allowlist", HARLE_TELEGRAM_ALLOWED_USER_IDS="")
    p = AccessPolicy(s)
    assert not p.is_allowed(1)


def test_unknown_policy_treated_as_allowlist() -> None:
    s = Settings(HARLE_TELEGRAM_ACCESS_POLICY="bogus", HARLE_TELEGRAM_ALLOWED_USER_IDS="5")
    p = AccessPolicy(s)
    assert p.is_allowed(5)
    assert not p.is_allowed(6)


def test_refusal_message_nonempty() -> None:
    s = Settings()
    assert "authorized" in AccessPolicy(s).refusal_message().lower()


def test_none_user_denied() -> None:
    s = Settings(HARLE_TELEGRAM_ACCESS_POLICY="open")
    assert not AccessPolicy(s).is_allowed(None)
