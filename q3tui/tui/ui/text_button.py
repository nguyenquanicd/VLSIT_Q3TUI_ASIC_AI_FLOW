from textual.widgets import Button


class TextButton(Button):
    """A quiet, single-row action for toolbars and prompt suggestions."""

    def on_mount(self) -> None:
        self.active_effect_duration = 0

    DEFAULT_CSS = """
    TextButton.-style-default {
        height: 1;
        min-width: 0;
        border: none;
        background: transparent;
        color: $text-muted;
        text-style: none;
    }
    TextButton.-style-default:hover, TextButton.-style-default:focus {
        background: $panel;
        color: $foreground;
        text-style: none;
    }
    """
