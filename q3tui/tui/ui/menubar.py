"""Keyboard-first Textual adaptation of the shadcn/base Menubar parts.

Source API: https://ui.shadcn.com/docs/components/base/menubar
The composition objects describe menus; Textual widgets own focus and overlays. The parts and
the popups are shared with DropdownMenu and live in `ui/menu.py`; this module adds the bar
with its roving focus, and keeps the `Menubar*` names.
"""

from __future__ import annotations

from time import monotonic
from typing import Literal

from textual import events
from textual.binding import Binding

from q3tui.tui.ui.menu import (
    MenuCheckboxItem,
    MenuContent,
    MenuGroup,
    MenuItem,
    MenuLabel,
    MenuMenu,
    MenuPortal,
    MenuRadioGroup,
    MenuRadioItem,
    MenuRoot,
    MenuSeparator,
    MenuShortcut,
    MenuSub,
    MenuSubContent,
    MenuSubTrigger,
    MenuTrigger,
)

__all__ = [
    "Menubar",
    "MenubarCheckboxItem",
    "MenubarContent",
    "MenubarGroup",
    "MenubarItem",
    "MenubarLabel",
    "MenubarMenu",
    "MenubarPortal",
    "MenubarRadioGroup",
    "MenubarRadioItem",
    "MenubarSeparator",
    "MenubarShortcut",
    "MenubarSub",
    "MenubarSubContent",
    "MenubarSubTrigger",
    "MenubarTrigger",
]

MenubarShortcut = MenuShortcut
MenubarItem = MenuItem
MenubarCheckboxItem = MenuCheckboxItem
MenubarRadioItem = MenuRadioItem
MenubarLabel = MenuLabel
MenubarSeparator = MenuSeparator
MenubarGroup = MenuGroup
MenubarRadioGroup = MenuRadioGroup
MenubarContent = MenuContent
MenubarSubContent = MenuSubContent
MenubarSubTrigger = MenuSubTrigger
MenubarSub = MenuSub
MenubarPortal = MenuPortal
MenubarMenu = MenuMenu


class MenubarTrigger(MenuTrigger):
    DEFAULT_CSS = """
    MenubarTrigger { width: auto; height: 1; padding: 0 1;
        background: transparent; color: $foreground; }
    MenubarTrigger:focus, MenubarTrigger.open, MenubarTrigger:hover {
        background: $primary-muted; color: $foreground; }
    MenubarTrigger:disabled { color: $text-disabled; }
    """
    BINDINGS = [
        Binding("down", "vertical(1)", "Open / next"),
        Binding("up", "vertical(-1)", "Open / previous"),
        Binding("right", "horizontal(1)", "Next menu"),
        Binding("left", "horizontal(-1)", "Previous menu"),
        Binding("home", "edge(False)", "First menu"),
        Binding("end", "edge(True)", "Last menu"),
    ]

    async def action_vertical(self, direction: int) -> None:
        bar = self._root
        if bar:
            if bar.orientation == "vertical":
                await bar.move_trigger(direction)
            else:
                await bar.open_menu(self.menu_value, last=direction < 0, toggle=False)

    async def action_horizontal(self, direction: int) -> None:
        bar = self._root
        if bar:
            if bar.orientation == "horizontal":
                await bar.move_trigger(direction)
            elif direction > 0:
                await bar.open_menu(self.menu_value, toggle=False)

    def action_edge(self, last: bool) -> None:
        if self._root:
            self._root.focus_edge(last)

    def on_key(self, event: events.Key) -> None:
        if self._root and event.is_printable and event.key != "space":
            self._root.search_triggers(event.character or "")
            event.stop()
            event.prevent_default()


class Menubar(MenuRoot):
    DEFAULT_CSS = """
    Menubar { layout: horizontal; width: auto; height: 1; background: $surface; }
    Menubar.vertical { layout: vertical; height: auto; }
    """

    class Selected(MenuRoot.Selected):
        @property
        def menubar(self) -> Menubar:
            return self.root

    def __init__(
        self,
        *menus: MenubarMenu,
        loop_focus: bool = True,
        orientation: Literal["horizontal", "vertical"] = "horizontal",
        disabled: bool = False,
        id: str | None = None,
    ) -> None:
        if orientation not in ("horizontal", "vertical"):
            raise ValueError("Menubar supports horizontal or vertical LTR orientation")
        super().__init__(*menus, loop_focus=loop_focus, disabled=disabled, id=id)
        self.orientation = orientation
        self._search = ""
        self._search_time = 0.0
        self.set_class(orientation == "vertical", "vertical")

    def focus_edge(self, last: bool) -> None:
        enabled = [menu for menu in self.menus if not menu.trigger.disabled]
        if enabled and not self.disabled:
            menu = enabled[-1 if last else 0]
            self._activate(menu)
            menu.trigger.focus()

    def search_triggers(self, character: str) -> None:
        self._search = (
            self._search + character if monotonic() - self._search_time < 0.7 else character
        )
        self._search_time = monotonic()
        query = self._search.casefold()
        if len(set(query)) == 1:
            query = query[:1]
        ordered = self.menus[self.active_index + 1 :] + self.menus[: self.active_index + 1]
        for menu in ordered:
            if not menu.trigger.disabled and menu.trigger.label_text.casefold().startswith(query):
                self._activate(menu)
                menu.trigger.focus()
                break
