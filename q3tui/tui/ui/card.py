"""Card: a titled surface with a header, content, and footer, following shadcn's Card."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Static

__all__ = [
    "Card",
    "CardAction",
    "CardContent",
    "CardDescription",
    "CardFooter",
    "CardHeader",
    "CardTitle",
]


class CardTitle(Static):
    DEFAULT_CSS = "CardTitle { height: auto; text-style: bold; color: $foreground; }"

    def __init__(self, text: str, *, id: str | None = None) -> None:
        super().__init__(text, id=id, markup=False)


class CardDescription(Static):
    DEFAULT_CSS = "CardDescription { height: auto; color: $text-muted; }"

    def __init__(self, text: str, *, id: str | None = None) -> None:
        super().__init__(text, id=id, markup=False)


class CardAction(Horizontal):
    """Sits at the right end of the header, level with the title."""

    DEFAULT_CSS = "CardAction { width: auto; height: auto; }"


class CardHeader(Horizontal):
    """The title and description on the left, and a `CardAction`, if any, on the right."""

    DEFAULT_CSS = """
    CardHeader { height: auto; }
    CardHeader > .card-heading { width: 1fr; height: auto; }
    """

    def __init__(self, *parts: Widget, id: str | None = None, classes: str | None = None) -> None:
        super().__init__(id=id, classes=classes)
        self.parts = parts

    def compose(self) -> ComposeResult:
        yield Vertical(
            *(part for part in self.parts if not isinstance(part, CardAction)),
            classes="card-heading",
        )
        yield from (part for part in self.parts if isinstance(part, CardAction))


class CardContent(Vertical):
    DEFAULT_CSS = "CardContent { height: auto; }"


class CardFooter(Horizontal):
    DEFAULT_CSS = "CardFooter { height: auto; align-vertical: middle; }"


class Card(Vertical):
    """One cell of horizontal padding for the text, half-cell edges that take the color of what
    the card sits on, and a blank row between header, content, and footer."""

    DEFAULT_CSS = """
    Card { width: 1fr; height: auto; background: $surface; color: $foreground;
        border-top: outer transparent; border-bottom: outer transparent; }
    Card > * { padding: 0 1; margin-bottom: 1; }
    Card > *:last-child { margin-bottom: 0; }
    """
