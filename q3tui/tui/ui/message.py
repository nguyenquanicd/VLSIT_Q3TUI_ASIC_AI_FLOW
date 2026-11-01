"""Message, following shadcn's Message: a conversation row with an avatar, header, and footer."""

from __future__ import annotations

from typing import Literal

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Static

from q3tui.tui.ui.avatar import Avatar

__all__ = [
    "Message",
    "MessageAvatar",
    "MessageContent",
    "MessageFooter",
    "MessageGroup",
    "MessageHeader",
]


class MessageAvatar(Horizontal):
    """The avatar column. `MessageAvatar("Ada Lovelace")`, or `MessageAvatar()` for an empty slot
    that keeps earlier messages of a group lined up with the avatar on the last one."""

    DEFAULT_CSS = "MessageAvatar { width: 5; height: auto; padding: 0 0 0 1; }"

    def __init__(self, name: str = "", *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.person = name

    def compose(self) -> ComposeResult:
        if self.person:
            yield Avatar(self.person)


class MessageHeader(Static):
    """A sender name above the bubble."""

    DEFAULT_CSS = "MessageHeader { width: auto; height: 1; padding: 0 1; color: $text-muted; }"

    def __init__(self, text: str, *, id: str | None = None) -> None:
        super().__init__(text, id=id, markup=False)


class MessageFooter(Static):
    """Metadata under the bubble: a delivery status, a time."""

    DEFAULT_CSS = "MessageFooter { width: auto; height: 1; padding: 0 1; color: $text-muted; }"

    def __init__(self, text: str, *, id: str | None = None) -> None:
        super().__init__(text, id=id, markup=False)


class MessageContent(Vertical):
    """The column that holds the header, the bubble, and the footer."""

    DEFAULT_CSS = "MessageContent { width: 1fr; height: auto; }"


class Message(Horizontal):
    """`Message(MessageAvatar("Ada"), MessageContent(MessageHeader("Ada"), Bubble("Hi")))`.

    `align="end"` puts the row on the right (the current user): the content is right-aligned and
    the avatar goes after it.
    """

    DEFAULT_CSS = """
    Message { width: 1fr; height: auto; }
    Message.-end > MessageContent > MessageHeader,
    Message.-end > MessageContent > MessageFooter { align-horizontal: right; text-align: right;
        width: 1fr; }
    Message.-end > MessageContent { align-horizontal: right; }
    """

    def __init__(
        self,
        *parts: Widget,
        align: Literal["start", "end"] = "start",
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        ordered = list(reversed(parts)) if align == "end" else list(parts)
        super().__init__(*ordered, id=id, classes=classes)
        self.align = align
        self.set_class(align == "end", "-end")


class MessageGroup(Vertical):
    """Consecutive messages from one sender."""

    DEFAULT_CSS = "MessageGroup { width: 1fr; height: auto; }"
