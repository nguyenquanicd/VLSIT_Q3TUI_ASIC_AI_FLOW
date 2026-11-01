"""Keyboard-first Textual adaptation of the shadcn/base DropdownMenu parts.

Source API: https://ui.shadcn.com/docs/components/base/dropdown-menu
A dropdown menu is one trigger and one menu. The parts and the popups are shared with the
Menubar and live in `ui/menu.py`; this module adds the single-menu root and a button-like
trigger, and exports every part under its `DropdownMenu*` name.
"""

from __future__ import annotations

from textual.binding import Binding
from textual.content import Content

from q3tui.tui.ui.icons import icon, key_label
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
    "DropdownMenu",
    "DropdownMenuCheckboxItem",
    "DropdownMenuContent",
    "DropdownMenuGroup",
    "DropdownMenuItem",
    "DropdownMenuLabel",
    "DropdownMenuPortal",
    "DropdownMenuRadioGroup",
    "DropdownMenuRadioItem",
    "DropdownMenuSeparator",
    "DropdownMenuShortcut",
    "DropdownMenuSub",
    "DropdownMenuSubContent",
    "DropdownMenuSubTrigger",
    "DropdownMenuTrigger",
]

DropdownMenuContent = MenuContent
DropdownMenuPortal = MenuPortal
DropdownMenuGroup = MenuGroup
DropdownMenuLabel = MenuLabel
DropdownMenuItem = MenuItem
DropdownMenuShortcut = MenuShortcut
DropdownMenuSeparator = MenuSeparator
DropdownMenuCheckboxItem = MenuCheckboxItem
DropdownMenuRadioGroup = MenuRadioGroup
DropdownMenuRadioItem = MenuRadioItem
DropdownMenuSub = MenuSub
DropdownMenuSubTrigger = MenuSubTrigger
DropdownMenuSubContent = MenuSubContent


class DropdownMenuTrigger(MenuTrigger):
    """A quiet one-row trigger: the label, then the key hint, then an optional chevron.

    `key` is the hint of the shortcut that opens the menu; it is only a hint.
    """

    DEFAULT_CSS = """
    DropdownMenuTrigger { width: auto; height: 1; padding: 0 1;
        background: transparent; color: $text-muted; }
    DropdownMenuTrigger:hover, DropdownMenuTrigger:focus, DropdownMenuTrigger.open {
        background: $panel; color: $foreground; }
    DropdownMenuTrigger:disabled { color: $text-disabled; }
    """
    BINDINGS = [
        Binding("down", "vertical(1)", "Open"),
        Binding("up", "vertical(-1)", "Open (last item)"),
    ]

    def __init__(
        self,
        label: str,
        *,
        key: str | None = None,
        chevron: bool = False,
        tooltip: str | None = None,
        id: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(label, id=id, disabled=disabled)
        self.shortcut = key
        self.chevron = chevron
        if tooltip:
            self.tooltip = tooltip

    def set_label(self, label: str, *, show_key: bool = True) -> None:
        """Change the label. With `show_key`, the dimmed key hint follows it."""
        self.label_text = label
        parts: list[str | tuple[str, str]] = [label]
        if self.shortcut and show_key:
            parts += [" ", (key_label(self.shortcut), "dim")]
        if self.chevron:
            parts += [" ", icon("chevron_down")]
        self.update(Content.assemble(*parts))

    def on_mount(self) -> None:
        self.set_label(self.label_text)

    async def action_vertical(self, direction: int) -> None:
        if self._root:
            await self._root.open_menu(self.menu_value, last=direction < 0, toggle=False)


class DropdownMenu(MenuRoot):
    """One trigger and one menu: `DropdownMenu(DropdownMenuTrigger("Open"), content)`.

    `value` names the menu; it is the `menu_name` of its popups. Open it from code with
    `await dropdown.open()`.
    """

    DEFAULT_CSS = "DropdownMenu { width: auto; height: 1; }"

    class Selected(MenuRoot.Selected):
        @property
        def dropdown(self) -> DropdownMenu:
            return self.root

    def __init__(
        self,
        trigger: DropdownMenuTrigger,
        content: MenuContent | MenuPortal,
        *,
        value: str = "menu",
        loop_focus: bool = True,
        disabled: bool = False,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(
            MenuMenu(value, trigger, content),
            loop_focus=loop_focus,
            disabled=disabled,
            id=id,
            classes=classes,
        )
        self.trigger = trigger

    async def open(self, *, last: bool = False, toggle: bool = True) -> None:
        """Open the menu; with `toggle`, close it instead when it is already open."""
        await self.open_menu(self.menus[0].value, last=last, toggle=toggle)
