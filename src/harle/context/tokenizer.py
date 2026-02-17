"""Token counting utility using tiktoken.

Provides a thin wrapper around tiktoken for estimating token counts.
Used by the Context Assembler to enforce the token budget described in
``docs/trd/architecture/orchestrator.md`` section 4.
"""

from __future__ import annotations

import functools

import tiktoken

# Default encoding for the GPT-4o / GPT-4o-mini model family.
_DEFAULT_ENCODING = "o200k_base"


@functools.lru_cache(maxsize=4)
def _get_encoding(encoding_name: str) -> tiktoken.Encoding:
    """Return a cached tiktoken encoding instance.

    Args:
        encoding_name: Tiktoken encoding name (e.g. ``"o200k_base"``).

    Returns:
        The corresponding :class:`tiktoken.Encoding`.
    """
    return tiktoken.get_encoding(encoding_name)


def count_tokens(
    text: str,
    encoding_name: str = _DEFAULT_ENCODING,
) -> int:
    """Count the number of tokens in *text*.

    Args:
        text: The text to tokenize and count.
        encoding_name: Tiktoken encoding name.  Defaults to
            ``o200k_base`` (GPT-4o family).

    Returns:
        Number of tokens.
    """
    encoding = _get_encoding(encoding_name)
    return len(encoding.encode(text))
