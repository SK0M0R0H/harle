"""Dataset sync — Git pull and change detection (not yet implemented).

This module will handle pulling the latest vault state from the Git
remote and triggering re-indexing when files change.  For now,
syncing is manual (the user pushes/pulls their vault repo).
"""

from __future__ import annotations
