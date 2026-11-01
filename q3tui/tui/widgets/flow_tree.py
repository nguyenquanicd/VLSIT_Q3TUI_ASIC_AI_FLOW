"""The Flow tab: the stages and their steps, each with its display state; the selected row shows its buttons, and
[⋯], a right click or Shift+F10 opens its context menu (spec/tui.md "Flow tree")."""

from __future__ import annotations

from textual import events
from textual.actions import SkipAction
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.content import Content
from textual.message import Message
from textual.widgets import Static

from q3tui.engine.engine import StepStatus
from q3tui.flowdef import Flow
from q3tui.tui.labels import DISPLAY, state_icon
from q3tui.tui.ui.action import Action
from q3tui.tui.ui.context_menu import ContextMenu
from q3tui.tui.ui.icons import icon
from q3tui.tui.ui.menu import MenuContent


class RowButton(Action):
    DEFAULT_CSS = """
    RowButton { width: 3; height: 1; color: $text-muted; display: none; }
    RowButton:hover { color: $foreground; background: $surface; }
    """

    def __init__(self, glyph: str, action: str, tooltip: str) -> None:
        super().__init__(glyph)
        self.action = action
        self.can_focus = False
        self.tooltip = tooltip

    def activate(self) -> None:
        row = next(a for a in self.ancestors if isinstance(a, FlowRow))
        if self.action == "more":  # the menu opens under the button
            row.focus()
            row.post_message(FlowTree.Act(row.flow_tree, row.kind, row.ident, "more", (self.region.x, self.region.bottom)))
            return
        row.post_message(FlowTree.Act(row.flow_tree, row.kind, row.ident, self.action))


class FlowRow(Horizontal, can_focus=True):
    """A stage or a step."""

    DEFAULT_CSS = """
    FlowRow { width: 1fr; height: 1; padding: 0 1; }
    FlowRow > .row-label { width: 1fr; height: 1; text-wrap: nowrap; text-overflow: ellipsis; }
    FlowRow.-stage > .row-label { text-style: bold; }
    FlowRow:hover, FlowRow:focus { background: $panel; }
    FlowRow:focus > RowButton, FlowRow.-selected > RowButton { display: block; }
    FlowRow.-selected { background: $surface; }
    """

    def __init__(self, tree: FlowTree, kind: str, name: str, *, last: bool = False) -> None:
        super().__init__(classes=f"-{kind}")
        self.flow_tree, self.kind, self.ident, self.last = tree, kind, name, last
        self.status: StepStatus | None = None
        self.expanded = True

    def compose(self) -> ComposeResult:
        yield Static("", classes="row-label")
        yield RowButton("▶", "run", "Run to here" if self.kind == "step" else "Run the stage")
        if self.kind == "step":
            yield RowButton("↻", "rerun", "Run again")
        yield RowButton(icon("ellipsis"), "more", "More…")

    def on_mount(self) -> None:
        self.refresh_label()

    def refresh_label(self) -> None:
        labels = self.query(".row-label")
        if not labels:
            return
        label = labels.first(Static)
        if self.kind == "stage":
            label.update(Content.assemble((icon("chevron_down" if self.expanded else "chevron_right"), "dim"),
                                          f" {self.ident}"))
            return
        st = self.status
        text, style, _ = DISPLAY[st.display] if st else ("", "", "")
        label.update(Content.assemble((" └ " if self.last else " ├ ", "dim"),
                                      state_icon(st) if st else " ", f" {self.ident}  ", (text, style)))

    def on_click(self, event: events.Click) -> None:
        if event.button == 3:
            self.focus()
            self.post_message(FlowTree.Act(self.flow_tree, self.kind, self.ident, "more",
                                           (event.screen_x, event.screen_y + 1)))
            return
        self.focus()
        if self.kind == "step":
            self.post_message(FlowTree.Selected(self.flow_tree, self.ident))
        elif event.chain == 2:
            self.flow_tree.set_expanded(self, not self.expanded)

    def key_enter(self) -> None:
        if self.kind == "step":
            self.post_message(FlowTree.Selected(self.flow_tree, self.ident))
        else:
            self.flow_tree.set_expanded(self, not self.expanded)


class FlowTree(VerticalScroll):
    """Up and Down move, Left closes a stage, Right opens it, Enter selects a step."""

    DEFAULT_CSS = """
    FlowTree { height: 1fr; }
    FlowTree > .flow-empty { padding: 0 1; color: $text-muted; }
    """
    BINDINGS = [
        Binding("up", "move(-1)", show=False),
        Binding("down", "move(1)", show=False),
        Binding("left", "fold(False)", show=False),
        Binding("right", "fold(True)", show=False),
        Binding("shift+f10", "more", show=False),
    ]

    class Selected(Message):
        def __init__(self, tree: FlowTree, step: str) -> None:
            super().__init__()
            self.tree, self.step = tree, step

    class Act(Message):
        """A button of a row: `action` is run, rerun or more (`at`: where its menu opens, a screen cell)."""

        def __init__(self, tree: FlowTree, kind: str, name: str, action: str,
                     at: tuple[int, int] | None = None) -> None:
            super().__init__()
            self.tree, self.kind, self.name, self.action, self.at = tree, kind, name, action, at

    def __init__(self, flow: Flow | None, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.flow = flow
        self.selected: str | None = None

    def compose(self) -> ComposeResult:
        if self.flow is None or not self.flow.stages:
            yield Static("No flow loaded", classes="flow-empty")
            return
        yield RowMenu()
        for stage in self.flow.stages:
            yield FlowRow(self, "stage", stage.name)
            for n, sid in enumerate(stage.steps):
                yield FlowRow(self, "step", sid, last=n == len(stage.steps) - 1)

    @property
    def rows(self) -> list[FlowRow]:
        return [r for r in self.query(FlowRow) if r.display]

    def step_row(self, sid: str) -> FlowRow | None:
        return next((r for r in self.query(FlowRow) if r.kind == "step" and r.ident == sid), None)

    def update_statuses(self, statuses: list[StepStatus]) -> None:
        for st in statuses:
            row = self.step_row(st.id)
            if row is not None and (row.status is None or row.status != st):
                row.status = st
                row.refresh_label()

    def select(self, sid: str | None) -> None:
        self.selected = sid
        for r in self.query(FlowRow):
            r.set_class(r.kind == "step" and r.ident == sid, "-selected")

    def focused_step(self) -> str | None:
        focused = self.screen.focused if self.is_attached else None
        if isinstance(focused, FlowRow) and focused.kind == "step":
            return focused.ident
        return None

    def set_expanded(self, stage: FlowRow, expanded: bool) -> None:
        stage.expanded = expanded
        stage.refresh_label()
        steps = set(next(s for s in self.flow.stages if s.name == stage.ident).steps)
        for r in self.query(FlowRow):
            if r.kind == "step" and r.ident in steps:
                r.display = expanded

    def action_move(self, direction: int) -> None:
        rows, focused = self.rows, self.screen.focused
        if focused not in rows:
            raise SkipAction()
        rows[(rows.index(focused) + direction) % len(rows)].focus()

    def action_more(self) -> None:
        focused = self.screen.focused
        if not isinstance(focused, FlowRow):
            raise SkipAction()
        self.post_message(self.Act(self, focused.kind, focused.ident, "more", (focused.region.x, focused.region.bottom)))

    def open_menu(self, content: MenuContent, at: tuple[int, int]) -> None:
        """Opens on the menu's own queue: opening waits for a refresh, which the caller's handler would hold up."""
        menu = self.query_one(RowMenu)
        menu.menus[0].content = content
        menu.call_later(menu.open_at, *at)

    def action_fold(self, expand: bool) -> None:
        focused = self.screen.focused
        if not isinstance(focused, FlowRow):
            raise SkipAction()
        if focused.kind == "stage":
            self.set_expanded(focused, expand)
        elif not expand:
            stage = self.flow.stage_of(focused.ident).name
            next(r for r in self.query(FlowRow) if r.kind == "stage" and r.ident == stage).focus()


class RowMenu(ContextMenu):
    """The context menu of a row; its items are set each time it opens (FlowTree.open_menu)."""

    DEFAULT_CSS = "RowMenu { height: 0; }"

    def __init__(self) -> None:
        super().__init__(MenuContent())
