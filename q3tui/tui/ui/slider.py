"""Slider: pick a number on a track with the keyboard, following shadcn's Slider."""

from __future__ import annotations

from textual import events
from textual.actions import SkipAction
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Static

__all__ = ["Slider"]


class Slider(Horizontal, can_focus=True):
    """`label  [fill|thumb|rest]  value`, drawn with colored cells and no glyphs.

    Left/Down and Right/Up change the value by `step`, Page Down/Up by ten steps, Home/End jump
    to the ends, and a click on the track sets the value there.
    """

    DEFAULT_CSS = """
    Slider { width: 1fr; height: 1; }
    Slider > .slider-label { width: auto; padding: 0 1 0 0; color: $text-muted; }
    Slider > .slider-track { width: 1fr; height: 1; background: $panel; }
    Slider .slider-fill { height: 1; background: $primary; }
    Slider .slider-thumb { width: 1; height: 1; background: $foreground; }
    Slider .slider-rest { height: 1; }
    Slider:focus .slider-thumb { background: $accent; }
    Slider > .slider-value { width: 6; text-align: right; color: $text-muted; }
    Slider:disabled { opacity: 50%; }
    """
    BINDINGS = [
        Binding("left,down", "nudge(-1)", show=False),
        Binding("right,up", "nudge(1)", show=False),
        Binding("pagedown", "nudge(-10)", show=False),
        Binding("pageup", "nudge(10)", show=False),
        Binding("home", "jump('min')", show=False),
        Binding("end", "jump('max')", show=False),
    ]

    value = reactive(0.0)

    class Changed(Message):
        def __init__(self, slider: Slider, value: float) -> None:
            super().__init__()
            self.slider = slider
            self.value = value

        @property
        def control(self) -> Slider:
            return self.slider

    def __init__(
        self,
        value: float = 0,
        *,
        minimum: float = 0,
        maximum: float = 100,
        step: float = 1,
        label: str = "",
        show_value: bool = True,
        disabled: bool = False,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes, disabled=disabled)
        if maximum <= minimum or step <= 0:
            raise ValueError("Slider needs minimum < maximum and a positive step")
        self.minimum = minimum
        self.maximum = maximum
        self.step = step
        self.label = label
        self.show_value = show_value
        self.set_reactive(Slider.value, self._clamp(value))

    def _clamp(self, value: float) -> float:
        snapped = self.minimum + round((value - self.minimum) / self.step) * self.step
        return max(self.minimum, min(self.maximum, snapped))

    def set_value(self, value: float, *, notify: bool = True) -> None:
        value = self._clamp(value)
        if value != self.value:
            self.value = value
            if notify:
                self.post_message(self.Changed(self, value))

    def compose(self) -> ComposeResult:
        if self.label:
            yield Static(self.label, classes="slider-label", markup=False)
        with Horizontal(classes="slider-track"):
            yield Static("", classes="slider-fill")
            yield Static("", classes="slider-thumb")
            yield Static("", classes="slider-rest")
        if self.show_value:
            yield Static("", classes="slider-value", markup=False)

    def on_mount(self) -> None:
        self._draw()

    def watch_value(self) -> None:
        if self.is_mounted:
            self._draw()

    def _draw(self) -> None:
        span = round((self.maximum - self.minimum) / self.step)
        at = round((self.value - self.minimum) / self.step)
        fill, rest = self.query_one(".slider-fill"), self.query_one(".slider-rest")
        for widget, width in ((fill, at), (rest, span - at)):
            widget.display = width > 0
            if width > 0:
                widget.styles.width = f"{width}fr"
        for widget in self.query(".slider-value"):
            text = f"{self.value:g}"
            widget.update(text)

    def action_nudge(self, steps: int) -> None:
        if self.disabled:
            raise SkipAction()
        self.set_value(self.value + steps * self.step)

    def action_jump(self, end: str) -> None:
        if self.disabled:
            raise SkipAction()
        self.set_value(self.minimum if end == "min" else self.maximum)

    def on_click(self, event: events.Click) -> None:
        track = self.query_one(".slider-track")
        offset = event.screen_x - track.region.x
        if self.disabled or not 0 <= offset < track.region.width:
            return
        event.stop()
        self.focus()
        ratio = offset / max(1, track.region.width - 1)
        self.set_value(self.minimum + ratio * (self.maximum - self.minimum))
