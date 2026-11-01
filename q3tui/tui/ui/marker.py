"""Marker, following shadcn's Marker: an inline note, a bordered row, or a labeled separator."""

from __future__ import annotations

from typing import Literal

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from q3tui.tui.ui.icons import IconName, icon
from q3tui.tui.ui.spinner import Spinner

__all__ = ["Marker"]


class Marker(Horizontal):
    """`Marker("Switched to a new branch", icon_name="flow")`.

    Variants: `default` (an inline note), `border` (the same with a rule under the row), and
    `separator` (the label centered between two rules; drawn with borders, so no line glyphs).
    `status="running"` puts a spinner where the icon would be, for work in progress.
    """

    DEFAULT_CSS = """
    Marker { width: 1fr; height: auto; color: $text-muted; }
    Marker.-border { border-bottom: solid $foreground 30%; }
    Marker > .marker-icon { width: auto; margin-right: 1; }
    Marker > .marker-text { width: auto; }
    Marker.-separator > .marker-rule { width: 1fr; height: 1; border-top: solid $foreground 30%; }
    Marker.-separator > .marker-text { margin: 0 1; }
    """

    def __init__(
        self,
        text: str,
        *,
        variant: Literal["default", "border", "separator"] = "default",
        icon_name: IconName | None = None,
        status: Literal["running"] | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        if variant not in ("default", "border", "separator"):
            raise ValueError(f"Unknown marker variant: {variant!r}")
        self.text = text
        self.variant = variant
        self.icon_name = icon_name
        self.status = status
        if variant != "default":
            self.add_class(f"-{variant}")

    def compose(self) -> ComposeResult:
        if self.variant == "separator":
            yield Static("", classes="marker-rule")
        if self.status == "running":
            yield Spinner(classes="marker-icon")
        elif self.icon_name:
            yield Static(icon(self.icon_name), classes="marker-icon", markup=False)
        yield Static(self.text, classes="marker-text", markup=False)
        if self.variant == "separator":
            yield Static("", classes="marker-rule")
