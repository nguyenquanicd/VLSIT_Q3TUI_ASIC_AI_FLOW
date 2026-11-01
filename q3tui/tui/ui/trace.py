"""Trace, following shadcn's Trace: the lines of an agent's work (thinking, tool calls)."""

from __future__ import annotations

from typing import Literal

from textual.containers import Vertical
from textual.content import Content
from textual.timer import Timer
from textual.widget import Widget

from q3tui.tui.ui.action import Action
from q3tui.tui.ui.collapsible import Collapsible, CollapsibleContent
from q3tui.tui.ui.icons import IconName, icon

__all__ = ["Trace", "TraceCollapsible", "TraceLine"]

TraceStatus = Literal["running", "error", "pending"]
_SPINNER: tuple[IconName, ...] = (
    "spinner_1",
    "spinner_2",
    "spinner_3",
    "spinner_4",
    "spinner_5",
    "spinner_6",
)


class TraceLine(Action):
    """One line: an icon, a title, and a muted description.

    `status`: `running` shows a spinner and bold text, `error` is red with an error icon, and
    `pending` is dimmed. A line on its own is plain text and not a Tab stop; inside a
    `TraceCollapsible` it is the heading: Enter, Space, or a click opens the detail, and a chevron
    follows the line.
    """

    DEFAULT_CSS = """
    TraceLine { width: 1fr; height: 1; color: $text-muted; }
    TraceLine.-running { color: $foreground; text-style: bold; }
    TraceLine.-error { color: $text-error; }
    TraceLine.-pending { color: $text-muted; text-style: dim; }
    TraceLine.-expandable:hover, TraceLine.-expandable:focus { background: $panel;
        color: $foreground; }
    """

    def __init__(
        self,
        title: str,
        *,
        icon_name: IconName | None = None,
        description: str = "",
        status: TraceStatus | None = None,
        key: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        if status not in (None, "running", "error", "pending"):
            raise ValueError(f"Unknown trace status: {status!r}")
        super().__init__(title, key=key, icon_name=icon_name, id=id, classes=classes)
        self.description = description
        self.status = status
        self._frame = 0
        self._spin: Timer | None = None
        self.can_focus = False
        if status:
            self.add_class(f"-{status}")

    @property
    def section(self) -> Collapsible | None:
        return next((a for a in self.ancestors if isinstance(a, TraceCollapsible)), None)

    def on_mount(self) -> None:
        section = self.section
        if section is not None:
            self.can_focus = True
            self.add_class("-expandable")
        if self.status == "running":
            self._spin = self.set_interval(0.12, self._tick)
        super().on_mount()

    def glyph_name(self) -> IconName | None:
        if self.status == "running":
            return _SPINNER[self._frame % len(_SPINNER)]
        if self.status == "error":
            return "error"
        return self.icon_name

    def refresh_label(self) -> None:
        parts: list[str | tuple[str, str]] = []
        glyph = self.glyph()
        if glyph:
            parts += [glyph, " "]
        parts.append(self.label)
        if self.description:
            parts += [" ", (self.description, "dim")]
        section = self.section
        if section is not None:
            parts += [" ", icon("chevron_down" if section.open else "chevron_right")]
        self.update(Content.assemble(*parts))

    def set_status(self, status: TraceStatus | None) -> None:
        """Change the state of the line (a tool that was running is done: `None`)."""
        if status not in (None, "running", "error", "pending"):
            raise ValueError(f"Unknown trace status: {status!r}")
        if self.status:
            self.remove_class(f"-{self.status}")
        if self._spin is not None and status != "running":
            self._spin.stop()
            self._spin = None
        if status == "running" and self._spin is None and self.is_mounted:
            self._spin = self.set_interval(0.12, self._tick)
        self.status = status
        if status:
            self.add_class(f"-{status}")
        self.refresh_label()

    def _tick(self) -> None:
        self._frame += 1
        self.refresh_label()

    def activate(self) -> None:
        section = self.section
        if section is not None:
            section.set_open(not section.open)


class TraceCollapsible(Collapsible):
    """A line that expands: `TraceCollapsible(TraceLine("Ran pnpm test"), Static("output"))`."""

    DEFAULT_CSS = "TraceCollapsible { height: auto; }"

    def __init__(
        self,
        line: TraceLine,
        *content: Widget,
        open: bool = False,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(line, CollapsibleContent(*content), open=open, id=id, classes=classes)

    def _apply(self) -> None:
        for content in self.query(CollapsibleContent):
            content.display = self.open
        for line in self.query(TraceLine):
            line.refresh_label()


class Trace(Vertical):
    """A list of lines, one under the other."""

    DEFAULT_CSS = "Trace { width: 1fr; height: auto; }"
