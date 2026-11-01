"""The brand of Home: the flow's name centred above the Q3TUI wordmark (the design of ../q3tui)."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

WORDMARK = "\n".join(
    (
        "  ▄▄▄▄▄   ▄▄▄▄▄▄▄  ▄▄▄▄▄▄▄▄▄ ▄▄▄  ▄▄▄ ▄▄▄▄▄ ",
        "▄███████▄ ▀▀▀▀████ ▀▀▀███▀▀▀ ███  ███  ███  ",
        "███   ███   ▄▄██▀     ███    ███  ███  ███  ",
        "███▄█▄███     ███▄    ███    ███▄▄███  ███  ",
        " ▀█████▀  ███████▀    ███    ▀██████▀ ▄███▄ ",
        "      ▀▀                                    ",
    )
)


class WelcomeBrand(Widget):
    """The flow name centred right above the wordmark, which is in the primary colour; a one-line wordmark when
    the screen is narrow."""

    DEFAULT_CSS = """
    WelcomeBrand { height: auto; margin-bottom: 2; }
    WelcomeBrand .flow-name { width: 1fr; height: 1; text-align: center; color: $text-muted; }
    WelcomeBrand .wordmark { width: 1fr; height: 6; text-align: center; color: $primary; text-style: bold; }
    WelcomeBrand .small-wordmark { display: none; width: 1fr; height: 1; text-align: center; color: $primary;
        text-style: bold; }
    WelcomeBrand.narrow .wordmark { display: none; }
    WelcomeBrand.narrow .small-wordmark { display: block; }
    """

    def __init__(self, flow: str) -> None:
        super().__init__()
        self.flow = flow

    def compose(self) -> ComposeResult:
        yield Static(self.flow.upper(), classes="flow-name", markup=False)
        yield Static(WORDMARK, classes="wordmark", markup=False)
        yield Static("Q 3 T U I", classes="small-wordmark", markup=False)
