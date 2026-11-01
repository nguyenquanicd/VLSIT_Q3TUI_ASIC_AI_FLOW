"""Fuzzy matching shared by Combobox and Command."""

from __future__ import annotations

__all__ = ["fuzzy_score"]


def fuzzy_score(query: str, text: str) -> int | None:
    """How well `query` matches `text`, lower is better, `None` for no match.

    A run of the query inside the text scores its position, so a prefix is best. Otherwise the
    query's letters must appear in order, and the score is 100 plus their positions.
    """
    if not query:
        return 0
    wanted, haystack = query.casefold(), text.casefold()
    if wanted in haystack:
        return haystack.index(wanted)
    position, score = -1, 100
    for letter in wanted:
        position = haystack.find(letter, position + 1)
        if position < 0:
            return None
        score += position
    return score
