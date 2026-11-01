"""Diagrams in a Markdown view: ```mermaid and ```wavedrom blocks drawn as terminal art (spec/tui.md "Main")."""

from __future__ import annotations

from functools import lru_cache

MERMAID = ("mermaid", "mmd")
WAVE = ("wavedrom", "wavejson")
LANGS = MERMAID + WAVE


@lru_cache(maxsize=128)
def draw(code: str, lang: str) -> str | None:
    """The diagram as text, or None when it is not a diagram or cannot be drawn (the caller shows the source)."""
    lang = (lang or "").lower()
    if lang in MERMAID:
        from q3tui.tui.diagrams.mermaid import render

        return render(code)
    if lang in WAVE:
        from q3tui.tui.diagrams.wave import wave_text

        return wave_text(code)
    return None
