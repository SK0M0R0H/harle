"""Capture Engine — orchestrates the conversational interview flow.

Manages the interview state machine: selects topics, generates adaptive
questions via LLM, collects answers, produces vault document drafts,
and writes approved content through the Profile Writer.

The engine is stateless between calls — all state is persisted in the
CaptureRun (database). Each call to ``process_response()`` advances
the state machine and returns the next action for the CLI/API.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session as DBSession

from harle.capture.interview_helpers import InterviewLLM, TopicSelector
from harle.capture.prompts import (
    INTERVIEW_SYSTEM_PROMPT,
    PRIVACY_NOTE,
    build_capability_note,
    build_question_prompt,
)
from harle.capture.registry import TopicRegistry
from harle.capture.run import CaptureMode, CaptureRun, CaptureRunManager
from harle.capture.topics import Sensitivity, Topic
from harle.capture.writer import CaptureOutput, ProfileWriter
from harle.debug import etrace

logger = logging.getLogger(__name__)

MAX_QUESTIONS_PER_CLUSTER = 5
MIN_QUESTIONS_BEFORE_SUMMARY = 2


@dataclass(frozen=True)
class InterviewResponse:
    """What the engine returns after each interaction step."""

    run_id: str
    action: str  # question, draft, summary, tier_break, complete, paused, error
    message: str
    topic_id: str | None = None
    topic_name: str | None = None
    draft_content: str | None = None
    capability_note: str | None = None
    progress: dict = field(default_factory=dict)


class CaptureEngine:
    """Orchestrates interview sessions using the topic registry and LLM.

    The conversation pattern per topic cluster is:
        1. Ask registry questions + adaptive follow-ups (QUESTIONING)
        2. Summarize and confirm with user (SUMMARIZING)
        3. Generate vault document draft (DRAFTING)
        4. User reviews draft — approve/edit/skip (REVIEWING)
    After each tier, offer a stopping point (TIER_BREAK).
    """

    def __init__(
        self,
        *,
        registry: TopicRegistry,
        run_manager: CaptureRunManager,
        writer: ProfileWriter,
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
    ) -> None:
        resolved_key = api_key or os.getenv("OPENAI_API_KEY")
        self._run_manager = run_manager
        self._writer = writer
        self._llm = InterviewLLM(
            model=model,
            api_key=resolved_key,
            vault_root=writer._vault_root,
        )
        self._topics = TopicSelector(registry)

    # ── Public API ────────────────────────────────────────────────────

    def start_interview(
        self,
        db_session: DBSession,
        *,
        scope: str = "all",
        tiers: list[int] | None = None,
        resume: bool = False,
    ) -> InterviewResponse:
        """Start a new interview or resume a paused one.

        Args:
            db_session: Active SQLAlchemy session.
            scope: Topic scope filter (all/work/personal/goals).
            tiers: Target tier numbers (default [1, 2]).
            resume: If True, look for a paused session to resume.

        Returns:
            InterviewResponse with the first question.
        """
        target_tiers = tiers if tiers is not None else [1, 2]

        with etrace.span("capture_interview_start", level=etrace.STEP, module="capture_engine"):
            if resume:
                run = self._run_manager.find_resumable_run(
                    db_session, mode=CaptureMode.INTERVIEW,
                )
                if run is not None:
                    etrace.detail("Resuming run", module="capture_engine", run_id=run.run_id)
                    self._run_manager.resume_run(db_session, run.run_id)
                    return self._next_action(db_session, run.run_id)
                etrace.detail("No resumable run found, creating new", module="capture_engine")

            run = self._run_manager.create_run(
                db_session,
                mode=CaptureMode.INTERVIEW,
                scope=scope,
                target_tiers=target_tiers,
            )
            self._run_manager.start_run(db_session, run.run_id)
            etrace.step(
                "Interview started",
                module="capture_engine",
                run_id=run.run_id,
                scope=scope,
                tiers=target_tiers,
                topics=len(run.topic_progress),
            )
            return self._next_action(db_session, run.run_id)

    def process_response(
        self,
        db_session: DBSession,
        run_id: str,
        *,
        user_response: str,
        action: str = "answer",
    ) -> InterviewResponse:
        """Process a user response and advance the interview.

        Args:
            db_session: Active SQLAlchemy session.
            run_id: The active capture run ID.
            user_response: The user's text response.
            action: One of: answer, approve, edit, skip, pause, continue, stop.

        Returns:
            InterviewResponse with the next action.
        """
        run = self._run_manager.get_run(db_session, run_id)
        if run is None:
            return InterviewResponse(
                run_id=run_id, action="error",
                message=f"Run {run_id!r} not found.",
            )

        with etrace.span("capture_interview_respond", level=etrace.STEP, module="capture_engine"):
            if action == "pause":
                return self._pause(db_session, run)
            if action == "stop":
                self._run_manager.complete_run(db_session, run_id)
                return self._build_completion(run)
            if action == "continue":
                return self._next_action(db_session, run_id)

            current_topic_id = self._topics.current_topic_id(run)
            if current_topic_id is None:
                return self._build_completion(run)

            if action == "skip":
                return self._skip_topic(db_session, run, current_topic_id)
            if action in ("approve", "edit"):
                return self._handle_approval(
                    db_session, run, current_topic_id, user_response, action,
                )
            return self._handle_answer(db_session, run, current_topic_id, user_response)

    # ── State machine ─────────────────────────────────────────────────

    def _next_action(self, db_session: DBSession, run_id: str) -> InterviewResponse:
        """Determine the next action based on current run state."""
        run = self._run_manager.get_run(db_session, run_id)
        if run is None:
            return InterviewResponse(run_id=run_id, action="error", message="Run not found.")

        current_topic_id = self._topics.current_topic_id(run)
        if current_topic_id is None:
            return self._build_completion(run)

        topic = self._topics.get_topic(current_topic_id)
        if topic is None:
            return self._build_completion(run)

        progress = run.topic_progress[current_topic_id]
        answers = progress.answers or {}
        exchanges = answers.get("exchanges", [])
        phase = answers.get("phase", "questioning")

        if phase == "reviewing":
            return InterviewResponse(
                run_id=run.run_id, action="draft",
                message="Here's a draft based on our conversation. Approve, edit, or skip?",
                topic_id=current_topic_id, topic_name=topic.name,
                draft_content=progress.generated_content,
                progress=self._progress_stats(run),
            )

        return self._ask_next_question(db_session, run, topic, exchanges)

    def _ask_next_question(
        self, db_session: DBSession, run: CaptureRun, topic: Topic, exchanges: list[dict],
    ) -> InterviewResponse:
        """Generate and return the next question for the current topic."""
        question_text = self._topics.pick_question(topic, exchanges)

        is_follow_up = len(exchanges) > 0
        if question_text and self._llm.has_llm:
            prompt = build_question_prompt(topic, question_text, exchanges, is_follow_up=is_follow_up)
            try:
                question_text = self._llm.generate(INTERVIEW_SYSTEM_PROMPT, prompt)
            except Exception:
                logger.warning("LLM call failed, using registry question directly")

        if not question_text:
            return self._transition_to_draft(db_session, run, topic)

        privacy_prefix = ""
        if topic.sensitivity == Sensitivity.HIGH and len(exchanges) == 0:
            privacy_prefix = f"({PRIVACY_NOTE})\n\n"

        updated_answers = dict(run.topic_progress[topic.id].answers or {})
        updated_answers["phase"] = "questioning"
        updated_answers["current_question"] = question_text
        self._run_manager.update_topic_progress(
            db_session, run.run_id, topic.id,
            status="in_progress", answers=updated_answers,
        )

        return InterviewResponse(
            run_id=run.run_id, action="question",
            message=f"{privacy_prefix}{question_text}",
            topic_id=topic.id, topic_name=topic.name,
            progress=self._progress_stats(run),
        )

    def _handle_answer(
        self, db_session: DBSession, run: CaptureRun, topic_id: str, answer: str,
    ) -> InterviewResponse:
        """Store an answer and decide whether to continue or generate a draft."""
        topic = self._topics.get_topic(topic_id)
        if topic is None:
            return self._next_action(db_session, run.run_id)

        progress = run.topic_progress[topic_id]
        answers = dict(progress.answers or {})
        exchanges = list(answers.get("exchanges", []))

        current_q = answers.get("current_question", "")
        exchanges.append({"question": current_q, "answer": answer})
        answers["exchanges"] = exchanges

        enough = len(exchanges) >= min(
            MAX_QUESTIONS_PER_CLUSTER,
            len(topic.questions) + sum(len(q.follow_ups) for q in topic.questions),
        )
        all_asked = len(exchanges) >= len(topic.questions)

        if enough or (all_asked and len(exchanges) >= MIN_QUESTIONS_BEFORE_SUMMARY):
            answers["phase"] = "reviewing"
            self._run_manager.update_topic_progress(
                db_session, run.run_id, topic_id, status="in_progress", answers=answers,
            )
            return self._transition_to_draft(db_session, run, topic)

        answers["phase"] = "questioning"
        self._run_manager.update_topic_progress(
            db_session, run.run_id, topic_id, status="in_progress", answers=answers,
        )
        run = self._run_manager.get_run(db_session, run.run_id)
        return self._ask_next_question(db_session, run, topic, exchanges)

    def _transition_to_draft(
        self, db_session: DBSession, run: CaptureRun, topic: Topic,
    ) -> InterviewResponse:
        """Generate summary + draft and present for review."""
        progress = run.topic_progress[topic.id]
        exchanges = (progress.answers or {}).get("exchanges", [])

        summary = self._llm.generate_summary(topic, exchanges)
        draft = self._llm.generate_draft(topic, exchanges)

        answers = dict(progress.answers or {})
        answers["phase"] = "reviewing"
        self._run_manager.update_topic_progress(
            db_session, run.run_id, topic.id,
            status="in_progress", answers=answers, generated_content=draft,
        )

        return InterviewResponse(
            run_id=run.run_id, action="draft",
            message=f"{summary}\n\n---\n\nHere's a draft document I generated:",
            topic_id=topic.id, topic_name=topic.name,
            draft_content=draft,
            progress=self._progress_stats(run),
        )

    def _handle_approval(
        self, db_session: DBSession, run: CaptureRun,
        topic_id: str, user_response: str, action: str,
    ) -> InterviewResponse:
        """Handle draft approval or edit. Edit integrates feedback into draft and re-presents."""
        topic = self._topics.get_topic(topic_id)
        if topic is None:
            return self._next_action(db_session, run.run_id)

        progress = run.topic_progress[topic_id]
        current_draft = progress.generated_content or ""

        if action == "edit" and user_response.strip():
            # Integrate user's feedback into the draft; re-present for approval
            integrated = self._llm.integrate_edit(topic, current_draft, user_response)
            self._run_manager.update_topic_progress(
                db_session, run.run_id, topic_id,
                status="in_progress", generated_content=integrated,
            )
            return InterviewResponse(
                run_id=run.run_id, action="draft",
                message="I've integrated your feedback. Here's the updated draft — approve (y), add more edits, or skip (/skip):",
                topic_id=topic_id, topic_name=topic.name,
                draft_content=integrated,
                progress=self._progress_stats(run),
            )

        # Approve: save current draft to vault
        content = current_draft

        vault_path = asyncio.run(
            self._writer.write(CaptureOutput(
                topic_id=topic_id,
                title=topic.name,
                content=content,
                tags=[topic.category, topic.context],
                context=topic.context,
                vault_path=topic.vault_target,
                is_update=Path(self._writer._vault_root / topic.vault_target).exists(),
            ))
        )

        self._run_manager.update_topic_progress(
            db_session, run.run_id, topic_id,
            status="completed", vault_path=vault_path,
            generated_content=content, completed_at=datetime.utcnow(),
        )

        capability = build_capability_note(topic)
        etrace.detail("Topic completed", module="capture_engine", topic_id=topic_id, vault_path=vault_path)

        if self._topics.should_offer_tier_break(run, topic):
            return InterviewResponse(
                run_id=run.run_id, action="tier_break",
                message=(
                    f"Saved to {vault_path}. {capability}\n\n"
                    f"We've covered this tier. Want to continue with "
                    f"the next set of topics, or stop here for today?"
                ),
                topic_id=topic_id, topic_name=topic.name,
                capability_note=capability,
                progress=self._progress_stats(run),
            )

        return self._advance_after_topic(db_session, run, topic_id, vault_path, capability)

    def _skip_topic(
        self, db_session: DBSession, run: CaptureRun, topic_id: str,
    ) -> InterviewResponse:
        """Skip the current topic and move to the next."""
        self._run_manager.update_topic_progress(
            db_session, run.run_id, topic_id, status="skipped",
        )
        etrace.detail("Topic skipped", module="capture_engine", topic_id=topic_id)

        run = self._run_manager.get_run(db_session, run.run_id)
        if self._topics.current_topic_id(run) is None:
            return self._build_completion(run)
        return self._next_action(db_session, run.run_id)

    def _pause(self, db_session: DBSession, run: CaptureRun) -> InterviewResponse:
        """Pause the current interview run."""
        self._run_manager.pause_run(db_session, run.run_id)
        etrace.step("Interview paused", module="capture_engine", run_id=run.run_id)
        return InterviewResponse(
            run_id=run.run_id, action="paused",
            message=(
                "Session paused. Your progress is saved.\n"
                "Resume anytime with: harle capture interview --resume"
            ),
            progress=self._progress_stats(run),
        )

    def _advance_after_topic(
        self, db_session: DBSession, run: CaptureRun,
        topic_id: str, vault_path: str, capability: str,
    ) -> InterviewResponse:
        """Advance to the next topic after completing one."""
        run = self._run_manager.get_run(db_session, run.run_id)
        next_id = self._topics.current_topic_id(run)
        if next_id is None:
            return self._build_completion(run)

        next_topic = self._topics.get_topic(next_id)
        self._run_manager.update_topic_progress(
            db_session, run.run_id, next_id,
            status="in_progress", answers={"phase": "questioning", "exchanges": []},
        )
        run = self._run_manager.get_run(db_session, run.run_id)

        next_resp = self._ask_next_question(db_session, run, next_topic, [])
        return InterviewResponse(
            run_id=run.run_id, action=next_resp.action,
            message=f"Saved to {vault_path}. {capability}\n\n{next_resp.message}",
            topic_id=next_resp.topic_id, topic_name=next_resp.topic_name,
            progress=self._progress_stats(run),
        )

    # ── Response builders ─────────────────────────────────────────────

    def _build_completion(self, run: CaptureRun) -> InterviewResponse:
        """Build the final completion response."""
        completed = sum(1 for p in run.topic_progress.values() if p.status == "completed")
        skipped = sum(1 for p in run.topic_progress.values() if p.status == "skipped")

        parts = [f"Interview complete! Captured {completed} topic(s) across your vault."]
        if skipped:
            parts.append(f"{skipped} topic(s) were skipped.")
        parts.append(
            "\nTry asking me a question to see how I use what you shared — "
            "for example: \"What should I focus on this week?\""
        )

        return InterviewResponse(
            run_id=run.run_id, action="complete",
            message="\n".join(parts),
            progress=self._progress_stats(run),
        )

    def _progress_stats(self, run: CaptureRun) -> dict:
        """Build progress statistics for the response."""
        completed = sum(1 for p in run.topic_progress.values() if p.status == "completed")
        skipped = sum(1 for p in run.topic_progress.values() if p.status == "skipped")
        total = len(run.topic_progress)
        current = self._topics.current_topic_id(run)
        current_tier = None
        if current:
            topic = self._topics.get_topic(current)
            if topic:
                current_tier = topic.tier.value
        return {
            "completed": completed,
            "skipped": skipped,
            "total": total,
            "current_tier": current_tier,
        }
