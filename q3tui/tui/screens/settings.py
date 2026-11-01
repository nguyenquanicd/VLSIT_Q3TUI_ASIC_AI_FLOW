"""Settings: the Assistant in the sidebar; the keys of the config in three tabs, Session · Project · User
(spec/tui.md "Settings")."""

from __future__ import annotations

import json
import typing
from dataclasses import dataclass

from pydantic import BaseModel
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.screen import Screen
from textual.widgets import Static

from q3tui.config import ConfigError
from q3tui.config.schema import Config
from q3tui.tui.ui.button import Button
from q3tui.tui.ui.command import CommandDialog, CommandItem
from q3tui.tui.ui.input import Input
from q3tui.tui.ui.resizable import ResizableHandle, ResizablePanel, ResizablePanelGroup
from q3tui.tui.ui.select import Select, SelectItem
from q3tui.tui.ui.tabs import Tabs, TabsContent, TabsList, TabsTrigger
from q3tui.tui.widgets.chat import ChatPanel

GROUPS = [("LLM", "llm"), ("Pipeline", "pipeline"), ("Tools", "tools"), ("PDKs", "pdks"), ("FPGAs", "fpgas"),
          ("MCP servers", "mcp_servers"), ("TUI", "tui")]
LAYERS = ("session", "project", "user")


@dataclass
class Key:
    dotted: str
    kind: str  # bool | choice | text | map
    choices: tuple = ()
    doc: str = ""


def keys_of(model: type[BaseModel], prefix: str) -> list[Key]:
    out = []
    for name, f in model.model_fields.items():
        dotted = f"{prefix}.{name}"
        ann = f.annotation
        args = [a for a in typing.get_args(ann) if a is not type(None)] or [ann]
        base = args[0]
        origin = typing.get_origin(base)
        if isinstance(base, type) and issubclass(base, BaseModel):
            out += keys_of(base, dotted)
        elif base is bool:
            out.append(Key(dotted, "bool", doc=f.description or ""))
        elif origin is typing.Literal:
            out.append(Key(dotted, "choice", typing.get_args(base), f.description or ""))
        elif origin in (dict, list):
            out.append(Key(dotted, "map", doc=f.description or ""))
        else:
            out.append(Key(dotted, "text", doc=f.description or ""))
    return out


def group_keys(section: str) -> list[Key]:
    f = Config.model_fields[section]
    base = f.annotation
    if typing.get_origin(base) is dict:
        return [Key(section, "map")]
    return keys_of(base, section)


def get(data: dict, dotted: str):
    node = data
    for p in dotted.split("."):
        if not isinstance(node, dict) or p not in node:
            return None
        node = node[p]
    return node


def show(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, (dict, list)):
        return json.dumps(value) if value else "—"
    return str(value)


class SettingRow(Vertical):
    DEFAULT_CSS = """
    SettingRow { height: auto; padding: 0 1; margin-bottom: 1; }
    SettingRow .row-head { height: 1; }
    SettingRow .row-key { width: 1fr; text-style: bold; }
    SettingRow .row-source { width: auto; color: $text-muted; }
    SettingRow .row-edit { height: auto; }
    SettingRow .row-edit Input, SettingRow .row-edit Select { width: 1fr; }
    SettingRow .row-edit Button { margin-left: 1; }
    """

    def __init__(self, key: Key, layer: str) -> None:
        super().__init__()
        self.key, self.config_layer = key, layer

    def compose(self) -> ComposeResult:
        cfg = self.app.opened.config
        effective = get(cfg.config.model_dump(mode="json"), self.key.dotted)
        source = cfg.source(self.key.dotted)
        here = cfg.layer_value(self.config_layer, self.key.dotted)
        with Horizontal(classes="row-head"):
            yield Static(self.key.dotted, classes="row-key", markup=False)
            yield Static(Content.assemble((show(effective), ""), ("  from ", "dim"), (source, "$accent")),
                         classes="row-source")
        with Horizontal(classes="row-edit"):
            if self.key.kind == "choice" or self.key.kind == "bool":
                choices = ("true", "false") if self.key.kind == "bool" else tuple(str(c) for c in self.key.choices)
                yield Select(*(SelectItem(c, c) for c in choices),
                             value=None if here is None else str(here).lower() if self.key.kind == "bool" else str(here),
                             placeholder=f"(not set in {self.config_layer})", id="value")
            else:
                yield Input(value="" if here is None else (json.dumps(here) if isinstance(here, (dict, list)) else str(here)),
                            placeholder=f"(not set in {self.config_layer}; Enter saves)", id="value")
            yield Button("Reset", id="reset")
            if self.config_layer == "session" and here is not None:
                yield Button("Save to Project", id="save-project")
                yield Button("Save to User", id="save-user")

    def value(self, raw: str):
        if self.key.kind == "bool":
            return raw == "true"
        if raw == "":
            return None
        try:
            return json.loads(raw) if self.key.kind in ("map", "text") and raw[:1] in "[{0123456789-tfn\"" else raw
        except ValueError:
            return raw

    def save(self, raw: str, layer: str | None = None) -> None:
        screen = self.screen
        try:
            self.app.opened.ops.settings(self.key.dotted, self.value(raw), layer=layer or self.config_layer)
            self.app.toast(f"{self.key.dotted} saved to {layer or self.config_layer}")
        except (ConfigError, Exception) as exc:  # noqa: BLE001 -- a bad value is refused, with the reason
            self.app.toast(str(exc), variant="error")
        self.app.after_settings()
        screen.call_later(screen.redraw)

    @on(Input.Submitted, "#value")
    def _submitted(self, event) -> None:
        event.stop()
        self.save(event.value)

    @on(Select.Changed, "#value")
    def _changed(self, event) -> None:
        event.stop()
        if event.value is not None:
            self.save(str(event.value))

    @on(Button.Pressed)
    def _pressed(self, event: Button.Pressed) -> None:
        event.stop()
        bid = event.button.id
        if bid == "reset":
            self.save("")
        elif bid in ("save-project", "save-user"):
            here = self.app.opened.config.layer_value("session", self.key.dotted)
            self.app.opened.ops.settings(self.key.dotted, here, layer=bid[5:])
            self.app.opened.ops.settings(self.key.dotted, None, layer="session")
            self.app.after_settings()
            self.screen.call_later(self.screen.redraw)


class SettingsScreen(Screen):
    DEFAULT_CSS = """
    SettingsScreen #settings-body { margin: 1 0; }
    SettingsScreen #search { margin: 0 1 1 1; }
    SettingsScreen .group-title { text-style: bold; color: $primary; padding: 0 1; margin-top: 1; }
    SettingsScreen #layer-tabs { height: 1fr; }
    SettingsScreen #layer-tabs TabsContent { height: 1fr; margin-top: 0; }
    SettingsScreen .sites { padding: 0 1; height: auto; }
    SettingsScreen .site-row { height: 1; }
    SettingsScreen .site-row Static { width: 1fr; }
    """
    BINDINGS = [Binding("ctrl+f", "search", show=False), Binding("escape", "back", show=False)]

    def __init__(self, bars, group: str | None = None) -> None:
        super().__init__()
        self.bars = bars
        self.group = group
        self.layer_tab = "project"
        self.filter = ""

    def compose(self) -> ComposeResult:
        title, status = self.bars()
        yield title
        opened = self.app.opened
        yield ResizablePanelGroup(
            ResizablePanel(ChatPanel(opened.ops, lambda: {"screen": "settings"}, id="chat"), size=30),
            ResizableHandle(),
            ResizablePanel(Vertical(Input(placeholder="Search keys (Ctrl+F)", id="search"),
                                    Tabs(TabsList(*(TabsTrigger(x.title(), x) for x in LAYERS)),
                                         *(TabsContent(x, VerticalScroll(*self.rows(x), id=f"rows-{x}")) for x in LAYERS),
                                         value=self.layer_tab, id="layer-tabs")), size=70),
            id="settings-body")
        yield status

    def rows(self, layer: str):
        for title, section in GROUPS:
            keys = [k for k in group_keys(section) if self.filter in k.dotted.lower() or self.filter in k.doc.lower()]
            if not keys:
                continue
            yield Static(title, classes="group-title", id=f"group-{section}-{layer}")
            if section == "tools":
                yield Horizontal(Button("Apply preset ▾", id="apply-preset"), classes="sites")
            for k in keys:
                yield SettingRow(k, layer)
        if not self.filter or "site" in self.filter or "package" in self.filter:
            yield Static("Sites & packages", classes="group-title")
            yield Vertical(*self.site_rows(), classes="sites")

    def site_rows(self):
        opened = self.app.opened
        if opened.engine is None:
            return
        from q3tui.engine.needs import find_package, installed_ref

        seen = set()
        for inst in opened.flow.instances.values():
            for pk in inst.packages:
                if pk["name"] in seen:
                    continue
                seen.add(pk["name"])
                folder = find_package(pk["name"], opened.lookup)
                have = installed_ref(pk["name"], opened.lookup)
                want = (pk.get("source") or {}).get("ref")
                state = "not installed" if folder is None else f"at {have}" if have else "linked"
                action = "Install" if folder is None else "Update" if have and want and str(have) != str(want) else None
                row = [Static(f"{pk['name']}: {state} (the steps need {want})", markup=False)]
                if action:
                    row.append(Button(action, id=f"pkg-{action.lower()}-{pk['name']}"))
                yield Horizontal(*row, classes="site-row")

    async def redraw(self) -> None:
        tabs = self.query(Tabs)
        if tabs:
            self.layer_tab = tabs.first().value
        await self.recompose()

    def on_mount(self) -> None:
        self.app.refresh_keys()
        if self.group:
            self.call_after_refresh(self._scroll_to_group)

    def on_descendant_focus(self) -> None:
        self.app.refresh_keys()

    def _scroll_to_group(self) -> None:
        hits = self.query(f"#group-{self.group}-{self.layer_tab}")
        if hits:
            hits.first().scroll_visible(top=True, animate=False)

    def action_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_back(self) -> None:
        self.app.pop_screen()

    @on(Input.Submitted, "#search")
    async def _search(self, event) -> None:
        self.filter = event.value.strip().lower()
        await self.redraw()

    @on(Button.Pressed, "#apply-preset")
    def _preset(self, event) -> None:
        event.stop()
        names = set()
        for root in self.app.opened.lookup.roots:
            names |= {p.stem for p in (root / "templates/tools").glob("*.yaml")}
        if not names:
            self.app.toast("No preset found (templates/tools/*.yaml)", variant="warning")
            return
        self.app.push_screen(CommandDialog(*(CommandItem(n, f"preset:{n}") for n in sorted(names))), self.app.menu_value)

    @on(Button.Pressed)
    def _package(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid.startswith("pkg-"):
            event.stop()
            _, action, name = bid.split("-", 2)
            self.app.alert_action(f"{'install' if action == 'install' else 'update'}:{name}")
