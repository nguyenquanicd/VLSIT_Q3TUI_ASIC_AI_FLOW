"""Spinner: a busy indicator, following shadcn's Spinner."""

from __future__ import annotations

from textual.timer import Timer
from textual.widgets import Static

from q3tui.tui.ui.icons import IconName, icon

__all__ = ["Spinner"]

_FRAMES: tuple[IconName, ...] = (
    "spinner_1",
    "spinner_2",
    "spinner_3",
    "spinner_4",
    "spinner_5",
    "spinner_6",
)


class Spinner(Static):
    """Cycles the Nerd Fonts progress-spinner glyphs, with an optional label after them."""

    DEFAULT_CSS = "Spinner { width: auto; height: 1; color: $primary; }"

    def __init__(
        self,
        label: str = "",
        *,
        interval: float = 0.12,
        running: bool = True,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes, markup=False)
        self.label = label
        self.interval = interval
        self.running = running
        self.frame = 0
        self._timer: Timer | None = None

    def on_mount(self) -> None:
        self._timer = self.set_interval(self.interval, self._tick, pause=not self.running)
        self._draw()

    def _draw(self) -> None:
        glyph = icon(_FRAMES[self.frame % len(_FRAMES)])
        self.update(f"{glyph} {self.label}" if self.label else glyph)

    def _tick(self) -> None:
        self.frame += 1
        self._draw()

    def start(self) -> None:
        self.running = True
        if self._timer:
            self._timer.resume()

    def stop(self) -> None:
        self.running = False
        if self._timer:
            self._timer.pause()
