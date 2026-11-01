"""Input, Textarea, and InputGroup, following shadcn's Input, Textarea, and Input Group.

Both fields are Textual's own widgets with the project look: one cell of padding for the text,
half-cell top and bottom edges that take the color behind them, and a `$panel` fill on focus.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Input as TextualInput
from textual.widgets import Static, TextArea

from q3tui.tui.ui.icons import IconName, icon

__all__ = ["Input", "InputGroup", "InputGroupAddon", "Textarea"]


class Input(TextualInput):
    """A one-line field. `Input.Changed`, `Input.Submitted`, and validators are Textual's; an
    invalid value (`-invalid`) gets an error-tinted fill."""

    DEFAULT_CSS = """
    Input { height: 3; padding: 0 1; background: $surface; color: $foreground; border: none;
        border-top: outer transparent; border-bottom: outer transparent; }
    Input:focus { border: none; border-top: outer transparent; border-bottom: outer transparent;
        background: $panel; }
    Input > .input--placeholder { color: $text-muted; }
    Input.-invalid, Input.-invalid:focus { background: $error-muted; }
    Input:disabled { opacity: 50%; }
    """


class Textarea(TextArea):
    """A multi-line field of `rows` text rows."""

    DEFAULT_CSS = """
    Textarea { padding: 0 1; background: $surface; color: $foreground; border: none;
        border-top: outer transparent; border-bottom: outer transparent; }
    Textarea:focus { border: none; border-top: outer transparent;
        border-bottom: outer transparent; background: $panel; }
    Textarea > .text-area--placeholder { color: $text-muted; }
    Textarea:disabled { opacity: 50%; }
    """

    def __init__(
        self,
        text: str = "",
        *,
        rows: int = 3,
        placeholder: str = "",
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(
            text,
            show_line_numbers=False,
            placeholder=placeholder,
            id=id,
            classes=classes,
            disabled=disabled,
        )
        self.styles.height = rows + 2  # Border-box: the two half-cell edge rows count.


class InputGroupAddon(Horizontal):
    """Muted text, an icon, or small widgets at either end of an `InputGroup`."""

    DEFAULT_CSS = """
    InputGroupAddon { width: auto; height: 1; padding: 0 1; color: $text-muted; }
    InputGroupAddon > Static { width: auto; }
    """

    def __init__(
        self,
        text: str = "",
        *widgets: Widget,
        icon_name: IconName | None = None,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self.text = f"{icon(icon_name)} {text}".strip() if icon_name else text
        self.widgets = widgets

    def compose(self) -> ComposeResult:
        if self.text:
            yield Static(self.text, markup=False)
        yield from self.widgets


class InputGroup(Horizontal):
    """An `Input` between addons, sharing one fill that deepens while the group has focus."""

    DEFAULT_CSS = """
    InputGroup { width: 1fr; height: 3; background: $surface;
        border-top: outer transparent; border-bottom: outer transparent; }
    InputGroup:focus-within { background: $panel; }
    InputGroup > Input { width: 1fr; height: 1; background: transparent; padding: 0;
        border-top: none; border-bottom: none; }
    InputGroup > Input:focus { background: transparent; border-top: none; border-bottom: none; }
    """
