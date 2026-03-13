"""Interview prompt templates for the Vault Capture Module.

Provides system prompts and user-message builders for the LLM-driven
interview flow. The Capture Engine uses these to generate adaptive
follow-up questions, confirmation summaries, and vault document drafts.

Techniques embedded in the prompts (from TRD and research):
- GATE: open-ended questions over multiple-choice
- Progressive depth: broad → narrow based on answers
- Reflection and confirmation after each topic cluster
- Latent preference discovery via follow-ups
"""

from __future__ import annotations

from harle.capture.topics import Sensitivity, Topic


INTERVIEW_SYSTEM_PROMPT = """\
You are Harle, a friendly and professional personal AI assistant \
conducting an onboarding interview to learn about the user. Your goal \
is to capture personal knowledge — preferences, work context, goals, \
and interests — so that Harle can be more helpful in the future.

Guidelines:
- Ask open-ended questions (GATE methodology). Prefer "Tell me about…" \
over yes/no questions.
- Start broad, then narrow based on responses (progressive depth).
- Be warm, conversational, and efficient. Do not lecture or over-explain.
- Keep questions concise — one question at a time.
- When the user gives a short answer, gently ask a follow-up to surface \
hidden details.
- Never judge or evaluate the user's answers.
- If the user seems uncomfortable, move on gracefully.
"""

PRIVACY_NOTE = (
    "This is completely optional and stays in your vault on your "
    "machine — I never send it anywhere."
)


def build_question_prompt(
    topic: Topic,
    question_text: str,
    previous_exchanges: list[dict[str, str]],
    *,
    is_follow_up: bool = False,
) -> str:
    """Build a user-message prompt for generating the next interview question.

    Args:
        topic: The current topic being discussed.
        question_text: The registry question or follow-up seed.
        previous_exchanges: List of {"question": ..., "answer": ...} dicts.
        is_follow_up: Whether this is an adaptive follow-up.

    Returns:
        The prompt string for the LLM.
    """
    parts: list[str] = []

    parts.append(f"Topic: {topic.name} — {topic.description}")

    if previous_exchanges:
        parts.append("\nConversation so far:")
        for ex in previous_exchanges:
            parts.append(f"  Q: {ex['question']}")
            parts.append(f"  A: {ex['answer']}")

    if is_follow_up:
        parts.append(
            f"\nBased on the user's last answer, ask a natural follow-up "
            f"that digs deeper. Seed idea: \"{question_text}\"\n"
            f"Generate ONE short, conversational follow-up question. "
            f"Output ONLY the question text."
        )
    else:
        parts.append(
            f"\nAsk the following question in a warm, conversational way: "
            f"\"{question_text}\"\n"
            f"Rephrase it naturally if needed. "
            f"Output ONLY the question text."
        )

    if topic.sensitivity == Sensitivity.HIGH:
        parts.append(f"\nInclude this privacy note: {PRIVACY_NOTE}")

    return "\n".join(parts)


def build_summary_prompt(
    topic: Topic,
    exchanges: list[dict[str, str]],
) -> str:
    """Build a prompt for summarizing answers and asking for confirmation.

    Args:
        topic: The topic cluster being summarized.
        exchanges: All Q&A exchanges for this topic.

    Returns:
        Prompt string for generating the summary.
    """
    parts = [
        f"Topic: {topic.name}",
        "\nHere is everything the user shared:",
    ]
    for ex in exchanges:
        parts.append(f"  Q: {ex['question']}")
        parts.append(f"  A: {ex['answer']}")

    parts.append(
        "\nWrite a brief, friendly summary of what you captured. "
        "End with: \"Did I miss anything?\"\n"
        "Keep it under 150 words. Output ONLY the summary text."
    )
    return "\n".join(parts)


def build_draft_prompt(
    topic: Topic,
    exchanges: list[dict[str, str]],
    existing_content: str | None = None,
) -> str:
    """Build a prompt for generating a vault Markdown document draft.

    The generated document should be well-structured Markdown with
    headings, bullet points, and natural prose — not a Q&A transcript.

    Args:
        topic: The topic being documented.
        exchanges: All Q&A exchanges for this topic.
        existing_content: Current vault file content if updating.

    Returns:
        Prompt string for generating the vault document.
    """
    parts = [
        f"Generate a vault knowledge document about: {topic.name}",
        f"Category: {topic.category} | Context: {topic.context}",
        "\nUser's answers from the interview:",
    ]
    for ex in exchanges:
        parts.append(f"  Q: {ex['question']}")
        parts.append(f"  A: {ex['answer']}")

    if existing_content:
        parts.append(
            f"\nExisting document content (merge, don't overwrite):\n"
            f"{existing_content}"
        )

    parts.append(
        "\nGenerate a clean Markdown document body (NO frontmatter — "
        "that is added separately). Use proper headings (##), bullet "
        "points, and natural language. Do NOT include a Q&A transcript. "
        "Transform the answers into structured, readable content. "
        "Keep it concise but complete."
    )
    return "\n".join(parts)


def build_integrate_edit_prompt(
    topic: Topic,
    current_draft: str,
    user_edit: str,
) -> str:
    """Build a prompt for integrating user edits into the draft.

    The user's text is feedback or additions to merge into the document,
    not a replacement. The LLM should produce the full revised document.

    Args:
        topic: The topic being documented.
        current_draft: The current draft Markdown.
        user_edit: What the user typed (correction, addition, or refinement).

    Returns:
        Prompt string for the LLM.
    """
    return f"""Topic: {topic.name}

Current draft document:

---
{current_draft}
---

The user provided this feedback or addition (integrate it into the document, do not replace the draft):

"{user_edit}"

Revise the draft to incorporate the user's feedback. Output the complete revised Markdown document body only (NO frontmatter). Keep the same structure and style; add, correct, or rephrase only where needed. Do not remove existing content unless the user asked to remove it."""


def build_capability_note(topic: Topic) -> str:
    """Generate a short note explaining what this captured knowledge enables.

    Implements DP-4: Make effort feel proportional.

    Args:
        topic: The completed topic.

    Returns:
        A one-sentence capability description.
    """
    capability_map = {
        "role_and_team": "I can now tailor responses to your role and team context.",
        "current_projects": "I can reference your active projects when you ask about priorities.",
        "daily_tools": "I'll use the right tool names without asking you each time.",
        "communication_style": "I'll format responses the way you prefer.",
        "recurring_decisions": "I can help prepare for decisions you make regularly.",
        "pain_points": "I'll look for ways to save you time on the things that slow you down.",
        "reporting_preferences": "Reports and summaries will match your preferred format.",
        "work_hours_timezone": "I'll respect your schedule and time zone in recommendations.",
        "dietary_preferences": "I can factor in your dietary needs for meal and restaurant suggestions.",
        "travel_preferences": "I can plan trips matching your style without asking setup questions.",
        "health_notes": "I'll keep health context in mind when relevant — kept private in your vault.",
        "communication_preferences": "I'll match your preferred tone and communication style.",
        "short_term_goals": "I can help track progress toward your near-term goals.",
        "long_term_goals": "I'll connect suggestions to your bigger-picture aspirations.",
        "learning_interests": "I can recommend resources aligned with what you want to learn.",
        "areas_of_expertise": "I'll use appropriate technical depth in your areas of expertise.",
    }
    return capability_map.get(
        topic.id,
        "This helps me give you more personalized responses.",
    )
