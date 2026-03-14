"""Interview helper functions — LLM generation and topic selection.

Extracted from the CaptureEngine to keep file sizes manageable.
Provides LLM-backed question generation, summary generation, document
draft generation, and topic ordering/selection utilities.
"""

from __future__ import annotations

import logging
from pathlib import Path

from openai import OpenAI

from harle.capture.prompts import (
    INTERVIEW_SYSTEM_PROMPT,
    build_draft_prompt,
    build_integrate_edit_prompt,
    build_summary_prompt,
)
from harle.capture.registry import TopicRegistry
from harle.capture.run import CaptureRun
from harle.capture.topics import Topic

logger = logging.getLogger(__name__)


class InterviewLLM:
    """LLM generation helpers for the interview engine.

    Handles adaptive question generation, summary generation, and
    vault document draft generation. Falls back to simple templates
    when no API key is available.
    """

    def __init__(
        self,
        *,
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
        vault_root: Path | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._vault_root = vault_root
        self._client: OpenAI | None = None

    @property
    def has_llm(self) -> bool:
        """Whether an LLM API key is configured."""
        return bool(self._api_key)

    def get_client(self) -> OpenAI:
        """Lazy-init the OpenAI client."""
        if self._client is None:
            if not self._api_key:
                raise RuntimeError(
                    "OPENAI_API_KEY is required for the interview mode. "
                    "Set it in your environment or use 'harle capture quick' instead."
                )
            self._client = OpenAI(api_key=self._api_key)
        return self._client

    def generate(self, system: str, user: str) -> str:
        """Call the LLM and return the response text."""
        client = self.get_client()
        response = client.responses.create(
            model=self._model,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.output_text.strip()

    def generate_summary(self, topic: Topic, exchanges: list[dict]) -> str:
        """Generate a confirmation summary of collected answers."""
        if not exchanges:
            return "Nothing captured for this topic yet."
        if not self._api_key:
            return self._fallback_summary(topic, exchanges)

        prompt = build_summary_prompt(topic, exchanges)
        try:
            return self.generate(INTERVIEW_SYSTEM_PROMPT, prompt)
        except Exception:
            logger.warning("LLM summary failed, using fallback")
            return self._fallback_summary(topic, exchanges)

    def generate_draft(self, topic: Topic, exchanges: list[dict]) -> str:
        """Generate a vault document draft from interview answers."""
        existing = self._load_existing_content(topic.vault_target)
        if not self._api_key:
            return self._fallback_draft(topic, exchanges)

        prompt = build_draft_prompt(topic, exchanges, existing)
        try:
            return self.generate(INTERVIEW_SYSTEM_PROMPT, prompt)
        except Exception:
            logger.warning("LLM draft generation failed, using fallback")
            return self._fallback_draft(topic, exchanges)

    def integrate_edit(self, topic: Topic, current_draft: str, user_edit: str) -> str:
        """Integrate the user's edit/feedback into the draft; return full revised draft.

        The user's text is merged into the document (additions, corrections),
        not used as a replacement for the whole draft.
        """
        if not self._api_key or not user_edit.strip():
            return current_draft
        prompt = build_integrate_edit_prompt(topic, current_draft, user_edit.strip())
        try:
            return self.generate(INTERVIEW_SYSTEM_PROMPT, prompt)
        except Exception:
            logger.warning("LLM integrate_edit failed, appending user text as note")
            return current_draft.rstrip() + "\n\n---\n\n*Your addition:* " + user_edit.strip()

    def _fallback_summary(self, topic: Topic, exchanges: list[dict]) -> str:
        """Generate a simple summary without LLM."""
        lines = [f"Here's what I captured about {topic.name}:"]
        for ex in exchanges:
            lines.append(f"- {ex['answer']}")
        lines.append("\nDid I miss anything?")
        return "\n".join(lines)

    def _fallback_draft(self, topic: Topic, exchanges: list[dict]) -> str:
        """Generate a simple draft without LLM."""
        lines = [f"# {topic.name}\n"]
        for ex in exchanges:
            lines.append(f"- {ex['answer']}")
        return "\n".join(lines)

    def _load_existing_content(self, vault_target: str) -> str | None:
        """Load existing vault file content if it exists."""
        if self._vault_root is None:
            return None
        path = self._vault_root / vault_target
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None


class TopicSelector:
    """Topic selection and ordering helpers for the interview engine."""

    def __init__(self, registry: TopicRegistry) -> None:
        self._registry = registry

    def current_topic_id(self, run: CaptureRun) -> str | None:
        """Find the current topic: first in_progress, then first pending."""
        topics = self.ordered_topic_ids(run)
        for tid in topics:
            if tid in run.topic_progress and run.topic_progress[tid].status == "in_progress":
                return tid
        for tid in topics:
            if tid in run.topic_progress and run.topic_progress[tid].status == "pending":
                return tid
        return None

    def ordered_topic_ids(self, run: CaptureRun) -> list[str]:
        """Return topic IDs in tier order for this run."""
        return self._registry.topic_ids_for_tiers(run.target_tiers)

    def pick_question(self, topic: Topic, exchanges: list[dict]) -> str | None:
        """Pick the next question from the registry or follow-ups."""
        asked_count = len(exchanges)
        all_questions: list[str] = []
        for q in topic.questions:
            all_questions.append(q.prompt)
            all_questions.extend(q.follow_ups)
        if asked_count < len(all_questions):
            return all_questions[asked_count]
        return None

    def should_offer_tier_break(self, run: CaptureRun, completed_topic: Topic) -> bool:
        """Check if the next pending topic is in a different tier."""
        topics = self.ordered_topic_ids(run)
        if completed_topic.id not in topics:
            return False
        completed_idx = topics.index(completed_topic.id)
        if completed_idx >= len(topics) - 1:
            return False
        next_id = None
        for tid in topics[completed_idx + 1:]:
            p = run.topic_progress.get(tid)
            if p and p.status in ("pending", "in_progress"):
                next_id = tid
                break
        if next_id is None:
            return False
        next_topic = self._registry.get_by_id(next_id)
        return next_topic is not None and next_topic.tier != completed_topic.tier

    def get_topic(self, topic_id: str) -> Topic | None:
        """Look up a topic by ID."""
        return self._registry.get_by_id(topic_id)
