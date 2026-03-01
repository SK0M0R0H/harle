"""Topic definitions for the Vault Capture Module.

Defines Tier, Sensitivity, TopicQuestion, Topic, and the default
topic tree. The registry loads these so capture modes can query
by tier, scope, or staleness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Tier(Enum):
    """Capture urgency / importance level."""

    ESSENTIAL = 1
    USEFUL = 2
    PERSONAL = 3
    ASPIRATIONAL = 4


class Sensitivity(Enum):
    """Privacy sensitivity of the topic."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class TopicQuestion:
    """A single question within a topic."""

    id: str
    prompt: str
    follow_ups: list[str] = field(default_factory=list)
    example_answer: str = ""
    input_type: str = "open"


@dataclass
class Topic:
    """A capturable topic with questions and metadata."""

    id: str
    name: str
    description: str
    tier: Tier
    category: str
    context: str
    sensitivity: Sensitivity
    questions: list[TopicQuestion]
    vault_target: str
    depends_on: list[str] = field(default_factory=list)
    refresh_interval_days: int = 90


def default_topic_tree() -> list[Topic]:
    """Return the first-version topic tree (Work, Personal, Goals)."""
    return [
        # Tier 1 — Essential (Work)
        Topic(
            id="role_and_team",
            name="Role and team",
            description="Job title, team, and reporting structure.",
            tier=Tier.ESSENTIAL,
            category="work",
            context="work",
            sensitivity=Sensitivity.LOW,
            questions=[
                TopicQuestion(
                    id="role",
                    prompt="What is your job title and role?",
                    follow_ups=["Do you manage people or report to someone specific?"],
                ),
                TopicQuestion(
                    id="team",
                    prompt="What team or department are you part of?",
                ),
            ],
            vault_target="knowledge/work/profile.md",
        ),
        Topic(
            id="current_projects",
            name="Current projects",
            description="What you are working on right now.",
            tier=Tier.ESSENTIAL,
            category="work",
            context="work",
            sensitivity=Sensitivity.LOW,
            questions=[
                TopicQuestion(
                    id="projects",
                    prompt="What are you working on right now? (1-3 projects)",
                    follow_ups=["For each project, what tools do you use to track it?"],
                ),
            ],
            vault_target="knowledge/work/projects.md",
        ),
        Topic(
            id="daily_tools",
            name="Daily tools",
            description="Tools used every day for work.",
            tier=Tier.ESSENTIAL,
            category="work",
            context="work",
            sensitivity=Sensitivity.LOW,
            questions=[
                TopicQuestion(
                    id="tools",
                    prompt="What tools do you use every day for work?",
                    follow_ups=[
                        "Do any of these have specific board/workspace names I should know?"
                    ],
                ),
            ],
            vault_target="knowledge/work/profile.md",
        ),
        Topic(
            id="communication_style",
            name="Communication style",
            description="How you prefer information delivered.",
            tier=Tier.ESSENTIAL,
            category="work",
            context="work",
            sensitivity=Sensitivity.LOW,
            questions=[
                TopicQuestion(
                    id="format",
                    prompt="How do you prefer information delivered? (bullets, paragraphs, tables)",
                    follow_ups=["Should status updates be brief or detailed?"],
                ),
            ],
            vault_target="knowledge/work/profile.md",
        ),
        # Tier 2 — Useful (Work)
        Topic(
            id="recurring_decisions",
            name="Recurring decisions",
            description="Decisions you make regularly at work.",
            tier=Tier.USEFUL,
            category="work",
            context="work",
            sensitivity=Sensitivity.LOW,
            questions=[
                TopicQuestion(
                    id="decisions",
                    prompt="What decisions do you make regularly at work?",
                    follow_ups=["Are there criteria you use each time?"],
                ),
            ],
            vault_target="knowledge/work/profile.md",
        ),
        Topic(
            id="pain_points",
            name="Pain points",
            description="What wastes your time at work.",
            tier=Tier.USEFUL,
            category="work",
            context="work",
            sensitivity=Sensitivity.LOW,
            questions=[
                TopicQuestion(
                    id="waste",
                    prompt="What wastes your time most at work?",
                    follow_ups=["Is there a task you wish someone else handled?"],
                ),
            ],
            vault_target="knowledge/work/profile.md",
        ),
        Topic(
            id="reporting_preferences",
            name="Reporting preferences",
            description="What reports must include.",
            tier=Tier.USEFUL,
            category="work",
            context="work",
            sensitivity=Sensitivity.LOW,
            questions=[
                TopicQuestion(
                    id="reports",
                    prompt="When you receive reports, what must be included?",
                    follow_ups=["Are there formats or lengths you prefer?"],
                ),
            ],
            vault_target="knowledge/work/profile.md",
        ),
        Topic(
            id="work_hours_timezone",
            name="Work hours and timezone",
            description="Time zone and schedule.",
            tier=Tier.USEFUL,
            category="work",
            context="work",
            sensitivity=Sensitivity.LOW,
            questions=[
                TopicQuestion(id="tz", prompt="What time zone are you in?"),
                TopicQuestion(
                    id="hours",
                    prompt="Do you have set work hours or a flexible schedule?",
                ),
            ],
            vault_target="knowledge/work/profile.md",
        ),
        # Tier 3 — Personal
        Topic(
            id="dietary_preferences",
            name="Dietary preferences",
            description="Dietary restrictions and preferences.",
            tier=Tier.PERSONAL,
            category="personal",
            context="personal",
            sensitivity=Sensitivity.MEDIUM,
            questions=[
                TopicQuestion(
                    id="diet",
                    prompt="Do you have dietary preferences or restrictions?",
                    follow_ups=["Favorite cuisines or restaurants?"],
                ),
            ],
            vault_target="knowledge/personal/preferences.md",
        ),
        Topic(
            id="travel_preferences",
            name="Travel preferences",
            description="Travel habits and preferences.",
            tier=Tier.PERSONAL,
            category="personal",
            context="personal",
            sensitivity=Sensitivity.MEDIUM,
            questions=[
                TopicQuestion(id="travel", prompt="Do you travel often?"),
                TopicQuestion(
                    id="travel_detail",
                    prompt="Window or aisle? Hotel preferences?",
                    follow_ups=["Budget range for travel?"],
                ),
            ],
            vault_target="knowledge/personal/preferences.md",
        ),
        Topic(
            id="health_notes",
            name="Health notes",
            description="Health conditions (optional, private).",
            tier=Tier.PERSONAL,
            category="personal",
            context="personal",
            sensitivity=Sensitivity.HIGH,
            questions=[
                TopicQuestion(
                    id="health",
                    prompt="Any health conditions I should know about? (completely optional)",
                    example_answer="This stays in your vault on your machine.",
                ),
            ],
            vault_target="knowledge/personal/health/notes.md",
        ),
        Topic(
            id="communication_preferences",
            name="Communication preferences",
            description="Tone and habits you want Harle to match.",
            tier=Tier.PERSONAL,
            category="personal",
            context="personal",
            sensitivity=Sensitivity.LOW,
            questions=[
                TopicQuestion(
                    id="tone",
                    prompt="Do you prefer formal or casual tone from me?",
                    follow_ups=["Any communication habits I should match?"],
                ),
            ],
            vault_target="knowledge/personal/preferences.md",
        ),
        # Tier 4 — Aspirational (Goals)
        Topic(
            id="short_term_goals",
            name="Short-term goals",
            description="Goals for the next 1-3 months.",
            tier=Tier.ASPIRATIONAL,
            category="goals",
            context="personal",
            sensitivity=Sensitivity.LOW,
            questions=[
                TopicQuestion(
                    id="short_goals",
                    prompt="What are your goals for the next 1-3 months?",
                    follow_ups=["What would 'done' look like for each?"],
                ),
            ],
            vault_target="knowledge/personal/goals.md",
        ),
        Topic(
            id="long_term_goals",
            name="Long-term goals",
            description="Goals for the year or beyond.",
            tier=Tier.ASPIRATIONAL,
            category="goals",
            context="personal",
            sensitivity=Sensitivity.LOW,
            questions=[
                TopicQuestion(
                    id="long_goals",
                    prompt="What are your goals for this year or beyond?",
                    follow_ups=["Are there milestones along the way?"],
                ),
            ],
            vault_target="knowledge/personal/goals.md",
        ),
        Topic(
            id="learning_interests",
            name="Learning interests",
            description="Topics you want to learn.",
            tier=Tier.ASPIRATIONAL,
            category="goals",
            context="personal",
            sensitivity=Sensitivity.LOW,
            questions=[
                TopicQuestion(
                    id="learning",
                    prompt="What topics do you want to learn about?",
                    follow_ups=["Books, courses, or hands-on projects?"],
                ),
            ],
            vault_target="knowledge/personal/goals.md",
        ),
        Topic(
            id="areas_of_expertise",
            name="Areas of expertise",
            description="Topics you consider yourself expert in.",
            tier=Tier.ASPIRATIONAL,
            category="goals",
            context="personal",
            sensitivity=Sensitivity.LOW,
            questions=[
                TopicQuestion(
                    id="expertise",
                    prompt="What topics do you consider yourself an expert in?",
                    follow_ups=[
                        "Would you like me to use technical vocabulary in those areas?"
                    ],
                ),
            ],
            vault_target="knowledge/personal/goals.md",
        ),
    ]
