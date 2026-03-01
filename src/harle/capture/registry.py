"""Topic Registry — load and query capture topics by tier, scope, or staleness."""

from __future__ import annotations

from datetime import datetime, timedelta

from harle.capture.topics import Tier, Topic, default_topic_tree


class TopicRegistry:
    """Registry of capturable topics. Loads topic definitions and supports
    queries by tier, scope, and staleness.
    """

    def __init__(
        self,
        topic_tree: list[Topic] | None = None,
    ) -> None:
        """Initialize with a topic list. Defaults to the built-in topic tree."""
        self._topics: list[Topic] = topic_tree if topic_tree is not None else default_topic_tree()
        self._by_id: dict[str, Topic] = {t.id: t for t in self._topics}

    def get_all(self) -> list[Topic]:
        """Return all topics in tier order."""
        return list(self._topics)

    def get_by_id(self, topic_id: str) -> Topic | None:
        """Return the topic with the given id, or None."""
        return self._by_id.get(topic_id)

    def get_by_tier(self, tier: Tier) -> list[Topic]:
        """Return all topics in the given tier."""
        return [t for t in self._topics if t.tier == tier]

    def get_by_tiers(self, tiers: list[int]) -> list[Topic]:
        """Return all topics whose tier value is in the given list."""
        tier_values = set(tiers)
        return [t for t in self._topics if t.tier.value in tier_values]

    def get_by_scope(self, scope: str) -> list[Topic]:
        """Return all topics matching the scope.

        Scope is one of: "all", "work", "personal", "goals".
        "work" => context or category work; "personal" => personal/health;
        "goals" => goals; "all" => everything.
        """
        if scope == "all":
            return list(self._topics)
        if scope == "work":
            return [t for t in self._topics if t.context == "work" or t.category == "work"]
        if scope == "personal":
            return [
                t
                for t in self._topics
                if t.context == "personal" or t.category == "personal"
            ]
        if scope == "goals":
            return [t for t in self._topics if t.category == "goals"]
        return []

    def get_stale_topics(
        self,
        completed_at_by_topic_id: dict[str, datetime | None],
        *,
        as_of: datetime | None = None,
    ) -> list[Topic]:
        """Return topics that are stale: either never captured or last captured
        longer than their refresh_interval_days ago.

        completed_at_by_topic_id: map topic_id -> last completed_at (or None if never).
        as_of: reference time; defaults to utcnow().
        """
        now = as_of or datetime.utcnow()
        stale: list[Topic] = []
        for topic in self._topics:
            completed = completed_at_by_topic_id.get(topic.id)
            if completed is None:
                stale.append(topic)
                continue
            cutoff = now - timedelta(days=topic.refresh_interval_days)
            if completed.replace(tzinfo=None) < cutoff:
                stale.append(topic)
        return stale

    def topic_ids_for_tiers(self, tiers: list[int]) -> list[str]:
        """Return topic ids in order for the given tier values."""
        return [t.id for t in self.get_by_tiers(tiers)]
