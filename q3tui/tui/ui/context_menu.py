"""ContextMenu: a menu that opens where you right-click, following shadcn's Context Menu."""

from __future__ import annotations

import asyncio

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widget import Widget

from q3tui.tui.ui.menu import MenuContent, MenuMenu, MenuPortal, MenuRoot, MenuTrigger

__all__ = ["ContextMenu"]


class _Anchor(MenuTrigger):
    """A one-cell, invisible stand-in for the trigger, placed where the menu should open."""

    DEFAULT_CSS = """
    _Anchor { overlay: screen; position: absolute; width: 1; height: 1;
        background: transparent; }
    """
    can_focus = False


class ContextMenu(MenuRoot):
    """`ContextMenu(MenuContent(...), Static("Right-click me"))`.

    A right-click on anything inside opens the menu at the pointer. The keyboard way is
    **Shift+F10** while a widget inside has focus: it opens at that widget's lower-left corner.
    The menu has everything a [dropdown menu](dropdown-menu.md) has (arrow keys, typeahead,
    submenus, checkboxes, radios), and Escape closes it and returns focus to where it was.
    Posts `ContextMenu.Selected`.
    """

    DEFAULT_CSS = "ContextMenu { width: 1fr; height: auto; }"
    BINDINGS = [Binding("shift+f10", "open_here", show=False)]

    class Selected(MenuRoot.Selected):
        @property
        def context_menu(self) -> ContextMenu:
            return self.root

        @property
        def control(self) -> ContextMenu:
            return self.root

    def __init__(
        self,
        content: MenuContent | MenuPortal,
        *children: Widget,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(
            MenuMenu("context", _Anchor(""), content),
            id=id,
            classes=classes,
        )
        self._wrapped = children
        self._anchor: _Anchor | None = None
        self._returns: Widget | None = None
        self._opening = False

    def compose(self) -> ComposeResult:
        yield from self._wrapped  # The anchor is mounted on the Screen only while open.

    async def open_at(self, x: int, y: int) -> None:
        """Open the menu with its top-left corner at screen cell (x, y)."""
        await self.close(restore_focus=False)
        self._returns = self.screen.focused
        anchor = _Anchor("")
        anchor.styles.offset = (max(0, x), max(0, y - 1))
        anchor._root = self
        anchor.menu_value = "context"
        self.menus[0].trigger = anchor
        self._anchor = anchor
        await self.screen.mount(anchor)
        laid_out = asyncio.get_running_loop().create_future()
        anchor.call_after_refresh(laid_out.set_result, None)
        await laid_out  # The popup is placed from the anchor's region, so it needs one.
        self._opening = True  # `open_menu` closes first, which must not remove the anchor.
        try:
            await self.open_menu("context", toggle=False)
        finally:
            self._opening = False

    async def on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button == 3:
            event.stop()
            await self.open_at(event.screen_x, event.screen_y)

    async def action_open_here(self) -> None:
        focused = self.screen.focused
        if focused is None or self not in focused.ancestors:
            return
        await self.open_at(focused.region.x, focused.region.bottom)

    async def close(self, restore_focus: bool = True) -> None:
        was_open = bool(self.popups)
        await super().close(restore_focus=False)
        if self._opening:
            return
        anchor, self._anchor = self._anchor, None
        if anchor is not None and anchor.is_mounted:
            await anchor.remove()
        if was_open and restore_focus and self._returns is not None:
            self.screen.set_focus(self._returns)
