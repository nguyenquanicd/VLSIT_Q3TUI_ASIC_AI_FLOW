"""The theme of the TUI: one, `vlsit-dark` (spec/tui.md "Look")."""

from textual.theme import Theme

VLSIT_DARK = Theme(
    name="vlsit-dark",
    primary="#a78bfa",
    secondary="#9a9590",
    accent="#a78bfa",
    foreground="#e4e1dc",
    background="#141414",
    surface="#1c1c1c",
    panel="#252525",
    success="#a3be8c",
    warning="#d6a77a",
    error="#e08282",
    dark=True,
    variables={"input-cursor-background": "#a78bfa", "border": "#a78bfa"},
)

THEMES = {VLSIT_DARK.name: VLSIT_DARK}
