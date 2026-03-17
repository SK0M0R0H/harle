"""Query expansion for Phase 2 search.

Tokenizes, normalizes, stems, and enriches user queries with tag
vocabulary matches and optional role-specific terms.
"""

from __future__ import annotations

from whoosh.analysis import StemmingAnalyzer

from harle.search.types import ExpandedQuery, SearchQuery

# Small English stopword set for query expansion (no external dependency).
_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
        "has", "he", "in", "is", "it", "its", "of", "on", "that", "the",
        "to", "was", "were", "will", "with",
    }
)

# Default role-specific terms when add_role_terms is True (config has no map yet).
_DEFAULT_ROLE_TERMS: dict[str, list[str]] = {
    "secretary": ["workflow", "task-management", "status"],
}


def expand(
    query: SearchQuery,
    tag_vocabulary: set[str],
    config: object,
) -> ExpandedQuery:
    """Expand a search query for the Phase 2 pipeline.

    Tokenizes and normalizes the raw query, removes stopwords, stems
    terms for Whoosh, matches against the tag vocabulary for
    pre-filtering, and optionally adds role-specific terms.

    Args:
        query: User search query (and optional context/agent_role).
        tag_vocabulary: Set of known tags from file_index (lowercased).
        config: Search config with add_role_terms, match_tag_vocabulary,
            use_stemming (e.g. :class:`harle.config.SearchConfig`).

    Returns:
        :class:`ExpandedQuery` with whoosh_terms, tag_filters, role_terms,
        context_filter, and raw_query.
    """
    raw = (query.query or "").strip()
    context_filter = query.context

    # Tokenize and normalize (lowercase, drop very short, drop stopwords).
    words = [w.lower() for w in raw.split() if len(w) > 1]
    words = [w for w in words if w not in _STOPWORDS]

    # Stem for Whoosh if config says so.
    use_stemming = getattr(config, "use_stemming", True)
    if use_stemming and words:
        analyzer = StemmingAnalyzer()
        whoosh_terms = []
        for w in words:
            tokens = list(analyzer(w))
            whoosh_terms.extend(t.text for t in tokens if t.text)
        whoosh_terms = list(dict.fromkeys(whoosh_terms))  # preserve order, dedupe
    else:
        whoosh_terms = list(dict.fromkeys(words))

    # Tag filters: terms that appear in the tag vocabulary or stem-match vocab tokens
    # (e.g. "tasks" matches vocab "task-management" via stem "task").
    match_tags = getattr(config, "match_tag_vocabulary", True)
    if match_tags and tag_vocabulary:
        stemmer = StemmingAnalyzer() if use_stemming else None
        stemmed_vocab: set[str] = set()
        for term in tag_vocabulary:
            for part in term.replace("-", " ").split():
                if stemmer:
                    for tok in stemmer(part):
                        if tok.text:
                            stemmed_vocab.add(tok.text)
                else:
                    stemmed_vocab.add(part.lower())
        tag_filters = []
        for w in words:
            if w in tag_vocabulary:
                tag_filters.append(w)
            elif stemmed_vocab:
                stem_w = next((t.text for t in stemmer(w) if t.text), w) if stemmer else w.lower()
                if stem_w in stemmed_vocab:
                    tag_filters.append(w)
        tag_filters = list(dict.fromkeys(tag_filters))
    else:
        tag_filters = []

    # Role-specific terms.
    add_role_terms = getattr(config, "add_role_terms", True)
    role_terms: list[str] = []
    if add_role_terms and query.agent_role:
        role_terms = _DEFAULT_ROLE_TERMS.get(
            query.agent_role.lower(), []
        )
    role_terms = list(dict.fromkeys(role_terms))

    return ExpandedQuery(
        whoosh_terms=whoosh_terms,
        tag_filters=tag_filters,
        role_terms=role_terms,
        context_filter=context_filter,
        raw_query=raw,
    )
