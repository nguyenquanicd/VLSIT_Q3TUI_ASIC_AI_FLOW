"""Scrollbars that look the same thickness both ways (spec/tui.md "Look"): a cell is about twice as tall as it is
wide, so the one-column vertical bar is about half a row thick; the horizontal bar's thumb is drawn with the lower
half block (▄), half a row, instead of a whole row. Clicking and dragging work as before."""

from __future__ import annotations

from math import ceil

from rich.color import Color
from rich.segment import Segment, Segments
from rich.style import Style
from textual.scrollbar import ScrollBar, ScrollBarRender

THUMB = "▄"
BACK, BAR = Color.parse("#555555"), Color.parse("bright_magenta")  # Textual's defaults; the styles give the real ones


class BalancedScrollBarRender(ScrollBarRender):
    @classmethod
    def render_bar(cls, size: int = 25, virtual_size: float = 50, window_size: float = 20, position: float = 0,
                   thickness: int = 1, vertical: bool = True, back_color: Color = BACK,
                   bar_color: Color = BAR) -> Segments:
        if vertical:
            return super().render_bar(size, virtual_size, window_size, position, thickness, vertical, back_color,
                                      bar_color)
        size = int(size)
        back = Style(bgcolor=back_color)
        if not (window_size and size and virtual_size and size != virtual_size):
            return Segments([Segment(" " * size, back), Segment.line()] * thickness, new_lines=False)
        thumb = max(1, ceil(window_size * size / virtual_size))
        start = round((size - thumb) * position / max(1, virtual_size - window_size))
        start = max(0, min(size - thumb, start))
        left = Style(bgcolor=back_color, meta={"@mouse.down": "scroll_up"})
        right = Style(bgcolor=back_color, meta={"@mouse.down": "scroll_down"})
        grab = Style(color=bar_color, bgcolor=back_color, meta={"@mouse.down": "grab"})
        row = [Segment(" " * start, left), Segment(THUMB * thumb, grab), Segment(" " * (size - start - thumb), right),
               Segment.line()]
        return Segments(row * thickness, new_lines=False)


def install() -> None:
    ScrollBar.renderer = BalancedScrollBarRender
