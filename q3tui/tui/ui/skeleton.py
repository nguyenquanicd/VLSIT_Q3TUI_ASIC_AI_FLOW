"""Skeleton: a pulsing placeholder for content that is loading, following shadcn's Skeleton."""

from __future__ import annotations

from textual.timer import Timer
from textual.widgets import Static

__all__ = ["Skeleton"]


class Skeleton(Static):
    """A block that fades between two surface colors. `width` and `height` are cells or a
    Textual size such as `"1fr"`."""

    DEFAULT_CSS = """
    Skeleton { background: $panel; }
    Skeleton.-pulse { background: $surface; }
    """

    def __init__(
        self,
        width: int | str = "1fr",
        height: int | str = 1,
        *,
        pulse: bool = True,
        interval: float = 0.7,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self.styles.width = width
        self.styles.height = height
        self.pulse = pulse
        self.interval = interval
        self._timer: Timer | None = None

    def on_mount(self) -> None:
        self._timer = self.set_interval(self.interval, self._toggle, pause=not self.pulse)

    def _toggle(self) -> None:
        self.toggle_class("-pulse")
