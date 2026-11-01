from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from q3tui.tui.ui.icons import key_label
from q3tui.tui.ui.input import Textarea

PROMPT_ROWS = 6  # an intent is a document: room for a screenful of it


class PromptInput(Textarea):
    BINDINGS = [
        Binding("enter", "submit", "Submit", priority=True),
        Binding("shift+enter", "line_break", "New line", priority=True),
    ]

    class Submitted(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def __init__(self, *, placeholder: str = "", id: str | None = None) -> None:
        super().__init__(rows=PROMPT_ROWS, placeholder=placeholder, id=id, collapse_pastes=True)
        self.styles.height = None  # the stylesheet sizes it: a short screen shrinks it

    def action_submit(self) -> None:
        self.post_message(self.Submitted(self.value))

    def action_line_break(self) -> None:
        self.replace("\n", *self.selection)


class PromptBox(Widget):
    """The Textarea component with the submit hints under it. Its own focus look (a lighter
    surface) shows where the keyboard is."""

    DEFAULT_CSS = """
    PromptBox { layout: vertical; height: 9; background: transparent; }
    PromptBox PromptInput { width: 1fr; height: 8; }
    PromptBox .submit-hint { width: 1fr; height: 1;
        text-align: right; color: $text-muted; text-opacity: 60%; }
    """

    class Submitted(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def compose(self) -> ComposeResult:
        yield PromptInput(placeholder="Describe your design intent…", id="prompt-input")
        yield Static(
            f"{key_label('shift+enter')} new line · {key_label('enter')} submit",
            classes="submit-hint",
            markup=False,
        )

    def focus_input(self) -> None:
        self.query_one(PromptInput).focus()

    def set_value(self, value: str, *, at_end: bool = True) -> None:
        """Replace the text. The cursor goes to the end, or to the top to read a long text."""
        field = self.query_one(PromptInput)
        field.load_text(value)
        field.move_cursor(field.document.end if at_end else (0, 0))
        field.focus()

    def clear(self) -> None:
        self.set_value("")

    def submit(self) -> None:
        text = self.query_one(PromptInput).value.strip()
        if text:
            self.post_message(self.Submitted(text))

    @on(PromptInput.Submitted)
    def input_submitted(self, event: PromptInput.Submitted) -> None:
        event.stop()
        self.submit()
