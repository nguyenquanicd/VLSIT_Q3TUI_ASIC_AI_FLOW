"""A minimal app that shows widgets under the vlsit-dark theme and the shared stylesheet."""

from textual.app import App, ComposeResult
from textual.widget import Widget

from q3tui.tui.themes import VLSIT_DARK


class Harness(App):
    CSS_PATH = "../../q3tui/tui/styles/app.tcss"

    def __init__(self, *widgets: Widget) -> None:
        super().__init__()
        self.widgets = widgets

    def compose(self) -> ComposeResult:
        yield from self.widgets

    def on_mount(self) -> None:
        self.register_theme(VLSIT_DARK)
        self.theme = VLSIT_DARK.name


def edge_colors(widget: Widget) -> tuple[str, str]:
    """The colors painted in the exposed half of the top and bottom edge rows (hex)."""
    from textual.geometry import Region

    size = widget.outer_size
    strips = widget._styles_cache.render_widget(widget, Region(0, 0, size.width, size.height))
    first, last = list(strips[0])[0], list(strips[-1])[0]
    return first.style.color.triplet.hex, last.style.color.triplet.hex


def screen_text(app: App) -> str:
    """Everything drawn on the screen, as plain text lines."""
    return "\n".join(strip.text for strip in app.screen._compositor.render_strips())
