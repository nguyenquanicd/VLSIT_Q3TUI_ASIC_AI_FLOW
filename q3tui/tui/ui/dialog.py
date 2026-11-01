"""Dialog: a modal screen composed from shadcn-style parts."""

from typing import Any

from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.content import Content
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Static

from q3tui.tui.ui.icons import icon, key_label
from q3tui.tui.ui.text_button import TextButton

__all__ = [
    "Dialog",
    "DialogClose",
    "DialogContent",
    "DialogDescription",
    "DialogFooter",
    "DialogHeader",
    "DialogTitle",
]


class DialogTitle(Static):
    DEFAULT_CSS = "DialogTitle { height: auto; text-style: bold; color: $foreground; }"

    def __init__(self, text: str, *, id: str | None = None) -> None:
        super().__init__(text, id=id, markup=False)


class DialogDescription(Static):
    DEFAULT_CSS = "DialogDescription { height: auto; color: $text-muted; }"

    def __init__(self, text: str, *, id: str | None = None) -> None:
        super().__init__(text, id=id, markup=False)


class DialogHeader(Vertical):
    DEFAULT_CSS = "DialogHeader { height: auto; }"


class DialogFooter(Horizontal):
    DEFAULT_CSS = """
    DialogFooter { height: auto; align-horizontal: right; }
    DialogFooter > TextButton { margin-left: 1; padding: 0 1; }
    """


class DialogClose(TextButton):
    """Closes the dialog and returns `value` to whoever opened it.

    `key` is a shortcut that does the same from anywhere in the dialog, as long as the
    focused widget does not use that key itself. It is shown in front of the label, like
    the prompt's submit hint.
    """

    def __init__(
        self,
        label: str,
        value: Any = None,
        *,
        key: str | None = None,
        variant: str = "default",
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        text = Content(label)
        if key:
            text = Content.assemble((f"{key_label(key)} ", "dim"), text)
        super().__init__(text, variant=variant, id=id, classes=classes, compact=True)
        self.value = value
        self.shortcut = key

    @on(Button.Pressed)
    def close_dialog(self, event: Button.Pressed) -> None:
        event.stop()
        self.screen.dismiss(self.value)


class DialogContent(Vertical):
    """The box. One cell of text padding on each side, half-cell edges above and below."""

    DEFAULT_CSS = """
    DialogContent {
        layers: base overlay; align-horizontal: right;
        width: 54; max-width: 95%; height: auto; max-height: 90%;
        padding: 0; background: $surface; color: $foreground;
        border-top: outer $background; border-bottom: outer $background;
    }
    DialogContent > * { layer: base; padding: 0 1; margin-bottom: 1; }
    DialogContent > *:last-child { margin-bottom: 0; }
    DialogContent.closable DialogHeader { padding: 0 4 0 1; }
    DialogContent > .dialog-close-layer { layer: overlay; width: auto; height: 1;
        padding: 0; margin: 0; }
    DialogContent .dialog-close { padding: 0; background: transparent; color: $text-muted; }
    DialogContent .dialog-close:hover { background: transparent; color: $foreground; }
    """


class Dialog(ModalScreen[Any]):
    """Modal dialog. Open with `app.push_screen(dialog, callback)`.

    Pass the parts to show (usually a `DialogHeader`, a body, and a `DialogFooter`); they
    are placed in a `DialogContent`. The backdrop is the screen itself. The dialog returns
    the `value` of the `DialogClose` that was pressed, or `None` for the close button and a
    click outside. A `DialogClose` with a `key` can also be pressed from anywhere in the
    dialog by that key; a `DialogClose` with `key="escape"` takes over Escape.
    """

    DEFAULT_CSS = """
    Dialog { align: center middle; background: $background 65%; }
    """
    BINDINGS = [Binding("escape", "close", "Close")]

    def __init__(
        self,
        *parts: Widget,
        show_close_button: bool = True,
        dismiss_on_outside_click: bool = True,
        initial_focus: str | None = None,
        width: int | None = None,
    ) -> None:
        super().__init__()
        self.parts = parts
        self.show_close_button = show_close_button
        self.dismiss_on_outside_click = dismiss_on_outside_click
        self.width = width
        if initial_focus:
            self.AUTO_FOCUS = initial_focus

    def compose(self) -> ComposeResult:
        with DialogContent(classes="closable" if self.show_close_button else ""):
            if self.show_close_button:
                with Container(classes="dialog-close-layer"):
                    close = DialogClose(icon("close"), classes="dialog-close")
                    close.can_focus = False  # Escape closes; the glyph is for the mouse.
                    yield close
            yield from self.parts

    def on_mount(self) -> None:
        if self.width is not None:
            self.query_one(DialogContent).styles.width = self.width
        for button in self.query(DialogClose):
            if button.shortcut and button.shortcut != "escape":
                self._bindings.bind(
                    button.shortcut, f"press_close({button.shortcut!r})", show=False
                )

    def _close_button(self, key: str) -> DialogClose | None:
        return next((b for b in self.query(DialogClose) if b.shortcut == key), None)

    def action_press_close(self, key: str) -> None:
        button = self._close_button(key)
        if button is not None and not button.disabled:
            button.press()

    def on_click(self, event: events.Click) -> None:
        if not self.dismiss_on_outside_click:
            return
        if self.get_widget_at(event.screen_x, event.screen_y)[0] is self:
            self.dismiss(None)

    def action_close(self) -> None:
        button = self._close_button("escape")
        if button is not None:
            button.press()
        else:
            self.dismiss(None)
