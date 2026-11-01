"""Sidebar, following shadcn's Sidebar: a navigation column that can fold to icons."""

from __future__ import annotations

from textual.actions import SkipAction
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from q3tui.tui.ui.action import Action
from q3tui.tui.ui.icons import IconName
from q3tui.tui.ui.keys import bind_key

__all__ = ["Sidebar", "SidebarGroup", "SidebarMenuItem"]


class SidebarMenuItem(Action):
    """A destination. Enter, Space, a click, or its key selects it. While the sidebar is folded
    only its icon shows."""

    DEFAULT_CSS = """
    SidebarMenuItem { width: 1fr; height: 1; padding: 0 1; color: $text-muted; }
    SidebarMenuItem:hover, SidebarMenuItem:focus { background: $panel; color: $foreground; }
    SidebarMenuItem.-active { background: $primary-muted; color: $foreground; text-style: bold; }
    """

    def __init__(
        self,
        label: str,
        value: str = "",
        *,
        icon_name: IconName | None = None,
        key: str | None = None,
        disabled: bool = False,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(
            label, key=key, icon_name=icon_name, disabled=disabled, id=id, classes=classes
        )
        self.value = value or label

    def refresh_label(self) -> None:
        sidebar = next((a for a in self.ancestors if isinstance(a, Sidebar)), None)
        if sidebar is not None and sidebar.collapsed and self.icon_name:
            self.update(self.glyph())  # Folded: the icon alone.
        else:
            super().refresh_label()

    def activate(self) -> None:
        sidebar = next((a for a in self.ancestors if isinstance(a, Sidebar)), None)
        if sidebar is not None:
            sidebar.select(self.value)


class SidebarGroup(Vertical):
    """A muted heading and its items."""

    DEFAULT_CSS = """
    SidebarGroup { height: auto; margin-bottom: 1; }
    SidebarGroup > .sidebar-label { height: 1; padding: 0 1; color: $text-muted; text-style: dim; }
    """

    def __init__(self, label: str, *items: Widget, id: str | None = None) -> None:
        super().__init__(Static(label, classes="sidebar-label", markup=False), *items, id=id)


class Sidebar(Vertical):
    """`Sidebar(SidebarGroup("Workspace", SidebarMenuItem("Home", icon_name="home")), ...)`.

    Up and Down move between the items, Home and End jump to the ends. `toggle_key` (Ctrl+B by
    default) folds or unfolds it from anywhere on the screen. Posts `Sidebar.Selected`.
    """

    DEFAULT_CSS = """
    Sidebar { width: 26; height: 1fr; background: $surface; padding: 1 0; }
    Sidebar.-collapsed { width: 5; }
    Sidebar.-collapsed .sidebar-label { display: none; }
    """
    BINDINGS = [
        Binding("up", "step(-1)", show=False),
        Binding("down", "step(1)", show=False),
        Binding("home", "edge(0)", show=False),
        Binding("end", "edge(-1)", show=False),
    ]

    collapsed = reactive(False)

    class Selected(Message):
        def __init__(self, sidebar: Sidebar, value: str) -> None:
            super().__init__()
            self.sidebar = sidebar
            self.value = value

        @property
        def control(self) -> Sidebar:
            return self.sidebar

    def __init__(
        self,
        *parts: Widget,
        value: str | None = None,
        collapsed: bool = False,
        toggle_key: str | None = "ctrl+b",
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(*parts, id=id, classes=classes)
        self.value = value
        self.toggle_key = toggle_key
        self._unbind = None
        self.set_reactive(Sidebar.collapsed, collapsed)
        self.set_class(collapsed, "-collapsed")

    @property
    def items(self) -> list[SidebarMenuItem]:
        return list(self.query(SidebarMenuItem))

    def on_mount(self) -> None:
        if self.toggle_key:
            self._unbind = bind_key(self, self.toggle_key, self.toggle)
        self.select(self.value, notify=False)
        self._relabel()

    def on_unmount(self) -> None:
        if self._unbind:
            self._unbind()

    def watch_collapsed(self, collapsed: bool) -> None:
        self.set_class(collapsed, "-collapsed")
        if self.is_mounted:
            self._relabel()

    def _relabel(self) -> None:
        for item in self.items:
            item.refresh_label()

    def toggle(self) -> None:
        self.collapsed = not self.collapsed

    def select(self, value: str | None, *, notify: bool = True) -> None:
        changed = value != self.value
        self.value = value
        for item in self.items:
            item.set_class(item.value == value, "-active")
        if changed and notify and value is not None:
            self.post_message(self.Selected(self, value))

    def _enabled(self) -> list[SidebarMenuItem]:
        return [item for item in self.items if not item.disabled]

    def action_step(self, direction: int) -> None:
        items, focused = self._enabled(), self.screen.focused
        if focused not in items:
            raise SkipAction()
        items[(items.index(focused) + direction) % len(items)].focus()

    def action_edge(self, index: int) -> None:
        items = self._enabled()
        if self.screen.focused not in items:
            raise SkipAction()
        items[index].focus()
