"""Alert: a callout with an icon, a title, and a description, following shadcn's Alert."""

from __future__ import annotations

from typing import Literal

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Static

from q3tui.tui.ui.icons import IconName, icon

__all__ = ["Alert", "AlertDescription", "AlertTitle"]

AlertVariant = Literal["default", "destructive", "success", "warning"]
_ICONS: dict[str, IconName] = {
    "default": "about",
    "destructive": "error",
    "success": "selected",
    "warning": "warning",
}


class AlertTitle(Static):
    DEFAULT_CSS = "AlertTitle { height: auto; text-style: bold; color: $foreground; }"

    def __init__(self, text: str, *, id: str | None = None) -> None:
        super().__init__(text, id=id, markup=False)


class AlertDescription(Static):
    DEFAULT_CSS = "AlertDescription { height: auto; color: $text-muted; }"

    def __init__(self, text: str, *, id: str | None = None) -> None:
        super().__init__(text, id=id, markup=False)


class Alert(Horizontal):
    """An icon, then a title and a description. `success` and `warning` are additions.

    One cell of horizontal padding for the text and half-cell top and bottom edges that take
    the color of whatever the alert sits on.
    """

    DEFAULT_CSS = """
    Alert { width: 1fr; height: auto; padding: 0 1; background: $surface;
        border-top: outer transparent; border-bottom: outer transparent; }
    Alert > .alert-icon { width: 3; color: $primary; }
    Alert > .alert-body { width: 1fr; height: auto; }
    Alert.-destructive { background: $error-muted; }
    Alert.-destructive > .alert-icon { color: $text-error; }
    Alert.-success > .alert-icon { color: $text-success; }
    Alert.-warning > .alert-icon { color: $text-warning; }
    """

    def __init__(
        self,
        *parts: Widget,
        variant: AlertVariant = "default",
        icon_name: IconName | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self.parts = parts
        self.variant = variant
        self.icon_name = icon_name or _ICONS[variant]
        if variant != "default":
            self.add_class(f"-{variant}")

    def compose(self) -> ComposeResult:
        yield Static(icon(self.icon_name), classes="alert-icon", markup=False)
        yield Vertical(*self.parts, classes="alert-body")
