"""Textual's Markdown, with ```mermaid and ```wavedrom blocks drawn as diagrams (spec/tui.md "Main"): the source
when it cannot be drawn; a click (or Enter) shows a diagram larger, in a Dialog."""

from __future__ import annotations

from textual import events
from textual.binding import Binding
from textual.containers import ScrollableContainer
from textual.content import Content
from textual.widgets import Markdown, Static
from textual.widgets._markdown import MarkdownFence

from q3tui.tui.diagrams import draw
from q3tui.tui.ui.dialog import Dialog, DialogDescription, DialogHeader, DialogTitle


class DiagramFence(MarkdownFence):
    """A fenced block; a diagram is drawn, never wrapped, scrolls sideways, and opens larger in a Dialog."""

    DEFAULT_CSS = """
    DiagramFence.-diagram > Label { text-wrap: nowrap; width: auto; }
    DiagramFence.-diagram:focus { background: $panel; }
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

    def notify_style_update(self) -> None:
        if self.art is None:
            super().notify_style_update()

    def _copy_context(self, block) -> None:
        super()._copy_context(block)
        if isinstance(block, DiagramFence):
            self.art = block.art
            self.set_class(self.art is not None, "-diagram")
            self.can_focus = self.art is not None

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
