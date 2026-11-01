"""Item, following shadcn's Item: a row with media, a title and description, and actions."""

from __future__ import annotations

from typing import Literal

from textual import events
from textual.actions import SkipAction
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from q3tui.tui.ui.icons import IconName, icon

__all__ = [
    "Item",
    "ItemActions",
    "ItemContent",
    "ItemDescription",
    "ItemGroup",
    "ItemMedia",
    "ItemSeparator",
    "ItemTitle",
]


class ItemMedia(Static):
    """The leading icon (or a small widget such as an Avatar, via `ItemMedia` children)."""

    DEFAULT_CSS = "ItemMedia { width: auto; height: 1; margin-right: 1; color: $text-muted; }"

    def __init__(self, icon_name: IconName, *, id: str | None = None) -> None:
        super().__init__(icon(icon_name), id=id, markup=False)


class ItemTitle(Static):
    DEFAULT_CSS = "ItemTitle { height: auto; text-style: bold; color: $foreground; }"

    def __init__(self, text: str, *, id: str | None = None) -> None:
        super().__init__(text, id=id, markup=False)


class ItemDescription(Static):
    DEFAULT_CSS = "ItemDescription { height: auto; color: $text-muted; }"

    def __init__(self, text: str, *, id: str | None = None) -> None:
        super().__init__(text, id=id, markup=False)


class ItemContent(Vertical):
    """The title and description."""

    DEFAULT_CSS = "ItemContent { width: 1fr; height: auto; }"


class ItemActions(Horizontal):
    """Buttons or badges at the right end of the row."""

    DEFAULT_CSS = "ItemActions { width: auto; height: auto; margin-left: 1; }"


class ItemSeparator(Static):
    DEFAULT_CSS = "ItemSeparator { height: 1; border-top: solid $border-blurred; }"


class Item(Horizontal):
    """`Item(ItemMedia("file"), ItemContent(ItemTitle("a.pdf"), ItemDescription("1 MB")))`.

    `variant`: `default`, `muted` (a `$surface` fill), or `outline` (underlined title). With
    `value=...` the row is selectable: it is a Tab stop, Enter, Space, or a click posts
    `Item.Selected`, and inside an `ItemGroup` Up and Down move between selectable rows.
    """

    DEFAULT_CSS = """
    Item { width: 1fr; height: auto; padding: 0 1; }
    Item.-muted { background: $surface;
        border-top: outer transparent; border-bottom: outer transparent; }
    Item.-outline ItemTitle { text-style: bold underline; }
    Item.-selectable:hover, Item.-selectable:focus { background: $panel; }
    """
    BINDINGS = [Binding("enter,space", "choose", show=False)]

    class Selected(Message):
        def __init__(self, item: Item, value: str) -> None:
            super().__init__()
            self.item = item
            self.value = value

        @property
        def control(self) -> Item:
            return self.item

    def __init__(
        self,
        *parts: Widget,
        variant: Literal["default", "muted", "outline"] = "default",
        value: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(*parts, id=id, classes=classes)
        if variant not in ("default", "muted", "outline"):
            raise ValueError(f"Unknown item variant: {variant!r}")
        self.value = value
        if variant != "default":
            self.add_class(f"-{variant}")
        if value is not None:
            self.can_focus = True
            self.add_class("-selectable")

    def action_choose(self) -> None:
        if self.value is None:
            raise SkipAction()
        self.post_message(self.Selected(self, self.value))

    def on_click(self, event: events.Click) -> None:
        if self.value is not None:
            self.focus()
            self.post_message(self.Selected(self, self.value))


class ItemGroup(Vertical):
    """Items stacked. Up and Down move between the selectable ones."""

    DEFAULT_CSS = "ItemGroup { width: 1fr; height: auto; }"
    BINDINGS = [
        Binding("up", "step(-1)", show=False),
        Binding("down", "step(1)", show=False),
    ]

    def action_step(self, direction: int) -> None:
        rows = [i for i in self.query(Item) if i.value is not None]
        focused = self.screen.focused
        if focused not in rows:
            raise SkipAction()
        rows[(rows.index(focused) + direction) % len(rows)].focus()
