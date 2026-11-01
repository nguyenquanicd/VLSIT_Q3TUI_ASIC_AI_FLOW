"""Input, Textarea, and InputGroup, following shadcn's Input, Textarea, and Input Group.

Both fields are Textual's own widgets with the project look: one cell of padding for the text,
half-cell top and bottom edges that take the color behind them, and a `$panel` fill on focus.
"""

from __future__ import annotations

import re

from textual import events
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


def _lines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


_PASTE_TOKEN = re.compile(r"\[Pasted text #(\d+) \+\d+ lines?\]")


class Textarea(TextArea):
    """A multi-line field of `rows` text rows.

    With `collapse_pastes`, a pasted text of several lines shows as one token,
    `[Pasted text #1 +11 lines]`; Backspace after a token removes it whole, and `value` is the text
    with each token replaced by what was pasted. See spec/tui.md "Input boxes".
    """

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
        collapse_pastes: bool = False,
    ) -> None:
        self.collapse_pastes = collapse_pastes
        self._pastes: dict[int, str] = {}
        super().__init__(
            text,
            show_line_numbers=False,
            placeholder=placeholder,
            id=id,
            classes=classes,
            disabled=disabled,
        )
        self.styles.height = rows + 2  # Border-box: the two half-cell edge rows count.

    @property
    def value(self) -> str:
        """The text, each paste token replaced by the text it stands for."""

        def expand(match: re.Match[str]) -> str:
            return self._pastes.get(int(match[1]), match[0])

        return _PASTE_TOKEN.sub(expand, self.text) if self._pastes else self.text

    def load_text(self, text: str) -> None:
        self._pastes.clear()
        super().load_text(text)

    def clear(self):
        self._pastes.clear()
        return super().clear()

    async def _on_paste(self, event: events.Paste) -> None:
        text = _lines(event.text)
        if not self.collapse_pastes or self.read_only or "\n" not in text.strip("\n"):
            return  # Textual walks the MRO: TextArea's own handler pastes it as typed text
        event.prevent_default()
        number = max(self._pastes, default=0) + 1
        self._pastes[number] = text
        extra = text.count("\n")
        token = f"[Pasted text #{number} +{extra} line{'s' if extra != 1 else ''}]"
        if result := self._replace_via_keyboard(token, *self.selection):
            self.move_cursor(result.end_location)

    def action_delete_left(self) -> None:
        if self._pastes and self.selection.is_empty:
            row, column = self.cursor_location
            line = self.document[row][:column]
            for match in _PASTE_TOKEN.finditer(line):
                if match.end() == column and int(match[1]) in self._pastes:
                    self._delete_via_keyboard((row, match.start()), (row, column))
                    return
        super().action_delete_left()


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
