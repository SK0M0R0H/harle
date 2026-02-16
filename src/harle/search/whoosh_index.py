"""Whoosh full-text search index (not yet implemented).

This module will build and query a Whoosh inverted index over the
dataset, providing BM25 keyword scoring with field boosts (title 2x).
It will replace the simple keyword search in :mod:`harle.search.engine`
once the dataset grows beyond ~100 files.
"""

from __future__ import annotations
