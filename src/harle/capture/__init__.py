"""Vault Capture Module — topic registry, run manager, profile writer.

Phase 1 provides the core infrastructure: topics, capture run lifecycle
persistence, and writing/merging capture results to the vault. "Run"
refers to a single capture workflow (quick profile, interview, refresh),
distinct from chat sessions between the user and Harle.
"""

from harle.capture.registry import TopicRegistry
from harle.capture.run import (
    CaptureMode,
    CaptureRun,
    CaptureRunManager,
    CaptureRunState,
    TopicProgress,
)
from harle.capture.topics import (
    Sensitivity,
    Tier,
    Topic,
    TopicQuestion,
    default_topic_tree,
)
from harle.capture.writer import CaptureOutput, ProfileWriter

__all__ = [
    "CaptureMode",
    "CaptureOutput",
    "CaptureRun",
    "CaptureRunManager",
    "CaptureRunState",
    "ProfileWriter",
    "Sensitivity",
    "Tier",
    "Topic",
    "TopicProgress",
    "TopicQuestion",
    "TopicRegistry",
    "default_topic_tree",
]
