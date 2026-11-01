"""The TUI (spec/tui.md): it acts only through Ops and shows what the engine's events and state say."""

from __future__ import annotations

from pathlib import Path

from textual import events
from textual.app import App
from textual.binding import Binding

from q3tui.engine.events import Event
from q3tui.runtime.session import Opened, open_project
from q3tui.tui.screens.home import HomeScreen
from q3tui.tui.screens.settings import SettingsScreen
from q3tui.tui.screens.workspace import WorkspaceScreen
from q3tui.tui.themes import VLSIT_DARK
from q3tui.tui.ui.command import CommandDialog, CommandItem
from q3tui.tui.ui.dialog import Dialog, DialogDescription, DialogHeader, DialogTitle
from q3tui.tui.ui.dropdown_menu import DropdownMenu
from q3tui.tui.ui.icons import set_icon_set
from q3tui.tui.ui.menubar import Menubar
from q3tui.tui.ui.toast import toast
from q3tui.tui.widgets.bars import RuntimeStats, StatusBar, TitleBar, menus
from q3tui.tui.widgets.dialogs import (
    CostDialog,
    DefinitionDialog,
    ShortcutsDialog,
    allow,
    confirm,
    download,
)

SHORTCUTS = [
    ("Ctrl+Q", "quit"), ("Ctrl+K", "command palette"), ("Ctrl+R", "run the flow"), ("Ctrl+X", "stop the run"),
    ("Ctrl+N / Ctrl+O", "new project / open project"), ("Alt+,", "settings"), ("F1", "keyboard shortcuts"),
    ("F6 / F7 / F8", "the flow / the model and effort / the cost"), ("Alt+F/R/V/H", "the File / Run / View / Help menu"),
    ("Tab / Shift+Tab", "the next / previous part"), ("Alt+1..9", "the n-th tab of the tabs around the focus"),
    ("t / o / f", "run to / only / from this step"), ("s", "run the stage of this step"), (".", "run this step again"),
    ("a / A", "approve / approve by force"), ("r", "send a change request"), ("q / Q", "answer the next open question / every one with its default"),
    ("c / C", "confirm the selected item / every item"), ("w", "ask for a change to the selected item"),
    ("m", "ask the assistant about the selected item"),
    ("Shift+F10", "the menu of the Flow tree row"),
    ("Enter / Shift+Enter", "chat: send / new line"), ("Esc", "chat: stop the answer"), ("Ctrl+L", "chat: new chat"),
]


class Q3App(App):
    CSS_PATH = "styles/app.tcss"
    TITLE = "Q3TUI"
    # Global keys work everywhere, typing included (spec/tui.md "Rules" 1): a text field would otherwise take Alt+1 as
    # the digit it carries, so every one of them is a priority binding.
    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("ctrl+k", "palette", "Commands", priority=True),
        Binding("ctrl+r", "run", "Run", priority=True),
        Binding("ctrl+x", "stop", "Stop", priority=True),
        Binding("ctrl+n", "new_project", show=False, priority=True),
        Binding("ctrl+o", "open_project", show=False, priority=True),
        Binding("alt+comma", "settings", show=False, priority=True),
        Binding("f1", "shortcuts", show=False, priority=True),
        Binding("f6", "dropdown('flow-menu')", show=False, priority=True),
        Binding("f7", "dropdown('runtime-menu')", show=False, priority=True),
        Binding("f8", "cost_details", show=False, priority=True),
        *(Binding(f"alt+{k}", f"menu('{m}')", show=False, priority=True)
          for k, m in (("f", "file"), ("r", "run"), ("v", "view"), ("h", "help"))),
        *(Binding(f"alt+{n}", f"tab({n})", show=False, priority=True) for n in range(1, 10)),
    ]

    def __init__(self, opened: Opened, *, session: list[str] | None = None, home: Path | None = None) -> None:
        super().__init__()
        self.opened = opened
        self.session_options = list(session or [])
        self.home_dir = home
        self._unsubscribe = None
        self.status_text = "idle"
        self._cost_base = self._project_cost()  # what the project had spent when Q3TUI started (or opened it)
        self._cost_before = 0.0  # spent in this session in the projects opened before this one

    # -- start --------------------------------------------------------------------------------------

    async def on_event(self, event: events.Event) -> None:
        """A paste gives the app its focus back, as a key does: a terminal's paste dialog takes
        the focus, and the paste comes before the terminal says the focus is back
        (spec/tui.md "Input boxes")."""
        if isinstance(event, events.Paste) and not event.is_forwarded and not self.app_focus:
            self.app_focus = True
        if isinstance(event, events.MouseDown) and not event.is_forwarded:
            # Main rebuilds while a step runs: a press on a widget removed since the last frame is
            # dropped (Textual's text selection would read its missing parent)
            widget, _ = self.screen.get_widget_and_offset_at(event.x, event.y)
            if widget is not None and widget.parent is None and widget is not self.screen:
                return
        await super().on_event(event)

    def on_mount(self) -> None:
        from q3tui.tui.scrollbars import install

        install()
        self.register_theme(VLSIT_DARK)
        self.theme = VLSIT_DARK.name
        self._attach()
        self.push_screen(WorkspaceScreen(self.bars) if self.opened.has_run else HomeScreen(self.bars))
        for w in self.opened.warnings:
            self.toast(str(getattr(w, "message", w)), variant="warning")
        if self.opened.engine is not None:
            changed = self.opened.engine.check_definitions()
            if changed:
                self.push_screen(DefinitionDialog(changed), lambda c: self._definition_answer(changed, c))

    def _attach(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
        set_icon_set(self.opened.config.config.tui.icons)
        if self.opened.ops is not None:
            self._unsubscribe = self.opened.ops.subscribe(self._event)

    def _project_cost(self) -> float:
        if self.opened.ops is None:
            return 0.0
        cost = self.opened.ops.cost()
        return cost["total_usd"] + cost.get("assistant_usd", 0.0)

    def costs(self) -> dict[str, float]:
        """session: spent since Q3TUI started (steps and assistant); project: until the cost is reset."""
        project = self._project_cost()
        if project < self._cost_base:  # the cost was reset meanwhile
            self._cost_base = 0.0
        return {"session": self._cost_before + project - self._cost_base, "project": project}

    def bars(self) -> tuple[TitleBar, StatusBar]:
        o = self.opened
        cfg = o.config.config
        stats = RuntimeStats(o.flow.name or cfg.pipeline.flow, o.lookup.flows() or [cfg.pipeline.flow], cfg.llm.model,
                             cfg.llm.effort, self.costs())
        shown = self.screen.has_class("-assistant") if isinstance(self.screen, SettingsScreen) else None
        title = TitleBar(menus(gate=cfg.pipeline.gate_mode, assistant=shown), stats)
        status = StatusBar(str(o.project.root), self.status_text)
        return title, status

    # -- the bars -----------------------------------------------------------------------------------

    def refresh_keys(self) -> None:
        from q3tui.tui.keyhints import focus_label, hints

        screen = self.screen
        for bar in screen.query(StatusBar):
            bar.set_focus(focus_label(screen, screen.focused))
            bar.set_keys(hints(screen, screen.focused))

    def set_status(self, text: str) -> None:
        self.status_text = text
        for bar in self.screen.query(StatusBar):
            bar.set_status(text)

    def refresh_cost(self) -> None:
        if self.opened.ops is None:
            return
        costs = self.costs()
        for stats in self.screen.query(RuntimeStats):
            stats.update(costs=costs, model=self.opened.config.config.llm.model,
                         effort=self.opened.config.config.llm.effort)

    def toast(self, title: str, description: str = "", *, variant: str = "default") -> None:
        variant = {"error": "destructive"}.get(variant, variant)
        self.call_later(toast, self.screen, title, description, variant=variant)
        if self.opened.ops is not None:
            kind = "warning" if variant in ("warning", "destructive") else "log"
            self.opened.engine.bus.emit(kind, message=title + (f": {description}" if description else ""))

    # -- engine events ------------------------------------------------------------------------------

    def _event(self, event: Event) -> None:
        self.call_later(self._deliver, event.to_dict())

    async def _deliver(self, e: dict) -> None:
        for screen in self.screen_stack:
            if isinstance(screen, WorkspaceScreen):
                await screen.on_engine_event(e)
        kind = e.get("kind")
        if kind == "run_started":
            self.set_status("running")
        elif kind == "run_finished":
            outs = ", ".join(f"{s} {o}" for s, o in (e.get("outcomes") or {}).items())
            outcomes = set((e.get("outcomes") or {}).values())
            self.set_status("failed" if "failed" in outcomes else "waiting for you" if "waiting" in outcomes else "idle")
            self.call_later(toast, self.screen, "Run finished", outs)
            self.refresh_cost()
        elif kind == "step_finished" and e.get("result") == "failed":
            self.call_later(toast, self.screen, f"{e.get('step')} failed", str(e.get("error") or "")[:200],
                            variant="destructive")
        elif kind == "approval_waiting":
            self.call_later(toast, self.screen, f"{e.get('step')} is waiting for approval", "Approve it from Main (a).",
                            variant="warning")
        elif kind in ("task_finished", "step_finished"):
            self.refresh_cost()

    # -- running ------------------------------------------------------------------------------------

    def start_run(self, **scope) -> None:
        ops = self.opened.ops
        if ops is None:
            self.toast("The flow has errors", variant="error")
            return
        if ops.is_running:
            self.toast("A run is going on", variant="warning")
            return
        if not isinstance(self.screen, WorkspaceScreen):
            self.switch_screen(WorkspaceScreen(self.bars))

        async def go():
            try:
                await ops.run(**scope)
            except Exception as exc:  # noqa: BLE001 -- refused runs become a toast
                self.toast(str(exc), variant="warning")

        self.run_worker(go(), exclusive=False, group="run")

    def action_run(self) -> None:
        self.start_run()

    def action_stop(self) -> None:
        if self.opened.ops is not None and self.opened.ops.is_running:
            self.opened.ops.stop()
            self.set_status("stopping")
            self.toast("Stopping the run")

    # -- screens ------------------------------------------------------------------------------------

    def action_settings(self, group: str | None = None) -> None:
        self.push_screen(SettingsScreen(self.bars, group))

    def action_shortcuts(self) -> None:
        self.push_screen(ShortcutsDialog(SHORTCUTS))

    def action_new_project(self) -> None:
        self.push_screen(_FolderDialog("New project: the folder"), lambda p: p and self.reopen(Path(p), create=True))

    def action_open_project(self) -> None:
        self.push_screen(_FolderDialog("Open project: the folder"), lambda p: p and self.reopen(Path(p)))

    def reopen(self, folder: Path, *, create: bool = False, flow: str | None = None) -> None:
        if create:
            folder.mkdir(parents=True, exist_ok=True)
        spent = self.costs()["session"]
        try:
            self.opened = open_project(folder, session=self.session_options, home=self.home_dir, flow=flow)
        except Exception as exc:  # noqa: BLE001
            self.toast(str(exc), variant="error")
            return
        self._cost_before, self._cost_base = spent, self._project_cost()
        self._attach()
        while len(self.screen_stack) > 2:
            self.pop_screen()
        self.switch_screen(WorkspaceScreen(self.bars) if self.opened.has_run else HomeScreen(self.bars))

    def write_user_file(self, rel: str, text: str) -> None:
        path = self.opened.project.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text.rstrip() + "\n")
        self.switch_screen(WorkspaceScreen(self.bars))
        self.call_after_refresh(self.toast, f"Wrote {rel}", "Ctrl+R runs the flow.", variant="success")

    def after_settings(self) -> None:
        set_icon_set(self.opened.config.config.tui.icons)
        if self.opened.engine is not None:
            self.opened.engine.tool_env.ensure(self.opened.config.config)
        self.refresh_cost()

    def action_tab(self, n: int) -> None:
        """Alt+<n>: the n-th tab of the tab component around the focus (the sidebar, Main, the Settings)."""
        from q3tui.tui.ui.tabs import Tabs

        focused = self.screen.focused
        tabs = next((a for a in focused.ancestors_with_self if isinstance(a, Tabs)), None) if focused else None
        if tabs is None:
            return
        enabled = [t for t in tabs.triggers if not t.disabled]
        if not 1 <= n <= len(enabled):
            return
        tabs.select(enabled[n - 1].value)
        screen = self.screen
        if tabs.id == "main-tabs" and isinstance(screen, WorkspaceScreen):
            self.call_after_refresh(lambda: (t := screen.main.focus_target()) and t.focus())
        elif tabs.id == "layer-tabs" and isinstance(screen, SettingsScreen):
            self.set_timer(0.15, screen.focus_main)

    async def action_menu(self, name: str) -> None:
        bars = self.screen.query(Menubar)
        if bars:
            await bars.first().open_menu(name)

    async def action_dropdown(self, menu_id: str) -> None:
        menus_ = self.screen.query(f"#{menu_id}")
        if menus_:
            await menus_.first(DropdownMenu).open()

    def action_cost_details(self) -> None:
        if self.opened.ops is None:
            return
        def chosen(value) -> None:
            if value == "reset":
                self.push_screen(confirm("Reset the cost?", "The totals go back to 0; the reset is kept as an audit "
                                         "entry."), lambda ok: ok and self.menu_value("reset-cost"))

        self.push_screen(CostDialog(self.opened.ops.cost(), self.costs()["session"]), chosen)

    # -- menus, palette and dropdowns -------------------------------------------------------------

    def palette_items(self) -> list:
        ops = self.opened.ops
        items = [
            CommandItem("Run flow", "run", "ctrl+r"), CommandItem("Stop", "stop", "ctrl+x"),
            CommandItem("Settings", "settings", "alt+comma"), CommandItem("Apply a tools preset", "apply-preset"),
            CommandItem("New project", "new-project", "ctrl+n"), CommandItem("Open project", "open-project", "ctrl+o"),
            CommandItem("Import…", "import"), CommandItem("Run changed steps again", "rerun-changed"),
            *(CommandItem(f"Gate mode: {g}", f"gate-{g}") for g in ("manual", "auto", "unattended")),
            *(CommandItem(f"Icons: {s}", f"icons-{s}") for s in ("nerd", "unicode")),
            CommandItem("Cost", "cost"), CommandItem("Keyboard shortcuts", "shortcuts", "f1"),
            CommandItem("Quit", "quit", "ctrl+q"),
        ]
        if ops is not None:
            items += [CommandItem(f"Action: {a.name}", f"action:{a.name}", description=a.doc) for a in ops.actions()]
        return items

    def action_palette(self) -> None:
        self.push_screen(CommandDialog(*self.palette_items()), self.menu_value)

    def on_menubar_selected(self, event: Menubar.Selected) -> None:
        self.menu_value(event.value)

    def on_menu_root_selected(self, event) -> None:
        value = getattr(event, "value", None)
        if value:
            self.menu_value(value)

    def menu_value(self, value: str | None) -> None:
        if not value:
            return
        ops = self.opened.ops
        try:
            if value == "run":
                self.start_run()
            elif value == "stop":
                self.action_stop()
            elif value == "settings":
                self.action_settings()
            elif value == "quit":
                self.exit()
            elif value == "new-project":
                self.action_new_project()
            elif value == "open-project":
                self.action_open_project()
            elif value == "shortcuts":
                self.action_shortcuts()
            elif value == "about":
                self.push_screen(Dialog(DialogHeader(DialogTitle("Q3TUI"),
                                                     DialogDescription("Chip design flows on the Claude Agent SDK."))))
            elif value == "cost":
                self.action_cost_details()
            elif value == "reset-cost" and ops:
                ops.reset_cost()
                self.refresh_cost()
            elif value == "import":
                self.push_screen(_FolderDialog("Import: files or folders (space between)"), self._import)
            elif value == "rerun-changed" and ops:
                steps = [c["step"] for c in ops.engine.definition_changes()] or \
                    [s for s in ops.engine.flow.order() if ops.status(s).definition_changed]
                if steps:
                    self.start_run(rerun=steps)
            elif value.startswith("gate-") and value.count(":") == 0:
                self._session("pipeline.gate_mode", value[5:])
            elif value.startswith("gate-step:") and ops:
                _, sid, mode = value.split(":")
                ops.gate_mode(mode, sid)
            elif value.startswith("gate-stage:") and ops:
                _, stage, mode = value.split(":")
                for sid in next(s for s in ops.engine.flow.stages if s.name == stage).steps:
                    ops.gate_mode(mode, sid)
            elif value.startswith("icons-"):
                self._session("tui.icons", value[6:])
                self.switch_screen(type(self.screen)(self.bars))
            elif value == "view-assistant" and isinstance(self.screen, SettingsScreen):
                self.screen.action_toggle_assistant()
            elif value.startswith("model-"):
                self._session("llm.model", value[6:])
            elif value.startswith("effort-"):
                self._session("llm.effort", value[7:])
            elif value.startswith("flow-"):
                self.session_options = [o for o in self.session_options if not o.startswith("pipeline.flow=")]
                self.session_options.append(f"pipeline.flow={value[5:]}")
                self.reopen(self.opened.project.root, flow=value[5:])
            elif value.startswith("step:"):
                _, sid, action = value.split(":")
                if isinstance(self.screen, WorkspaceScreen):
                    self.screen.do(action, sid)
            elif value.startswith("action:") and ops:
                self.toast(ops.call_action(value[7:]))
            elif value == "apply-preset":
                self.action_settings("tools")
            elif value.startswith("preset:") and ops:
                keys = ops.apply_preset(value[7:])
                self.toast(f"Preset {value[7:]} applied", f"{len(keys)} key(s) written to the user config")
                self.after_settings()
        except Exception as exc:  # noqa: BLE001
            self.toast(str(exc), variant="warning")

    def _session(self, key: str, value) -> None:
        if self.opened.ops is None:
            self.opened.config.session_set(key, value)
        else:
            self.opened.ops.settings(key, value)
        self.after_settings()

    def _import(self, text: str | None) -> None:
        if not text or self.opened.ops is None:
            return
        table = self.opened.ops.import_files([Path(p).expanduser() for p in text.split()])
        taken = [f"{Path(f).name} → {s}" for f, s in table.items() if s]
        left = [Path(f).name for f, s in table.items() if not s]
        self.toast(f"Imported {len(taken)} file(s)", "; ".join(taken[:5]) + (f"; nobody took: {', '.join(left[:5])}"
                                                                             if left else ""))

    # -- alerts, approvals, definitions -------------------------------------------------------------

    def alert_action(self, payload: str) -> None:
        kind, _, arg = payload.partition(":")
        ops = self.opened.ops
        if kind == "settings":
            self.action_settings(arg or None)
        elif kind in ("install", "update") and ops is not None:
            src = ops._package_source(arg)
            work = ops.install_package if kind == "install" else ops.update_package
            done = "installed" if kind == "install" else "updated"
            self.push_screen(download(arg, src), lambda ok: ok and self._in_background(
                f"{arg}: downloading…", lambda: work(arg), f"{arg} {done}"))
        elif kind == "fetch" and ops is not None:
            self.push_screen(download(arg, {}), lambda ok: ok and self._in_background(
                f"{arg}: fetching…", lambda: ops.fetch_site(arg), f"{arg} fetched"))
        elif kind == "allow-setup" and ops is not None:
            cmd = self.opened.config.config.tools.setup_script or ""

            def allowed(ok: bool) -> None:
                if ok:
                    ops.allow("command", cmd)
                    self.call_later(self.refresh_view)

            self.push_screen(allow("a setup script", cmd), allowed)

    def _in_background(self, starting: str, work, finished: str) -> None:
        """Download or fetch off the UI thread, then show what changed (the alerts, the states)."""
        self.toast(starting)

        async def run() -> None:
            import asyncio

            try:
                await asyncio.to_thread(work)
                self.toast(finished, variant="success")
            except Exception as exc:  # noqa: BLE001 -- a failed download is told, the screen stays
                self.toast(str(exc), variant="error")
            await self.refresh_view()

        self.run_worker(run(), exclusive=False)

    async def refresh_view(self) -> None:
        """After something changed outside a run (a package, a site, a setting): redraw what depends on it."""
        if self.opened.engine is not None:
            self.opened.engine.tool_env.ensure(self.opened.config.config)
        screen = self.screen
        if isinstance(screen, HomeScreen):
            await screen.refresh_alerts()
        elif isinstance(screen, WorkspaceScreen):
            screen.refresh_statuses()
            await screen.main.refresh_step()

    def _definition_answer(self, changed: list[dict], choice: str | None) -> None:
        ops = self.opened.ops
        steps = [c["step"] for c in changed]
        if choice == "rerun":
            self.start_run(rerun=steps)
        elif ops is not None:
            ops.definition_answer(steps, "later")


class _FolderDialog(Dialog):
    def __init__(self, title: str) -> None:
        from q3tui.tui.ui.input import Input

        self.input = Input(placeholder="a path; Enter", id="folder")
        super().__init__(DialogHeader(DialogTitle(title)), self.input, initial_focus="#folder", width=72)

    def on_input_submitted(self, event) -> None:
        event.stop()
        self.dismiss(event.value.strip() or None)
