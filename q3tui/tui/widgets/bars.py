"""The title bar (menus, Flow ▾, Model / effort ▾, cost) and the status bar (status · keys · folder)
(spec/tui.md "Layout", "Buttons")."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.content import Content
from textual.widget import Widget
from textual.widgets import Static

from q3tui.tui.ui.dropdown_menu import DropdownMenu, DropdownMenuTrigger
from q3tui.tui.ui.icons import icon, key_label
from q3tui.tui.ui.menu import MenuContent, MenuLabel, MenuRadioGroup, MenuRadioItem, MenuSeparator
from q3tui.tui.ui.menubar import (
    Menubar,
    MenubarContent,
    MenubarItem,
    MenubarMenu,
    MenubarRadioGroup,
    MenubarRadioItem,
    MenubarSeparator,
    MenubarShortcut,
    MenubarSub,
    MenubarSubContent,
    MenubarSubTrigger,
    MenubarTrigger,
)

MODELS = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
GATES = ("manual", "auto", "unattended")


def menus(*, gate: str | None, icons: str) -> tuple[MenubarMenu, ...]:
    """File · Run · View · Help."""
    return (
        MenubarMenu("file", MenubarTrigger("File"), MenubarContent(
            MenubarItem("New project", "new-project", MenubarShortcut.from_key("ctrl+n")),
            MenubarItem("Open project", "open-project", MenubarShortcut.from_key("ctrl+o")),
            MenubarItem("Import…", "import"),
            MenubarSeparator(),
            MenubarItem("Settings", "settings", MenubarShortcut.from_key("alt+comma"), icon_name="settings"),
            MenubarSeparator(),
            MenubarItem("Quit", "quit", MenubarShortcut.from_key("ctrl+q"), icon_name="quit"),
        )),
        MenubarMenu("run", MenubarTrigger("Run"), MenubarContent(
            MenubarItem("Run flow", "run", MenubarShortcut.from_key("ctrl+r")),
            MenubarItem("Stop", "stop", MenubarShortcut.from_key("ctrl+x")),
            MenubarSub(MenubarSubTrigger("Gate mode", "gate"), MenubarSubContent(MenubarRadioGroup(
                *(MenubarRadioItem(g, f"gate-{g}", close_on_select=True) for g in GATES), value=f"gate-{gate}"))),
            MenubarItem("Run changed steps again", "rerun-changed"),
        )),
        MenubarMenu("view", MenubarTrigger("View"), MenubarContent(
            MenubarSub(MenubarSubTrigger("Icons", "icons"), MenubarSubContent(MenubarRadioGroup(
                *(MenubarRadioItem(s, f"icons-{s}", close_on_select=True) for s in ("nerd", "unicode")),
                value=f"icons-{icons}"))),
            MenubarSub(MenubarSubTrigger("Focus", "focus"), MenubarSubContent(
                *(MenubarItem(name, f"focus-{n}", MenubarShortcut.from_key(f"alt+{n}"))
                  for n, name in enumerate(("Assistant", "Flow", "Main", "Activities"), 1)))),
        )),
        MenubarMenu("help", MenubarTrigger("Help"), MenubarContent(
            MenubarItem("Keyboard shortcuts", "shortcuts", MenubarShortcut.from_key("f1")),
            MenubarItem("About", "about", icon_name="about"),
        )),
    )


class RuntimeStats(Widget):
    """Flow ▾ · Model / effort ▾ · the cost."""

    DEFAULT_CSS = """
    RuntimeStats { layout: horizontal; width: auto; height: 1; }
    RuntimeStats Static { width: auto; padding: 0 1; color: $text-muted; }
    """

    def __init__(self, flow: str, flows: list[str], model: str, effort: str | None, cost: float) -> None:
        super().__init__()
        self.flow, self.flows, self.model, self.effort, self.cost = flow, flows, model, effort, cost

    def compose(self) -> ComposeResult:
        flow_group = MenuRadioGroup(*(MenuRadioItem(f, f"flow-{f}", close_on_select=True) for f in self.flows),
                                    value=f"flow-{self.flow}")
        yield DropdownMenu(DropdownMenuTrigger(self.flow_label(), key="f6", chevron=True, id="choose-flow"),
                           MenuContent(flow_group), value="flow", id="flow-menu")
        models = list(dict.fromkeys([self.model, *MODELS]))
        runtime = MenuContent(
            MenuRadioGroup(MenuLabel("Model"), *(MenuRadioItem(m, f"model-{m}", close_on_select=True) for m in models),
                           value=f"model-{self.model}"),
            MenuSeparator(),
            MenuRadioGroup(MenuLabel("Effort"),
                           *(MenuRadioItem(e.title(), f"effort-{e}", close_on_select=True) for e in EFFORTS),
                           value=f"effort-{self.effort}"),
        )
        yield DropdownMenu(DropdownMenuTrigger(self.model_label(), key="f7", chevron=True, id="choose-runtime"),
                           runtime, value="runtime", id="runtime-menu")
        cost = Static(id="cost")
        self._show_cost(cost)
        yield cost

    def flow_label(self) -> str:
        return f"{icon('flow')} {self.flow}"

    def model_label(self) -> str:
        return f"{icon('model')} {self.model} · {(self.effort or '—').title()}"

    def _show_cost(self, field: Static) -> None:
        field.update(f"{icon('project_cost')} ${self.cost:,.2f}")
        field.tooltip = f"The cost of this project's runs and its assistant: {self.cost:,.4f} USD (click for details)"

    def update(self, *, model: str | None = None, effort: str | None = None, cost: float | None = None) -> None:
        if model is not None:
            self.model = model
        if effort is not None:
            self.effort = effort
        if cost is not None:
            self.cost = cost
        if self.is_mounted:
            self.query_one("#choose-runtime", DropdownMenuTrigger).set_label(self.model_label())
            self._show_cost(self.query_one("#cost", Static))

    def on_click(self, event) -> None:
        if getattr(event.widget, "id", None) == "cost":
            self.app.action_cost_details()


class TitleBar(Widget):
    DEFAULT_CSS = """
    TitleBar { dock: top; layout: horizontal; height: 1; padding: 0 1; background: $surface; }
    TitleBar .title-start { width: auto; height: 1; }
    TitleBar .brand { width: 9; height: 1; text-style: bold; color: $foreground; padding-left: 1; }
    TitleBar Menubar { background: transparent; }
    TitleBar .title-spacer { width: 1fr; }
    """

    def __init__(self, menus: tuple[MenubarMenu, ...], stats: RuntimeStats) -> None:
        super().__init__()
        self.menus, self.stats = menus, stats

    def compose(self) -> ComposeResult:
        with Horizontal(classes="title-start"):
            yield Static("Q3TUI", classes="brand")
            yield Menubar(*self.menus, id="menubar")
        yield Static("", classes="title-spacer")
        yield self.stats


class StatusBar(Widget):
    """status · the keys of the moment · the current folder."""

    DEFAULT_CSS = """
    StatusBar { dock: bottom; height: 1; layout: horizontal; background: $surface; padding: 0 1; }
    StatusBar #status { width: auto; padding-right: 2; }
    StatusBar #keys { width: 1fr; color: $text-muted; text-wrap: nowrap; text-overflow: ellipsis; }
    StatusBar #cwd { width: auto; color: $text-muted; }
    """

    def __init__(self, cwd: str) -> None:
        super().__init__()
        self.cwd = cwd

    def compose(self) -> ComposeResult:
        yield Static("", id="status")
        yield Static("", id="keys")
        yield Static(self.cwd, id="cwd", markup=False)

    def set_status(self, text: str | Content) -> None:
        self.query_one("#status", Static).update(text)

    def set_keys(self, keys: list[tuple[str, str]]) -> None:
        parts: list = []
        for key, what in keys:
            if parts:
                parts.append(("  ", ""))
            parts += [(key_label(key), "bold"), (f" {what}", "")]
        self.query_one("#keys", Static).update(Content.assemble(*parts))
