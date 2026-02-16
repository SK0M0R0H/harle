"""Auto-generate file summaries via LLM (not yet implemented).

This module will call GPT-4o-mini to generate one-sentence summaries,
key entities, and ``questions_answered`` metadata for each indexed
file.  Cost: ~$0.001 per file, only run for new or changed files.
"""

from __future__ import annotations
