"""Progress: a bar for work with a known or unknown length, following shadcn's Progress."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import Static

__all__ = ["Progress"]


class Progress(Horizontal):
    """`label  [=====-----]  42%`, drawn with colored cells and no glyphs.

    Set `value` (0 to `total`) as work advances. An indeterminate bar slides a block along
    the track instead.
    """

    DEFAULT_CSS = """
    Progress { width: 1fr; height: 1; }
    Progress > .progress-label { width: auto; padding: 0 1 0 0; color: $text-muted; }
    Progress > .progress-track { width: 1fr; height: 1; background: $panel; }
    Progress .progress-fill { height: 1; background: $primary; }
    Progress .progress-pre, Progress .progress-rest { height: 1; }
    Progress > .progress-value { width: 5; text-align: right; color: $text-muted; }
    """

    value = reactive(0.0)

    def __init__(
        self,
        value: float = 0,
        total: float = 100,
        *,
        label: str = "",
        show_value: bool = True,
        indeterminate: bool = False,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        if total <= 0:
            raise ValueError("Progress total must be positive")
        self.total = total
        self.label = label
        self.show_value = show_value
        self.indeterminate = indeterminate
        self._position = 0
        self._timer: Timer | None = None
        self.set_reactive(Progress.value, float(value))

    @property
    def fraction(self) -> float:
        return max(0.0, min(1.0, self.value / self.total))

    def advance(self, amount: float = 1) -> None:
        self.value = min(self.total, self.value + amount)

    def compose(self) -> ComposeResult:
        if self.label:
            yield Static(self.label, classes="progress-label", markup=False)
        with Horizontal(classes="progress-track"):
            yield Static("", classes="progress-pre")
            yield Static("", classes="progress-fill")
            yield Static("", classes="progress-rest")
        if self.show_value and not self.indeterminate:
            yield Static("", classes="progress-value", markup=False)

    def on_mount(self) -> None:
        if self.indeterminate:
            self._timer = self.set_interval(0.08, self._slide)
        self._draw()

    def watch_value(self) -> None:
        if self.is_mounted:
            self._draw()

    def _slide(self) -> None:
        self._position = (self._position + 1) % 20
        self._draw()

    def _draw(self) -> None:
        pre, fill, rest = (self.query_one(f".progress-{name}") for name in ("pre", "fill", "rest"))
        if self.indeterminate:
            widths = (self._position, 4, 20 - self._position)
        else:
            done = round(self.fraction * 1000)
            widths = (0, done, 1000 - done)
        for widget, width in zip((pre, fill, rest), widths):
            widget.display = width > 0
            if width > 0:
                widget.styles.width = f"{width}fr"
        for widget in self.query(".progress-value"):
            widget.update(f"{round(self.fraction * 100)}%")
