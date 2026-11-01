"""Settings: the Assistant in the sidebar; the keys of the config in three tabs, Session · Project · User
(spec/tui.md "Settings")."""

from __future__ import annotations

import asyncio
import json
import typing
from dataclasses import dataclass

from pydantic import BaseModel
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.widgets import Static

from q3tui.config import ConfigError
from q3tui.config.schema import Config
from q3tui.tui.screens.base import PartScreen
from q3tui.tui.ui.button import Button
from q3tui.tui.ui.command import CommandDialog, CommandItem
from q3tui.tui.ui.field import Field, FieldDescription, FieldError, FieldLabel
from q3tui.tui.ui.input import Input
from q3tui.tui.ui.resizable import ResizableHandle, ResizablePanel, ResizablePanelGroup
from q3tui.tui.ui.select import Select, SelectItem
from q3tui.tui.ui.skeleton import Skeleton
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
        return [Key(section, "map", doc=f.description or "")]
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


class SettingRow(Field):
    """One key of one layer (the Field component): its name (a click on it focuses the value), the value in effect
    and where it comes from, the value of this layer with its buttons, the key's description, and the error of a
    value refused (the text typed stays, to be fixed)."""

    DEFAULT_CSS = """
    SettingRow { height: auto; margin-bottom: 1; }
    SettingRow .row-head { height: 1; }
    SettingRow .row-key { width: 1fr; }
    SettingRow .row-source { width: auto; color: $text-muted; }
    SettingRow .row-edit { height: auto; }
    SettingRow .row-edit Input, SettingRow .row-edit Select { width: 1fr; }
    SettingRow .row-edit Button { margin-left: 1; }
    """

    def __init__(self, key: Key, layer: str, merged: dict) -> None:
        super().__init__()
        self.key, self.config_layer, self.merged = key, layer, merged
        self.control_id = f"value-{layer}-{key.dotted.replace('.', '-').replace('_', '-')}"

    def compose(self) -> ComposeResult:
        cfg = self.app.opened.config
        effective = get(self.merged, self.key.dotted)
        source = cfg.source(self.key.dotted)
        here = cfg.layer_value(self.config_layer, self.key.dotted)
        with Horizontal(classes="row-head"):
            yield FieldLabel(self.key.dotted, for_=f"#{self.control_id}", classes="row-key")
            yield Static(Content.assemble((show(effective), ""), ("  from ", "dim"), (source, "$accent")),
                         classes="row-source")
        with Horizontal(classes="row-edit"):
            if self.key.kind == "choice" or self.key.kind == "bool":
                choices = ("true", "false") if self.key.kind == "bool" else tuple(str(c) for c in self.key.choices)
                yield Select(*(SelectItem(c, c) for c in choices),
                             value=None if here is None else str(here).lower() if self.key.kind == "bool" else str(here),
                             placeholder=f"(not set in {self.config_layer})", id=self.control_id, classes="value")
            else:
                yield Input(value="" if here is None else (json.dumps(here) if isinstance(here, (dict, list)) else str(here)),
                            placeholder=f"(not set in {self.config_layer}; Enter saves)", id=self.control_id,
                            classes="value")
            yield Button("Reset", id="reset")
            if self.config_layer == "session" and here is not None:
                yield Button("Save to Project", id="save-project")
                yield Button("Save to User", id="save-user")
        if self.key.doc:
            yield FieldDescription(self.key.doc)
        yield FieldError()

    def value(self, raw: str):
        if self.key.kind == "bool":
            return raw == "true"
        if raw == "":
            return None
        try:
            return json.loads(raw) if self.key.kind in ("map", "text") and raw[:1] in "[{0123456789-tfn\"" else raw
        except ValueError:
            return raw

    def set_error(self, message: str | None) -> None:
        super().set_error(message)
        for value in self.query(".value"):
            value.set_class(bool(message), "-invalid")

    def save(self, raw: str, layer: str | None = None) -> None:
        screen = self.screen
        try:
            self.app.opened.ops.settings(self.key.dotted, self.value(raw), layer=layer or self.config_layer)
        except (ConfigError, Exception) as exc:  # noqa: BLE001 -- a bad value is refused, with the reason
            text = str(exc)  # under the value, which keeps what was typed; the file and key are already shown
            self.set_error(text.split(f"{self.key.dotted}: ", 1)[-1])
            return
        self.set_error(None)
        self.app.toast(f"{self.key.dotted} saved to {layer or self.config_layer}")
        self.app.after_settings()
        screen.call_later(screen.redraw)

    @on(Input.Submitted, ".value")
    def _submitted(self, event) -> None:
        event.stop()
        self.save(event.value)

    @on(Select.Changed, ".value")
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


class SettingsScreen(PartScreen):
    DEFAULT_CSS = """
    SettingsScreen #settings-body { margin: 1 0; }
    SettingsScreen #settings-head { height: 1; margin-bottom: 1; }
    SettingsScreen #search { width: 1fr; }
    SettingsScreen .skeleton-row { margin-bottom: 1; }
    SettingsScreen .skeleton-row.-title { width: 24; }
    SettingsScreen #chat-side { display: none; }
    SettingsScreen.-assistant #chat-side { display: block; }
    SettingsScreen .group-title { text-style: bold; color: $primary; margin-top: 1; }
    SettingsScreen #layer-tabs { height: 1fr; }
    SettingsScreen #layer-tabs TabsContent { height: 1fr; margin-top: 0; }
    SettingsScreen .sites { height: auto; }
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
        yield ResizablePanelGroup(
            ResizablePanel(id="chat-side", size=30),
            ResizableHandle(id="chat-handle"),
            ResizablePanel(Vertical(Horizontal(Input(placeholder="Search keys (Ctrl+F)", id="search"),
                                               id="settings-head"),
                                    Tabs(TabsList(*(TabsTrigger(x.title(), x) for x in LAYERS)),
                                         *(TabsContent(x, VerticalScroll(
                                             *(self.skeleton() if x == self.layer_tab else ()), id=f"rows-{x}"))
                                           for x in LAYERS),
                                         value=self.layer_tab, id="layer-tabs")), size=70),
            id="settings-body")
        yield status

    @staticmethod
    def skeleton():
        """What the tab shows while its rows are built (the screen is drawn first)."""
        for n in range(8):
            yield Skeleton("1fr", 1, classes="skeleton-row" + (" -title" if n % 4 == 0 else ""))

    async def _fill(self, layer: str) -> None:
        """Build the rows of a tab, after the screen is drawn; they replace its skeleton."""
        rows = self.query_one(f"#rows-{layer}", VerticalScroll)
        merged = self.app.opened.config.config.model_dump(mode="json")
        built = list(self.rows(layer, merged))
        first = True
        for at in range(0, len(built), 6):  # a few rows at a time: the first ones show at once
            if first:
                await rows.remove_children()
            await rows.mount_all(built[at:at + 6])
            if first and layer == self.layer_tab:
                self.focus_main()
            first = False
            await asyncio.sleep(0)

    def rows(self, layer: str, merged: dict):
        for title, section in GROUPS:
            keys = [k for k in group_keys(section) if self.filter in k.dotted.lower() or self.filter in k.doc.lower()]
            if not keys:
                continue
            yield Static(title, classes="group-title", id=f"group-{section}-{layer}")
            if section == "tools":
                yield Horizontal(Button("Apply preset ▾", id="apply-preset"), classes="sites")
            for k in keys:
                yield SettingRow(k, layer, merged)
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
        showing = self.has_class("-assistant")
        self.remove_class("-assistant")
        await self.recompose()
        self.query_one("#chat-handle").display = False
        await self._fill(self.layer_tab)
        if showing:
            self.action_toggle_assistant()

    def on_mount(self) -> None:
        super().on_mount()
        self.query_one("#chat-handle").display = False
        self.set_timer(0.02, lambda: self.run_worker(self._load_first(), exclusive=True))

    async def _load_first(self) -> None:
        await self._fill(self.layer_tab)
        if self.group:
            self.call_after_refresh(self._scroll_to_group)

    def main_part(self):
        rows = self.query(f"#rows-{self.layer_tab} SettingRow .value")
        return rows.first() if rows else self.query_one("#search")

    @on(Tabs.Changed, "#layer-tabs")
    async def _layer_changed(self, event: Tabs.Changed) -> None:
        """A tab's rows are made the first time it is shown (lazy)."""
        self.layer_tab = event.value
        rows = self.query_one(f"#rows-{event.value}", VerticalScroll)
        if not rows.children:
            await rows.mount_all(list(self.skeleton()))
            self.set_timer(0.02, lambda: self.run_worker(self._fill(event.value)))

    def action_toggle_assistant(self) -> None:
        """The Assistant is hidden at first; View ▸ Focus ▸ Assistant (or its key) shows it, again hides it."""
        side = self.query_one("#chat-side")
        showing = not self.has_class("-assistant")
        self.set_class(showing, "-assistant")
        self.query_one("#chat-handle").display = showing
        if showing and not side.children:
            side.mount(ChatPanel(self.app.opened.ops, lambda: {"screen": "settings"}, id="chat"))
        if showing:
            self.call_after_refresh(lambda: self.query("#chat-input") and self.query_one("#chat-input").focus())
        else:
            self.focus_main()
        self._sync_view_menu(showing)

    def _sync_view_menu(self, showing: bool) -> None:
        """View ▸ Assistant shows whether the Assistant is shown."""
        from q3tui.tui.ui.menu import MenuCheckboxItem

        for bar in self.query("Menubar"):
            for menu in bar.menus:
                for item in getattr(menu.content, "children", ()):
                    if isinstance(item, MenuCheckboxItem) and item.value == "view-assistant":
                        item.checked = showing
            bar.refresh_content()

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
