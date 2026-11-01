"""Empty: a placeholder for a view with nothing in it, following shadcn's Empty."""

from __future__ import annotations

from textual.containers import Vertical
from textual.widgets import Static

from q3tui.tui.ui.icons import IconName, icon

__all__ = [
    "Empty",
    "EmptyContent",
    "EmptyDescription",
    "EmptyHeader",
    "EmptyMedia",
    "EmptyTitle",
]


class EmptyMedia(Static):
    """The icon above the title."""

    DEFAULT_CSS = "EmptyMedia { width: 1fr; height: 1; text-align: center; color: $text-muted; }"

    def __init__(self, icon_name: IconName = "inbox", *, id: str | None = None) -> None:
        super().__init__(icon(icon_name), id=id, markup=False)


class EmptyTitle(Static):
    DEFAULT_CSS = """
    EmptyTitle { width: 1fr; height: auto; text-align: center; text-style: bold;
        color: $foreground; }
    """

    def __init__(self, text: str, *, id: str | None = None) -> None:
        super().__init__(text, id=id, markup=False)


class EmptyDescription(Static):
    DEFAULT_CSS = (
        "EmptyDescription { width: 1fr; height: auto; text-align: center; color: $text-muted; }"
    )

    def __init__(self, text: str, *, id: str | None = None) -> None:
        super().__init__(text, id=id, markup=False)


class EmptyHeader(Vertical):
    DEFAULT_CSS = "EmptyHeader { height: auto; }"


class EmptyContent(Vertical):
    """The actions under the description, centered."""

    DEFAULT_CSS = "EmptyContent { height: auto; align-horizontal: center; }"


class Empty(Vertical):
    """A centered stack: media, title, description, then actions."""

    DEFAULT_CSS = """
    Empty { width: 1fr; height: auto; padding: 0 1; background: $surface;
        border-top: outer transparent; border-bottom: outer transparent; }
    Empty > * { margin-bottom: 1; }
    Empty > *:last-child { margin-bottom: 0; }
    """
