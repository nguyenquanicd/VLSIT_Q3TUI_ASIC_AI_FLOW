"""Main: the step in view — a header with its state and main actions, one tab per output, its questions and
its log (spec/tui.md "Main")."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.message import Message
from textual.widgets import Static

from q3tui.engine import Engine
from q3tui.engine.events import read_events
from q3tui.flowdef import Problem
from q3tui.tui.labels import state_content
from q3tui.tui.ui.alert import Alert, AlertDescription, AlertTitle
from q3tui.tui.ui.button import Button
from q3tui.tui.ui.empty import Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle
from q3tui.tui.ui.item import Item, ItemContent, ItemDescription, ItemGroup, ItemMedia, ItemTitle
from q3tui.tui.ui.resizable import ResizableHandle, ResizablePanel, ResizablePanelGroup
from q3tui.tui.ui.tabs import Tabs, TabsContent, TabsList, TabsTrigger
from q3tui.tui.views import View, build_views
from q3tui.tui.widgets.activities import line
from q3tui.tui.widgets.markdown import Q3Markdown

# display state -> the buttons of the step's main actions: (label, action, key)
BUTTONS: dict[str, list[tuple[str, str, str | None]]] = {
    "approval waiting": [("Approve", "approve", "a"), ("Change", "change", "r")],
    "question waiting": [("Answer", "answer", "q")],
    "stale": [("Run", "run_to", "t")],
    "pending": [("Run", "run_to", "t")],
    "failed": [("Run", "run_to", "t"), ("Log", "log", None)],
    "missing_input": [("Run", "run_to", "t"), ("Log", "log", None)],
    "approved": [("Change", "change", "r")],
    "done": [("Change", "change", "r")],
    "running": [],
}
# an item's state (its review status, or the `state` of a table view) -> its icon and colour class
ITEM_STATE: dict[str, tuple[str, str]] = {
    "confirmed": ("done", "ok"), "ok": ("done", "ok"), "not_reviewed": ("step_pending", "warn"),
    "change_requested": ("warning", "warn"), "warn": ("warning", "warn"), "error": ("error", "error"),
    "todo": ("step_pending", "plain"),
}


class ItemList(ItemGroup):
    """A list of a view tab (the Item component): Up / Down move, the focused row is the chosen one; without the
    focus the chosen row stays marked on a fainter background."""

    DEFAULT_CSS = """
    ItemList { height: auto; }
    ItemList Item { padding: 0 1; }
    ItemList Item.-chosen { background: $surface; }
    ItemList Item:focus { background: $panel; }
    ItemList Item.-tone-ok ItemMedia { color: $text-success; }
    ItemList Item.-tone-warn ItemMedia { color: $text-warning; }
    ItemList Item.-tone-error ItemMedia { color: $text-error; }
    """

    def choose(self, item: Item) -> None:
        for row in self.query(Item):
            row.set_class(row is item, "-chosen")

    @property
    def chosen(self) -> Item | None:
        rows = self.query("Item.-chosen")
        return rows.first() if rows else None


def _scroll(*children) -> VerticalScroll:
    """A scrolling box that is not a stop of the focus itself: its rows are."""
    box = VerticalScroll(*children)
    box.can_focus = False
    return box


class StepMain(Vertical):
    """`show(step)` puts a step in view; `refresh_step()` redraws it after an event."""

    DEFAULT_CSS = """
    StepMain { height: 1fr; }
    StepMain #main-header { height: 1; }
    StepMain #main-title { width: 1fr; text-wrap: nowrap; text-overflow: ellipsis; }
    StepMain #main-header Button { margin-left: 1; }
    StepMain Tabs { height: 1fr; }
    StepMain TabsContent { height: 1fr; margin-top: 0; }
    StepMain .view-detail { padding: 0 1; }
    StepMain .missing { color: $text-muted; padding: 1; }
    StepMain #main-errors { height: 1fr; }
    StepMain #main-errors Alert { margin-bottom: 1; }
    """

    class Do(Message):
        """An action on the step in view: approve, change, answer, run_to, log, review, …"""

        def __init__(self, action: str, step: str, item: tuple[str, str] | None = None) -> None:
            super().__init__()
            self.action, self.step, self.item = action, step, item

    def __init__(self, engine: Engine | None, problems: list[Problem] | None = None, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.engine = engine
        self.problems = problems or []
        self.step: str | None = None
        self.tab: str | None = None
        self.views: list[View] = []

    # -- composing ----------------------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        if self.problems:
            with VerticalScroll(id="main-errors"):
                for p in self.problems:
                    yield Alert(AlertTitle(p.message), AlertDescription(p.file), variant="destructive")
            return
        if self.engine is None or self.step is None:
            yield Empty(EmptyHeader(EmptyMedia("flow"), EmptyTitle("No step in view"),
                                    EmptyDescription("Pick a step in the Flow tab.")))
            return
        st = self.engine.status(self.step)
        with Horizontal(id="main-header"):
            yield Static(Content.assemble((self.step, "bold"), (f" · stage {st.stage}   ", "dim"), state_content(st)),
                         id="main-title")
            for label, action, key in BUTTONS[st.display]:
                yield Button(f"{label} {key}" if key else label, id=f"do-{action}")
        self.views = build_views(self.engine, self.step)
        questions = self.engine.decisions.of_step(self.step)
        triggers = [TabsTrigger(v.title, f"view-{v.artifact}") for v in self.views]
        if questions:
            open_n = sum(q.status == "open" for q in questions)
            triggers.append(TabsTrigger(f"Questions {open_n}" if open_n else "Questions", "questions"))
        triggers.append(TabsTrigger("Log", "log"))
        values = [t.value for t in triggers]
        with Tabs(TabsList(*triggers), value=self.tab if self.tab in values else values[0], id="main-tabs"):
            for v in self.views:
                yield TabsContent(f"view-{v.artifact}", *self._view(v))
            if questions:
                yield TabsContent("questions", *self._questions(questions))
            yield TabsContent("log", self._log())

    def _view(self, v: View):
        if v.missing:
            yield Static(f"`{v.artifact}` is not written yet.", classes="missing", markup=False)
            return
        if v.kind == "document":
            yield VerticalScroll(Q3Markdown(v.text, classes="view-detail"))
            return
        rows = []
        for it in v.items:
            known = ITEM_STATE.get(it.state)  # a mark only when the row has a state (review, or a table's `state`)
            parts = [ItemMedia(known[0])] if known else []
            rows.append(Item(*parts, ItemContent(ItemTitle(it.label)), value=it.id,
                             classes=f"-tone-{known[1] if known else 'plain'}"))
        if rows:
            rows[0].add_class("-chosen")
        first = v.items[0].detail if v.items else ""
        yield ResizablePanelGroup(
            ResizablePanel(_scroll(ItemList(*rows, id=f"list-{v.artifact}")), size=35),
            ResizableHandle(),
            ResizablePanel(VerticalScroll(Q3Markdown(first, classes="view-detail", id=f"detail-{v.artifact}")), size=65),
        )

    def _questions(self, questions):
        order = sorted(questions, key=lambda q: (q.status != "open", q.id))
        rows = []
        for q in order:
            block = " · blocking" if q.blocking and q.status == "open" else ""
            answer = f" → {q.answer}" if q.answer is not None else ""
            glyph, tone = ("step_gate", "warn") if q.status == "open" else ("done", "plain")
            rows.append(Item(ItemMedia(glyph), ItemContent(ItemTitle(f"{q.id} · {q.status}{block}"),
                                                           ItemDescription(f"{q.text}{answer}")),
                             value=q.id, classes=f"-tone-{tone}"))
        if rows:
            rows[0].add_class("-chosen")
        yield _scroll(ItemList(*rows, id="list-questions"))

    def _log(self):
        lines = []
        if self.engine is not None and self.step is not None:
            for e in read_events(self.engine.project.events_file):
                if e.get("step") == self.step:
                    item = line(e)
                    if item is not None:
                        lines.append(item)
        return VerticalScroll(*lines[-500:], id="step-log")

    # -- updating -----------------------------------------------------------------------------------

    async def show(self, step: str | None) -> None:
        if step != self.step:
            self.tab = None
        self.step = step
        await self.recompose()

    async def refresh_step(self) -> None:
        tabs = self.query(Tabs)
        if tabs:
            self.tab = tabs.first().value
        await self.recompose()

    def focus_target(self):
        """Where Tab puts the focus in Main: the chosen row of the list in view, else its first focusable widget."""
        tabs = self.query(Tabs)
        if tabs:
            content = next((c for c in self.query(TabsContent) if c.value == tabs.first().value), None)
            lists = content.query(ItemList) if content is not None else []
            if lists:
                group = lists.first()
                return group.chosen or next(iter(group.query(Item)), None)
        return next((w for w in self.query("*") if w.focusable), None)

    def selected_item(self) -> tuple[str, str] | None:
        """(artifact, item) of the selected row of the view tab in view."""
        tabs = self.query(Tabs)
        if not tabs or not tabs.first().value.startswith("view-"):
            return None
        artifact = tabs.first().value[5:]
        lists = self.query(f"#list-{artifact}")
        chosen = lists.first(ItemList).chosen if lists else None
        return (artifact, chosen.value) if chosen is not None else None

    def selected_question(self) -> str | None:
        lists = self.query("#list-questions")
        chosen = lists.first(ItemList).chosen if lists else None
        return chosen.value if chosen is not None else None

    def selected_text(self) -> str:
        sel = self.screen.get_selected_text() if hasattr(self.screen, "get_selected_text") else None
        return sel or ""

    def on_descendant_focus(self, event) -> None:
        """A row that takes the focus is the chosen one; its detail shows."""
        row = event.widget if isinstance(event.widget, Item) else None
        group = row.parent if row is not None else None
        if not isinstance(group, ItemList):
            return
        group.choose(row)
        list_id = group.id or ""
        if list_id == "list-questions" or not list_id.startswith("list-"):
            return
        artifact = list_id[5:]
        view = next((v for v in self.views if v.artifact == artifact), None)
        item = next((i for i in view.items if i.id == row.value), None) if view else None
        details = self.query(f"#detail-{artifact}")
        if item is not None and details:
            details.first(Q3Markdown).update(item.detail)

    @on(Tabs.Changed, "#main-tabs")
    def _tab_changed(self, event: Tabs.Changed) -> None:
        self.app.refresh_keys()

    @on(Item.Selected, "#list-questions Item")
    def _question_chosen(self, event: Item.Selected) -> None:
        event.stop()
        self.post_message(self.Do("answer_one", self.step, ("question", event.value)))

    @on(Button.Pressed)
    def _button(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid.startswith("do-") and self.step:
            event.stop()
            action = bid[3:]
            if action == "log":
                self.query_one("#main-tabs", Tabs).select("log")
                return
            self.post_message(self.Do(action, self.step))
