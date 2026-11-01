"""Bubble, following shadcn's Bubble: the framed surface of one conversational message."""

from __future__ import annotations

from typing import Literal

from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Static

from q3tui.tui.ui.icons import IconName, icon

__all__ = ["Bubble", "BubbleContent", "BubbleGroup", "BubbleReactions", "BubbleVariant"]

BubbleVariant = Literal[
    "default", "secondary", "muted", "tinted", "outline", "ghost", "destructive"
]
_VARIANTS = ("default", "secondary", "muted", "tinted", "outline", "ghost", "destructive")


class BubbleContent(Static):
    """The text. Plain text, wrapped; it is as wide as its text, up to 80% of the row."""

    DEFAULT_CSS = """
    BubbleContent { width: auto; max-width: 80%; height: auto; padding: 0 1;
        background: $primary; color: $background;
        border-top: outer transparent; border-bottom: outer transparent; }
    """

    def __init__(self, text: str, *, id: str | None = None) -> None:
        super().__init__(text, id=id, markup=False)


class BubbleReactions(Horizontal):
    """Small reactions under the bubble: icon names, or `(icon name, count)` pairs."""

    DEFAULT_CSS = """
    BubbleReactions { width: auto; height: 1; padding: 0 1; color: $text-muted; }
    BubbleReactions > Static { width: auto; margin-right: 1; }
    """

    def __init__(self, *reactions: IconName | tuple[IconName, int], id: str | None = None) -> None:
        super().__init__(id=id)
        self.reactions = reactions

    def compose(self):
        for reaction in self.reactions:
            name, count = (reaction, 0) if isinstance(reaction, str) else reaction
            yield Static(f"{icon(name)} {count}" if count else icon(name), markup=False)


class Bubble(Vertical):
    """`Bubble(BubbleContent("Hello"), variant="secondary", align="end")`.

    Variants: `default` (a strong primary fill, for the current user), `secondary` (a neutral
    panel), `muted` (quiet text, no fill), `tinted` (a soft primary fill), `outline` (underlined
    text), `ghost` (no frame, the full row: for assistant text), and `destructive`. `align="end"`
    puts it on the right.
    """

    DEFAULT_CSS = """
    Bubble { width: 1fr; height: auto; align-horizontal: left; }
    Bubble.-end { align-horizontal: right; }
    Bubble.-secondary > BubbleContent { background: $panel; color: $foreground; }
    Bubble.-muted > BubbleContent { background: transparent; color: $text-muted; }
    Bubble.-tinted > BubbleContent { background: $primary-muted; color: $foreground; }
    Bubble.-outline > BubbleContent { background: transparent; color: $foreground;
        text-style: underline; }
    Bubble.-ghost > BubbleContent { width: 1fr; max-width: 100%; background: transparent;
        color: $foreground; }
    Bubble.-destructive > BubbleContent { background: $error-muted; color: $foreground; }
    """

    def __init__(
        self,
        *parts: Widget | str,
        variant: BubbleVariant = "default",
        align: Literal["start", "end"] = "start",
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        widgets = [BubbleContent(p) if isinstance(p, str) else p for p in parts]
        super().__init__(*widgets, id=id, classes=classes)
        if variant not in _VARIANTS:
            raise ValueError(f"Unknown bubble variant: {variant!r}")
        self.variant = variant
        self.align = align
        if variant != "default":
            self.add_class(f"-{variant}")
        self.set_class(align == "end", "-end")


class BubbleGroup(Vertical):
    """Consecutive bubbles from one sender, with no blank row between them."""

    DEFAULT_CSS = "BubbleGroup { width: 1fr; height: auto; }"
