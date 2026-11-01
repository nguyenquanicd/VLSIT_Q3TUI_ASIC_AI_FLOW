"""Textual's Markdown, with ```mermaid and ```wavedrom blocks drawn as diagrams (spec/tui.md "Main"): the source
when it cannot be drawn; a click (or Enter) shows a diagram larger, in a Dialog. Any other code block has a header
with its language and "copy"."""

from __future__ import annotations

from textual import events
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer
from textual.content import Content
from textual.widgets import Label, Markdown, Static
from textual.widgets._markdown import MarkdownFence

from q3tui.tui.diagrams import draw
from q3tui.tui.ui.action import Action
from q3tui.tui.ui.dialog import Dialog, DialogDescription, DialogHeader, DialogTitle


class CopyCode(Action):
    """The "copy" of a code block: a click copies its code."""

    DEFAULT_CSS = """
    CopyCode { width: auto; height: 1; padding: 0 1; color: $text-muted; }
    CopyCode:hover { background: $panel; color: $foreground; }
    """

    def __init__(self) -> None:
        super().__init__("copy")
        self.can_focus = False

    def activate(self) -> None:
        fence = next(a for a in self.ancestors if isinstance(a, DiagramFence))
        self.app.copy_to_clipboard(fence.code)
        toast = getattr(self.app, "toast", None)
        if toast is not None:
            toast("Copied")


class DiagramFence(MarkdownFence):
    """A fenced block; a diagram is drawn, never wrapped, scrolls sideways, and opens larger in a Dialog; other code
    has a header: its language and "copy"."""

    DEFAULT_CSS = """
    DiagramFence.-diagram > Label { text-wrap: nowrap; width: auto; }
    DiagramFence.-diagram:focus { background: $panel; }
    DiagramFence > .code-head { height: 1; background: $panel; padding: 0 0 0 2; }
    DiagramFence > .code-head > .code-lang { width: 1fr; color: $text-muted; }
    DiagramFence > Label.-headed { padding: 0 2 1 2; }
    """
    BINDINGS = [Binding("enter", "enlarge", show=False)]

    def __init__(self, markdown: Markdown, token, code: str) -> None:
        super().__init__(markdown, token, code)
        self.art = draw(code, self.lexer)
        if self.art is not None:
            self._highlighted_code = Content(self.art)
            self.add_class("-diagram")
            self.can_focus = True
            self.tooltip = "Click or Enter: larger, in a dialog"

    def compose(self):
        if self.art is None:
            yield Horizontal(Static(self.lexer or "code", classes="code-lang", markup=False), CopyCode(),
                             classes="code-head")
        yield Label(self._highlighted_code, id="code-content", expand=True, classes="" if self.art else "-headed")

    def notify_style_update(self) -> None:
        if self.art is None:
            super().notify_style_update()

    def _copy_context(self, block) -> None:
        super()._copy_context(block)
        if isinstance(block, DiagramFence):
            headed = self.art is None
            self.art = block.art
            self.set_class(self.art is not None, "-diagram")
            self.can_focus = self.art is not None
            if headed != (self.art is None):  # a diagram became code, or the reverse: its header changes
                self.call_later(self.recompose)

    def action_enlarge(self) -> None:
        if self.art is not None:
            self.app.push_screen(DiagramDialog(self.art, f"Diagram ({self.lexer})"))

    def on_click(self, event: events.Click) -> None:
        if self.art is not None:
            event.stop()
            self.action_enlarge()


class Q3Markdown(Markdown):
    BLOCKS = {**Markdown.BLOCKS, "fence": DiagramFence, "code_block": DiagramFence}


class DiagramDialog(Dialog):
    """One diagram, larger, in a Dialog over the screen: the arrows scroll it, Escape or a click outside closes it."""

    DEFAULT_CSS = """
    DiagramDialog DialogContent { max-width: 95%; max-height: 90%; }
    DiagramDialog .diagram-view { width: 1fr; height: auto; max-height: 40; }
    DiagramDialog .diagram-view > Static { width: auto; text-wrap: nowrap; }
    """

    def __init__(self, art: str, title: str = "Diagram") -> None:
        widest = max((len(line) for line in art.splitlines()), default=20)
        view = ScrollableContainer(Static(art, markup=False), classes="diagram-view")
        super().__init__(DialogHeader(DialogTitle(title), DialogDescription("↑↓←→ scroll · Esc close")), view,
                         initial_focus=".diagram-view", width=min(widest + 6, 300))
