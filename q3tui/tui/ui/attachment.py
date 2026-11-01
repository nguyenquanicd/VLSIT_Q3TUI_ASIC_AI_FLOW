"""Attachment, following shadcn's Attachment: a file chip with a state and actions."""

from __future__ import annotations

from typing import Literal

from textual import events
from textual.actions import SkipAction
from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message
from textual.timer import Timer

from q3tui.tui.ui.action import Action
from q3tui.tui.ui.icons import IconName, icon

__all__ = ["Attachment", "AttachmentGroup"]

AttachmentState = Literal["idle", "uploading", "processing", "error", "done"]
_SPINNER: tuple[IconName, ...] = (
    "spinner_1",
    "spinner_2",
    "spinner_3",
    "spinner_4",
    "spinner_5",
    "spinner_6",
)


class Attachment(Action):
    """`Attachment("report.pdf", "PDF · 1.2 MB", icon_name="file", removable=True)`.

    `state`: `done` (normal), `idle` (muted), `uploading` (a spinner and the `progress` percentage),
    `processing` (a spinner), `error` (red, with an error icon). Enter, Space, or a click posts
    `Attachment.Opened`. When `removable` the chip ends with a cross: a click on the cross, or
    **Delete** or Backspace on the focused chip, posts `Attachment.Removed`.
    """

    DEFAULT_CSS = """
    Attachment { width: auto; height: 1; padding: 0 1; background: $panel; color: $foreground; }
    Attachment:hover, Attachment:focus { text-style: underline; }
    Attachment.-idle { color: $text-muted; }
    Attachment.-uploading, Attachment.-processing { color: $text-muted; }
    Attachment.-error { background: $error-muted; color: $text-error; }
    """
    BINDINGS = [Binding("delete,backspace", "remove", show=False)]

    class Opened(Message):
        def __init__(self, attachment: Attachment) -> None:
            super().__init__()
            self.attachment = attachment

        @property
        def control(self) -> Attachment:
            return self.attachment

    class Removed(Message):
        def __init__(self, attachment: Attachment) -> None:
            super().__init__()
            self.attachment = attachment

        @property
        def control(self) -> Attachment:
            return self.attachment

    def __init__(
        self,
        name: str,
        description: str = "",
        *,
        icon_name: IconName = "file",
        state: AttachmentState = "done",
        progress: float | None = None,
        removable: bool = False,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        if state not in ("idle", "uploading", "processing", "error", "done"):
            raise ValueError(f"Unknown attachment state: {state!r}")
        super().__init__(name, icon_name=icon_name, id=id, classes=classes)
        self.filename = name  # Not `name`: that is a Textual widget property.
        self.description = description
        self.state = state
        self.progress = progress
        self.removable = removable
        self._frame = 0
        self._spin: Timer | None = None

    def on_mount(self) -> None:
        self.set_state(self.state, progress=self.progress)
        super().on_mount()

    def glyph_name(self) -> IconName | None:
        if self.state in ("uploading", "processing"):
            return _SPINNER[self._frame % len(_SPINNER)]
        if self.state == "error":
            return "error"
        return self.icon_name

    def set_state(self, state: AttachmentState, *, progress: float | None = None) -> None:
        self.state = state
        self.progress = progress
        for name in ("idle", "uploading", "processing", "error", "done"):
            self.set_class(name == state, f"-{name}")
        if self._spin:
            self._spin.stop()
            self._spin = None
        if state in ("uploading", "processing"):
            self._spin = self.set_interval(0.12, self._tick)
        self.refresh_label()

    def _tick(self) -> None:
        self._frame += 1
        self.refresh_label()

    def refresh_label(self) -> None:
        detail = self.description
        if self.state == "uploading" and self.progress is not None:
            detail = f"{round(self.progress * 100)}%"
        self.label = f"{self.filename} {detail}".strip()
        if self.removable:
            self.label += f" {icon('close')}"  # the cross
        super().refresh_label()

    def on_click(self, event: events.Click) -> None:
        """A click on the cross removes the chip (anywhere else opens it: `Action` does that)."""
        if self.removable and not self.disabled and event.x >= self.size.width - 3:
            event.stop()
            event.prevent_default()  # not the handler of `Action` too
            self.focus()
            self.action_remove()

    def activate(self) -> None:
        self.post_message(self.Opened(self))

    def action_remove(self) -> None:
        if not self.removable or self.disabled:
            raise SkipAction()
        self.post_message(self.Removed(self))


class AttachmentGroup(Horizontal):
    """Attachments in a row, one cell apart. Left and Right move between them."""

    DEFAULT_CSS = """
    AttachmentGroup { width: 1fr; height: auto; }
    AttachmentGroup > Attachment { margin-right: 1; }
    """
    BINDINGS = [
        Binding("left", "step(-1)", show=False),
        Binding("right", "step(1)", show=False),
    ]

    def action_step(self, direction: int) -> None:
        items = list(self.query(Attachment))
        focused = self.screen.focused
        if focused not in items:
            raise SkipAction()
        items[(items.index(focused) + direction) % len(items)].focus()
