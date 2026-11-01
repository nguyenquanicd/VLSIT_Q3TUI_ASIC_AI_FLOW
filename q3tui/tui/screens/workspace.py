"""The Workspace: the sidebar (Assistant | Flow), Main, and Activities under it (spec/tui.md "Workspace")."""

from __future__ import annotations

import json
import time

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding

from q3tui.tui.screens.base import PartScreen
from q3tui.tui.ui.command import CommandDialog, CommandItem
from q3tui.tui.ui.resizable import ResizableHandle, ResizablePanel, ResizablePanelGroup
from q3tui.tui.ui.tabs import Tabs, TabsContent, TabsList, TabsTrigger
from q3tui.tui.widgets.activities import Activities
from q3tui.tui.widgets.chat import ChatPanel
from q3tui.tui.widgets.dialogs import AnswerDialog, ChangeDialog, confirm
from q3tui.tui.widgets.flow_tree import FlowTree
from q3tui.tui.widgets.main import StepMain


class WorkspaceScreen(PartScreen):
    DEFAULT_CSS = """
    WorkspaceScreen #columns { height: 1fr; margin: 1 0; }
    WorkspaceScreen #sidebar-tabs { height: 1fr; }
    WorkspaceScreen #sidebar-tabs TabsContent { height: 1fr; margin-top: 0; }
    """
    BINDINGS = [
        Binding("t", "step('run_to')", show=False), Binding("o", "step('run_only')", show=False),
        Binding("f", "step('run_from')", show=False), Binding("s", "step('run_stage')", show=False),
        Binding("full_stop", "step('rerun')", show=False), Binding("a", "step('approve')", show=False),
        Binding("A", "step('approve_force')", show=False), Binding("r", "step('change')", show=False),
        Binding("q", "step('answer')", show=False), Binding("c", "step('confirm_item')", show=False),
        Binding("C", "step('confirm_all')", show=False), Binding("w", "step('change_item')", show=False),
        Binding("m", "step('ask_item')", show=False),
        Binding("left_square_bracket", "tab(-1)", show=False), Binding("right_square_bracket", "tab(1)", show=False),
        Binding("ctrl+l", "new_chat", show=False),
    ]

    def __init__(self, bars) -> None:
        super().__init__()
        self.bars = bars
        self._last_refresh = 0.0
        self._pending_refresh = False

    # -- layout -------------------------------------------------------------------------------------

    def _sizes(self) -> dict:
        f = self.app.opened.project.tui_dir / "layout.json"
        try:
            return json.loads(f.read_text())
        except (OSError, ValueError):
            return {}

    def compose(self) -> ComposeResult:
        opened = self.app.opened
        sizes = self._sizes()
        title, status = self.bars()
        yield title
        yield ResizablePanelGroup(
            ResizablePanel(
                Tabs(TabsList(TabsTrigger("Assistant", "assistant"), TabsTrigger("Flow", "flow")),
                     TabsContent("assistant", ChatPanel(opened.ops, self.context, id="chat")),
                     TabsContent("flow", FlowTree(opened.flow if opened.flow.stages else None, id="flow-tree")),
                     value="flow", id="sidebar-tabs"),
                size=sizes.get("sidebar", 30), id="sidebar"),
            ResizableHandle(),
            ResizablePanel(
                ResizablePanelGroup(
                    ResizablePanel(StepMain(opened.engine, opened.problems, id="main"), size=sizes.get("main", 70)),
                    ResizableHandle(),
                    ResizablePanel(Activities(id="activities"), size=sizes.get("panel", 30), id="panel"),
                    direction="vertical", id="rows"),
                size=sizes.get("body", 70), id="body"),
            id="columns")
        yield status

    def on_mount(self) -> None:
        self.refresh_statuses()
        super().on_mount()

    def on_descendant_focus(self, event) -> None:
        """The focus and the sidebar tab in view always agree: a focus that lands in the other tab shows it."""
        tabs = self.query_one("#sidebar-tabs", Tabs)
        content = next((a for a in self.focused.ancestors_with_self if isinstance(a, TabsContent)
                        and a.parent is tabs), None) if self.focused is not None else None
        if content is not None and content.value != tabs.value:
            tabs.select(content.value)
        super().on_descendant_focus()

    @on(Tabs.Changed, "#sidebar-tabs")
    def _sidebar_changed(self, event: Tabs.Changed) -> None:
        """Showing the other tab (a click, Alt+1, Alt+2) takes the focus into it."""
        focused = self.focused
        if focused is None or not any(isinstance(a, TabsContent) and a.value == event.value
                                      for a in focused.ancestors_with_self):
            target = self.query_one("#chat-input") if event.value == "assistant" else self.main_part()
            if target is not None:
                def go() -> None:  # after the layout: a widget hidden by the switch drops the focus then
                    if self.focused is not target and target.focusable:
                        target.focus()

                self.call_after_refresh(go)
                self.set_timer(0.1, go)
        self.app.refresh_keys()

    def on_screen_resume(self) -> None:
        """Back from Settings or a dialog: the states may have changed."""
        self.refresh_statuses()

    def main_part(self):
        rows = [r for r in self.tree.rows if r.kind == "step"]
        chosen = next((r for r in rows if r.ident == self.tree.selected), rows[0] if rows else None)
        return chosen

    def parts(self) -> list:
        tabs = self.query_one("#sidebar-tabs", Tabs)
        side = self.query_one(ChatPanel) if tabs.value == "assistant" else self.tree
        return [side, self.main, self.query_one(Activities)]

    def on_unmount(self) -> None:
        self.save_sizes()

    def save_sizes(self) -> None:
        try:
            sizes = {"sidebar": self.query_one("#sidebar", ResizablePanel).size_share,
                     "body": self.query_one("#body", ResizablePanel).size_share,
                     "main": self.query_one("#main").parent.size_share,
                     "panel": self.query_one("#panel", ResizablePanel).size_share}
        except Exception:  # noqa: BLE001 -- not composed yet
            return
        d = self.app.opened.project.tui_dir
        d.mkdir(parents=True, exist_ok=True)
        (d / "layout.json").write_text(json.dumps(sizes))

    # -- what you are looking at --------------------------------------------------------------------

    @property
    def main(self) -> StepMain:
        return self.query_one(StepMain)

    @property
    def tree(self) -> FlowTree:
        return self.query_one(FlowTree)

    def current_step(self) -> str | None:
        return self.tree.focused_step() or self.main.step

    def context(self) -> dict:
        main = self.main
        tabs = main.query(Tabs)
        item = main.selected_item()
        return {"step": main.step, "tab": tabs.first().value if tabs else None,
                "item": f"{item[0]}:{item[1]}" if item else None}

    # -- engine events ------------------------------------------------------------------------------

    def refresh_statuses(self) -> None:
        ops = self.app.opened.ops
        if ops is not None:
            self.tree.update_statuses(ops.statuses())

    async def on_engine_event(self, e: dict) -> None:
        await self.query_one(Activities).write(e)
        now = time.monotonic()
        if now - self._last_refresh > 0.3:
            self._last_refresh = now
            self.refresh_statuses()
            if e.get("step") and e.get("step") == self.main.step and e.get("kind") not in ("task_text", "tool_call"):
                await self.main.refresh_step()
        elif not self._pending_refresh:
            self._pending_refresh = True
            self.set_timer(0.35, self._late_refresh)

    async def _late_refresh(self) -> None:
        self._pending_refresh = False
        self._last_refresh = time.monotonic()
        self.refresh_statuses()
        await self.main.refresh_step()

    # -- the Flow tree and Main ---------------------------------------------------------------------

    @on(FlowTree.Selected)
    async def _selected(self, event: FlowTree.Selected) -> None:
        self.tree.select(event.step)
        await self.main.show(event.step)
        self.app.refresh_keys()

    @on(FlowTree.Act)
    def _row_button(self, event: FlowTree.Act) -> None:
        if event.kind == "stage":
            if event.action == "run":
                self.app.start_run(stage=event.name)
            else:
                self.app.push_screen(CommandDialog(*[CommandItem(f"Gate ▸ {g}", f"gate-stage:{event.name}:{g}")
                                                     for g in ("manual", "auto", "unattended")]), self.app.menu_value)
            return
        if event.action == "run":
            self.app.start_run(to=event.name)
        elif event.action == "rerun":
            self.app.start_run(rerun=[event.name])
        else:
            self.app.push_screen(CommandDialog(*self.step_menu(event.name)), self.app.menu_value)

    def step_menu(self, sid: str) -> list[CommandItem]:
        items = [CommandItem("Run only", f"step:{sid}:run_only"), CommandItem("Run from here", f"step:{sid}:run_from"),
                 CommandItem("Regenerate", f"step:{sid}:regenerate"),
                 CommandItem("Reset (with the steps after it)", f"step:{sid}:reset"),
                 CommandItem("Reset only this step", f"step:{sid}:reset_only")]
        items += [CommandItem(f"Gate ▸ {g}", f"gate-step:{sid}:{g}") for g in ("manual", "auto", "unattended")]
        ops = self.app.opened.ops
        for a in ops.actions() if ops else []:
            if a.step == sid:
                items.append(CommandItem(f"Actions ▸ {a.name}", f"action:{a.name}", description=a.doc))
        return items

    @on(StepMain.Do)
    def _main_do(self, event: StepMain.Do) -> None:
        if event.action == "answer_one" and event.item:
            self.answer(event.item[1])
            return
        self.do(event.action, event.step)

    def action_step(self, action: str) -> None:
        sid = self.current_step()
        if sid is None:
            self.app.toast("Pick a step first (Alt+2)", variant="warning")
            return
        self.do(action, sid)

    def action_tab(self, direction: int) -> None:
        self.main.next_tab(direction)

    def action_new_chat(self) -> None:
        self.query_one(ChatPanel).new_chat()

    def do(self, action: str, sid: str) -> None:
        app, ops = self.app, self.app.opened.ops
        if ops is None:
            app.toast("The flow has errors", variant="error")
            return
        eng = ops.engine
        try:
            if action == "run_to":
                app.start_run(to=sid)
            elif action == "run_only":
                app.start_run(only=sid)
            elif action == "run_from":
                app.start_run(from_=sid)
            elif action == "run_stage":
                app.start_run(stage=eng.flow.stage_of(sid).name)
            elif action == "rerun":
                app.start_run(rerun=[sid])
            elif action == "regenerate":
                app.push_screen(confirm(f"Regenerate {sid}?", "It is written again from scratch (its outputs are "
                                        "backed up first)."), lambda ok: ok and app.start_run(regenerate=[sid]))
            elif action in ("reset", "reset_only"):
                only = action == "reset_only"
                app.push_screen(confirm(f"Reset {sid}{' only' if only else ' and the steps after it'}?",
                                        "The files Q3TUI wrote are deleted (after a backup)."),
                                lambda ok: ok and self._reset(sid, only))
            elif action == "approve":
                ops.approve(sid)
                app.toast(f"{sid} approved", variant="success")
            elif action == "approve_force":
                app.push_screen(confirm(f"Approve {sid} by force?", "Past its blocking questions and the items "
                                        "not reviewed."), lambda ok: ok and self._approve_force(sid))
            elif action == "change":
                app.push_screen(ChangeDialog(sid), lambda text: text and self._change(sid, text))
            elif action == "answer":
                qs = eng.decisions.open_of(sid)
                if not qs:
                    app.toast(f"{sid} has no open question")
                else:
                    self.answer(qs[0].id)
            elif action in ("confirm_item", "change_item", "ask_item", "confirm_all"):
                self._item_action(action, sid)
            self.refresh_statuses()
            self.call_later(self.main.refresh_step)
        except Exception as exc:  # noqa: BLE001 -- refused actions become a toast
            app.toast(str(exc), variant="warning")

    def _reset(self, sid: str, only: bool) -> None:
        done = self.app.opened.ops.reset(sid, only=only)
        self.app.toast(f"Reset: {', '.join(done)}")
        self.refresh_statuses()
        self.call_later(self.main.refresh_step)

    def _approve_force(self, sid: str) -> None:
        self.app.opened.ops.approve(sid, force=True)
        self.refresh_statuses()
        self.call_later(self.main.refresh_step)

    def _change(self, sid: str, text: str, item: tuple[str, str] | None = None) -> None:
        ops = self.app.opened.ops
        if item:
            ops.review(sid, item[0], item[1], confirm=False, text=text)
        else:
            ops.request_change(sid, text)
        self.app.toast(f"Change request sent to {sid}; it is stale now")
        self.refresh_statuses()
        self.call_later(self.main.refresh_step)

    def _item_action(self, action: str, sid: str) -> None:
        ops = self.app.opened.ops
        if action == "confirm_all":
            st = ops.engine.state.step(sid)
            for art, items in st.reviews.items():
                for item in items:
                    ops.review(sid, art, item)
            return
        item = self.main.selected_item()
        if item is None:
            self.app.toast("Select an item in a view tab first", variant="warning")
            return
        if action == "confirm_item":
            ops.review(sid, item[0], item[1])
        elif action == "change_item":
            self.app.push_screen(ChangeDialog(sid, item[1]), lambda text: text and self._change(sid, text, item))
        else:
            chat = self.query_one(ChatPanel)
            self.query_one("#sidebar-tabs", Tabs).select("assistant")
            quote = self.main.selected_text()
            box = chat.query_one("#chat-input")
            box.text = f"About {item[1]} ({item[0]}): " + (f"\"{quote}\" " if quote else "")
            box.focus()

    def answer(self, qid: str) -> None:
        ops = self.app.opened.ops
        q = ops.engine.decisions.get(qid)
        if q is None or q.status != "open":
            self.app.toast(f"{qid} is not open")
            return

        def done(result) -> None:
            if not result:
                return
            try:
                ops.answer(qid, result["answer"], hint=result.get("hint"))
                self.app.toast(f"{qid} answered")
            except Exception as exc:  # noqa: BLE001
                self.app.toast(str(exc), variant="warning")
            self.refresh_statuses()
            self.call_later(self.main.refresh_step)

        self.app.push_screen(AnswerDialog(q), done)
