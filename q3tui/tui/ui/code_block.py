"""CodeBlock, following shadcn's Code Block: code or terminal output with a title and copy."""

from __future__ import annotations

from typing import Literal

from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Static

from q3tui.tui.ui.action import Action
from q3tui.tui.ui.icons import IconName, icon

__all__ = ["CodeBlock"]


class _CopyButton(Action):
    DEFAULT_CSS = """
    _CopyButton { width: auto; height: 1; padding: 0 1; color: $text-muted; }
    _CopyButton:hover, _CopyButton:focus { background: $panel; color: $foreground; }
    """

    def activate(self) -> None:
        block = next((a for a in self.ancestors if isinstance(a, CodeBlock)), None)
        if block is not None:
            block.copy()


class CodeBlock(Vertical):
    """`CodeBlock(code, language="python", title="main.py", line_numbers=True, max_height=12)`.

    The code is highlighted with Rich (Pygments) in the terminal's own ANSI colors, so it follows
    the terminal palette. The content is a Tab stop and scrolls with the arrow keys, PageUp and
    PageDown, Home and End. **`c` copies the code** while the block has focus (the header shows the
    key) and posts `CodeBlock.Copied`. `variant="destructive"` tints the block for errors, and
    `title=None` leaves out the header.
    """

    DEFAULT_CSS = """
    CodeBlock { width: 1fr; height: auto; background: $surface;
        border-top: outer transparent; border-bottom: outer transparent; }
    CodeBlock.-destructive { background: $error-muted; }
    CodeBlock > .code-header { height: 1; padding: 0 1; background: $panel; }
    CodeBlock > .code-header > .code-title { width: 1fr; text-style: bold; color: $foreground; }
    CodeBlock > .code-scroll { height: auto; padding: 0 1; background: transparent; }
    CodeBlock > .code-scroll:focus { background-tint: transparent; text-style: none; }
    CodeBlock .code-text { width: auto; height: auto; }
    """
    BINDINGS = [Binding("c", "copy", show=False)]

    class Copied(Message):
        def __init__(self, block: CodeBlock, code: str) -> None:
            super().__init__()
            self.block = block
            self.code = code

        @property
        def control(self) -> CodeBlock:
            return self.block

    def __init__(
        self,
        code: str,
        *,
        language: str | None = None,
        title: str | None = None,
        icon_name: IconName | None = "file_code",
        line_numbers: bool = False,
        start_line: int = 1,
        wrap: bool = False,
        max_height: int | None = None,
        variant: Literal["default", "destructive"] = "default",
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self.code = code
        self.language = language
        self.title = title
        self.icon_name = icon_name
        self.line_numbers = line_numbers
        self.start_line = start_line
        self.wrap = wrap
        self.max_height = max_height
        self.set_class(variant == "destructive", "-destructive")

    def compose(self) -> ComposeResult:
        if self.title:
            with Horizontal(classes="code-header"):
                label = f"{icon(self.icon_name)} {self.title}" if self.icon_name else self.title
                yield Static(label, classes="code-title", markup=False)
                yield _CopyButton("copy", hint="c")
        with VerticalScroll(classes="code-scroll"):
            yield Static(self.renderable(), classes="code-text")

    def renderable(self) -> Syntax:
        dark = getattr(self.app.current_theme, "dark", True) if self.is_attached else True
        return Syntax(
            self.code.rstrip("\n"),
            self.language or "text",
            theme="ansi_dark" if dark else "ansi_light",
            line_numbers=self.line_numbers,
            start_line=self.start_line,
            word_wrap=self.wrap,
            background_color="default",
        )

    def on_mount(self) -> None:
        if self.max_height:
            self.query_one(".code-scroll").styles.max_height = self.max_height
        self.watch(self.app, "theme", lambda _: self.refresh_code(), init=False)

    def refresh_code(self) -> None:
        if self.is_mounted:
            self.query_one(".code-text", Static).update(self.renderable())

    def set_code(self, code: str) -> None:
        """Replace the code, for example while it streams in."""
        self.code = code
        self.refresh_code()

    def copy(self) -> None:
        self.app.copy_to_clipboard(self.code)
        self.post_message(self.Copied(self, self.code))

    def action_copy(self) -> None:
        self.copy()
