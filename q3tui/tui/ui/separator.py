"""Separator: a thin rule, horizontal or vertical, following shadcn's Separator."""

from __future__ import annotations

from typing import Literal

from textual.widgets import Static

__all__ = ["Separator"]


class Separator(Static):
    """Drawn by Textual's own border, so no line glyphs live in this module."""

    DEFAULT_CSS = """
    Separator { width: 1fr; height: 1; border-top: solid $border-blurred; }
    Separator.-vertical { width: 1; height: 1fr; border-top: none;
        border-left: solid $border-blurred; }
    """

    def __init__(
        self,
        orientation: Literal["horizontal", "vertical"] = "horizontal",
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        if orientation not in ("horizontal", "vertical"):
            raise ValueError("Separator orientation must be horizontal or vertical")
        self.orientation = orientation
        self.set_class(orientation == "vertical", "-vertical")
