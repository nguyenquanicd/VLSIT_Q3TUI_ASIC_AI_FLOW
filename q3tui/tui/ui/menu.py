"""Shared core of the menu components (Menubar, DropdownMenu).

The composition objects describe menus; `MenuRoot` owns the open popups and `MenuPopup`
renders, positions, and navigates one level of rows. Concrete components add their triggers.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Literal

from rich.cells import cell_len
from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.color import Color
from textual.message import Message
from textual.widget import Widget
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from q3tui.tui.ui.icons import IconName, icon, key_label

__all__ = [
    "MenuCheckboxItem",
    "MenuContent",
    "MenuGroup",
    "MenuItem",
    "MenuLabel",
    "MenuMenu",
    "MenuPopup",
    "MenuPortal",
    "MenuRadioGroup",
    "MenuRadioItem",
    "MenuRoot",
    "MenuSeparator",
    "MenuShortcut",
    "MenuSub",
    "MenuSubContent",
    "MenuSubTrigger",
    "MenuTrigger",
    "background_beneath",
]


@dataclass(frozen=True)
class MenuShortcut:
    text: str

    @classmethod
    def from_key(cls, key: str) -> MenuShortcut:
        """A shortcut hint for a Textual key name, drawn with key icons: `ctrl+n`."""
        return cls(key_label(key))


@dataclass
class MenuItem:
    label: str
    value: str = ""
    shortcut: MenuShortcut | str | None = None
    icon_name: IconName | None = None
    disabled: bool = False
    inset: bool = False
    variant: Literal["default", "destructive"] = "default"
    close_on_select: bool = True
    text_value: str | None = None


@dataclass
class MenuCheckboxItem(MenuItem):
    checked: bool | Literal["indeterminate"] = False
    close_on_select: bool = False


@dataclass
class MenuRadioItem(MenuItem):
    close_on_select: bool = False


@dataclass(frozen=True)
class MenuLabel:
    text: str
    inset: bool = False


@dataclass(frozen=True)
class MenuSeparator:
    pass


class MenuGroup:
    def __init__(self, *children: object) -> None:
        self.children = children


class MenuRadioGroup(MenuGroup):
    def __init__(self, *children: MenuRadioItem | MenuLabel, value: str = "") -> None:
        super().__init__(*children)
        self.value = value


class MenuContent(MenuGroup):
    def __init__(
        self,
        *children: object,
        align: Literal["start", "end"] = "start",
        side_offset: int = 0,
        width: int | None = None,
        min_width: int = 16,
        max_height: int = 16,
    ) -> None:
        super().__init__(*children)
        if (
            align not in ("start", "end")
            or (width is not None and width < 6)
            or min_width < 6
            or max_height < 3
        ):
            raise ValueError("Invalid menu alignment, width, min_width, or max_height")
        self.align = align
        self.side_offset = side_offset
        self.width = width  # None fits the content, never below min_width.
        self.min_width = min_width
        self.max_height = max_height


class MenuSubContent(MenuContent):
    pass


@dataclass
class MenuSubTrigger(MenuItem):
    pass


@dataclass
class MenuSub:
    trigger: MenuSubTrigger
    content: MenuSubContent


@dataclass
class MenuPortal:
    """Mount the content on the Screen, escaping the trigger's layout/clip."""

    content: MenuContent


def background_beneath(widget: Widget, y: int) -> Color:
    """Background under row `y` of an overlay `widget`; the widest run of widgets wins.

    Textual paints half-cell edges against the DOM ancestors' background, which is the Screen
    for an overlay, not whatever is actually under it on screen. Overlays (menus, selects,
    popovers) use this to color their edges.
    """
    runs: dict[Color, int] = {}
    x, end = widget.region.x, widget.region.right
    while x < end:
        for other, region in widget.screen.get_widgets_at(x, y):
            if other is widget or widget in other.ancestors:
                continue
            stop = max(x + 1, min(region.right, end))
            color = other.background_colors[1]
            runs[color] = runs.get(color, 0) + stop - x
            x = stop
            break
        else:
            x += 1
    return max(runs, key=runs.__getitem__) if runs else widget.background_colors[0]


class MenuTrigger(Static, can_focus=True):
    """Focusable widget that opens its menu. Subclasses add keys and styling."""

    BINDINGS = [
        Binding("enter,space", "open", "Open menu"),
        Binding("escape", "close", "Close menu"),
    ]

    def __init__(self, label: str, *, id: str | None = None, disabled: bool = False) -> None:
        super().__init__(label, id=id, disabled=disabled, markup=False)
        self.label_text = label
        self._root: MenuRoot | None = None
        self.menu_value = ""

    async def action_open(self) -> None:
        if self._root:
            await self._root.open_menu(self.menu_value)

    async def action_close(self) -> None:
        if self._root:
            await self._root.close()

    async def on_click(self, event: events.Click) -> None:
        event.stop()
        await self.action_open()

    async def on_enter(self) -> None:
        if self._root and self._root.popups and not self.disabled:
            await self._root.open_menu(self.menu_value, toggle=False)


@dataclass
class MenuMenu:
    value: str
    trigger: MenuTrigger
    content: MenuContent | MenuPortal
    disabled: bool = False


@dataclass
class _Row:
    item: MenuItem | MenuLabel
    group: MenuRadioGroup | None = None
    sub: MenuSub | None = None
    offset: int = 0


def _flatten(content: MenuGroup) -> list[_Row | None]:
    rows: list[_Row | None] = []

    def walk(group: MenuGroup, radio: MenuRadioGroup | None = None) -> None:
        for child in group.children:
            if isinstance(child, MenuSeparator):
                rows.append(None)
            elif isinstance(child, MenuRadioGroup):
                walk(child, child)
            elif isinstance(child, MenuGroup):
                walk(child, radio)
            elif isinstance(child, MenuSub):
                rows.append(_Row(child.trigger, sub=child, offset=len(rows)))
            elif isinstance(child, (MenuItem, MenuLabel)):
                rows.append(_Row(child, group=radio, offset=len(rows)))
            else:
                raise TypeError(f"Unsupported menu child: {type(child).__name__}")

    walk(content)
    return rows


class MenuRoot(Static):
    """Owns the open popups of one or more menus; Menubar and DropdownMenu build on it."""

    class Selected(Message):
        def __init__(self, root: MenuRoot, item: MenuItem) -> None:
            super().__init__()
            self.root = root
            self.item = item
            self.value = item.value or item.label
            self.checked = item.checked if isinstance(item, MenuCheckboxItem) else None

    def __init__(
        self,
        *menus: MenuMenu,
        loop_focus: bool = True,
        disabled: bool = False,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes, disabled=disabled)
        if len({menu.value for menu in menus}) != len(menus):
            raise ValueError("Menu values must be unique")
        self.menus = menus
        self.loop_focus = loop_focus
        self.orientation: Literal["horizontal", "vertical"] = "horizontal"
        self.active_index = 0
        self.popups: list[MenuPopup] = []
        self._closing = False

    @property
    def active_popup(self) -> MenuPopup | None:
        return self.popups[-1] if self.popups else None

    def compose(self) -> ComposeResult:
        first = True
        for menu in self.menus:
            trigger = menu.trigger
            trigger._root = self
            trigger.menu_value = menu.value
            if trigger.id is None:
                trigger.id = f"menu-{menu.value}"
            trigger.disabled = trigger.disabled or menu.disabled
            trigger.can_focus = first and not trigger.disabled
            if trigger.can_focus:
                self.active_index = self.menus.index(menu)
                first = False
            yield trigger

    def on_mount(self) -> None:
        self.app.message_signal.subscribe(self, self._observe_app_message)

    async def _observe_app_message(self, message: Message) -> None:
        if isinstance(message, events.MouseDown):
            await self.dismiss_outside(message.screen_x, message.screen_y)
        elif isinstance(message, events.Resize):
            await self.close(restore_focus=False)

    def refresh_content(self) -> None:
        """Reflect externally updated checkbox/radio model values in open menus."""
        for popup in self.popups:
            popup.refresh_rows()

    def watch_disabled(self, disabled: bool) -> None:
        if disabled and self.is_mounted:
            self.call_later(self.close, False)

    def _activate(self, menu: MenuMenu) -> None:
        self.active_index = self.menus.index(menu)
        for candidate in self.menus:
            candidate.trigger.can_focus = candidate is menu and not candidate.trigger.disabled

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        for menu in self.menus:
            if event.widget is menu.trigger:
                self._activate(menu)

    async def move_trigger(self, direction: int) -> None:
        enabled = [menu for menu in self.menus if not menu.trigger.disabled]
        if not enabled or self.disabled:
            return
        current = self.menus[self.active_index]
        index = enabled.index(current) if current in enabled else 0
        next_index = index + direction
        if self.loop_focus:
            next_index %= len(enabled)
        else:
            next_index = max(0, min(next_index, len(enabled) - 1))
        target = enabled[next_index]
        if self.popups:
            await self.open_menu(target.value, toggle=False)
        else:
            self._activate(target)
            target.trigger.focus()

    async def open_menu(self, value: str, *, last: bool = False, toggle: bool = True) -> None:
        menu = next((menu for menu in self.menus if menu.value == value), None)
        if menu is None or self.disabled or menu.trigger.disabled:
            return
        if self.popups and self.popups[0].menu_name == value and toggle:
            await self.close()
            return
        if self.popups and self.popups[0].menu_name == value:
            return
        await self.close(restore_focus=False)
        self._activate(menu)
        menu.trigger.add_class("open")
        content = menu.content.content if isinstance(menu.content, MenuPortal) else menu.content
        popup = MenuPopup(self, menu.trigger, value, content, last=last)
        self.popups.append(popup)
        await self.screen.mount(popup)

    async def close(self, restore_focus: bool = True) -> None:
        self._closing = True
        try:
            popups, self.popups = self.popups, []
            for popup in reversed(popups):
                if popup.is_mounted:
                    await popup.remove()
            for menu in self.menus:
                menu.trigger.remove_class("open")
            if popups and restore_focus:
                self.screen.set_focus(self.menus[self.active_index].trigger)
        finally:
            self._closing = False

    async def close_children(self, parent: MenuPopup) -> None:
        if parent not in self.popups:
            return
        index = self.popups.index(parent) + 1
        children, self.popups = self.popups[index:], self.popups[:index]
        for child in reversed(children):
            if child.is_mounted:
                await child.remove()

    async def dismiss_if_focus_left(self) -> None:
        if self._closing or not self.popups:
            return
        if self.app.focused not in [*self.popups, *(menu.trigger for menu in self.menus)]:
            await self.close(restore_focus=False)

    async def dismiss_outside(self, x: float, y: float) -> None:
        regions = [popup.region for popup in self.popups]
        regions.extend(menu.trigger.region for menu in self.menus)
        if self.popups and not any(region.contains(x, y) for region in regions):
            await self.close(restore_focus=False)

    async def select(self, popup: MenuPopup, row: _Row) -> None:
        item = row.item
        if not isinstance(item, MenuItem) or item.disabled:
            return
        if row.sub:
            await popup.open_submenu()
            return
        if isinstance(item, MenuCheckboxItem):
            item.checked = item.checked is not True
        elif isinstance(item, MenuRadioItem) and row.group:
            row.group.value = item.value or item.label
        if item.close_on_select:
            await self.close()
        else:
            popup.refresh_rows()
        self.post_message(self.Selected(self, item))

    async def on_unmount(self) -> None:
        self.app.message_signal.unsubscribe(self)
        await self.close(restore_focus=False)


class MenuPopup(OptionList):
    """An anchored, non-modal list of menu rows that leaves the screen interactive."""

    DEFAULT_CSS = """
    MenuPopup {
        overlay: screen; position: absolute; constrain: inside inside;
        width: 38; height: auto; max-height: 16; color: $foreground;
    }
    MenuPopup, MenuPopup:focus {
        padding: 0; border: none; border-top: outer $background;
        border-bottom: outer $background; background: $surface;
    }
    MenuPopup > .option-list--option { padding: 0 1; }
    MenuPopup > .option-list--option-highlighted {
        background: $primary-muted; color: $foreground; }
    """
    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("left", "switch(-1)", "Previous menu"),
        Binding("right", "switch(1)", "Next menu"),
        Binding("tab", "leave(False)", "Next control"),
        Binding("shift+tab", "leave(True)", "Previous control"),
        Binding("space", "select", "Select"),
        Binding("up", "step(-1)", "Previous item"),
        Binding("down", "step(1)", "Next item"),
    ]

    def __init__(
        self,
        owner: MenuRoot,
        anchor: Widget,
        name: str,
        content: MenuContent,
        *,
        parent: MenuPopup | None = None,
        parent_row: _Row | None = None,
        last: bool = False,
    ) -> None:
        super().__init__(markup=False)
        self.anchor = anchor
        self.menu_name = name
        self.owner = owner
        self.content = content
        self.parent_popup = parent
        self.parent_row = parent_row
        self.last = last
        self.rows: list[_Row] = []
        self._visible_rows = 0
        self._width = 0
        self._typeahead = ""
        self._typed_at = 0.0

    def _row_parts(self, row: _Row) -> tuple[Text, str]:
        """Left text and right-aligned suffix (shortcut or chevron) of a row."""
        item = row.item
        if isinstance(item, MenuLabel):
            return Text(("  " if item.inset else "") + item.text, style="bold dim"), ""
        prefix = ""
        if isinstance(item, MenuCheckboxItem):
            marker = "mixed" if item.checked == "indeterminate" else "selected"
            prefix = (icon(marker) if item.checked else " ") + " "
        elif isinstance(item, MenuRadioItem):
            prefix = (
                icon("selected")
                if row.group and row.group.value == (item.value or item.label)
                else " "
            ) + " "
        elif item.inset:
            prefix = "  "
        if item.icon_name:
            prefix += icon(item.icon_name) + " "
        suffix = icon("chevron_right") if row.sub else ""
        if item.shortcut:
            suffix = (
                item.shortcut.text if isinstance(item.shortcut, MenuShortcut) else item.shortcut
            )
        return Text(prefix + item.label), suffix

    def _natural_width(self, row: _Row) -> int:
        label, suffix = self._row_parts(row)
        return label.cell_len + (cell_len(suffix) + 2 if suffix else 0)

    def _row_text(self, row: _Row, width: int) -> Text:
        item = row.item
        label, suffix = self._row_parts(row)
        if isinstance(item, MenuLabel):
            label.truncate(width, overflow="ellipsis")
            return label
        right = Text(suffix)
        right.truncate(max(0, width - 3), overflow="ellipsis")
        suffix = right.plain
        label.truncate(max(1, width - cell_len(suffix) - (2 if suffix else 0)), overflow="ellipsis")
        if suffix:
            label.append(" " * max(1, width - label.cell_len - cell_len(suffix)))
            label.append(suffix, style="dim")
        if item.variant == "destructive":
            label.stylize(self.app.get_css_variables()["text-error"])
        if item.disabled:
            label.stylize("dim")
        return label

    def refresh_rows(self) -> None:
        highlighted = self.highlighted
        entries = _flatten(self.content)
        self.rows = [row for row in entries if row is not None]
        scrollbar = 1 if len(entries) > self._visible_rows > 0 else 0
        width = max(1, self._width - 2 - scrollbar)
        options = []
        for entry in entries:
            if entry is None:
                options.append(None)
            else:
                disabled = isinstance(entry.item, MenuLabel) or entry.item.disabled
                options.append(Option(self._row_text(entry, width), disabled=disabled))
        self.clear_options()
        self.add_options(options)
        if highlighted is not None and highlighted < self.option_count:
            self.highlighted = highlighted

    def _fit_width(self, entries: list[_Row | None]) -> int:
        """Fixed `width` if given, else the widest row (plus padding and scrollbar)."""
        screen_width = self.screen.size.width
        if self.content.width is not None:
            return min(self.content.width, screen_width)
        scrollbar = 1 if len(entries) > self._visible_rows else 0
        widest = max((self._natural_width(row) for row in entries if row), default=0)
        return min(max(widest + 2 + scrollbar, self.content.min_width), screen_width)

    def mount_menu(self) -> None:
        entries = _flatten(self.content)
        height = min(len(entries) + 2, self.content.max_height, self.screen.size.height)
        self._visible_rows = height - 2
        width = self._fit_width(entries)
        self._width = width
        self.styles.width = width
        self.styles.height = height
        self.styles.max_height = self.screen.size.height
        anchor = self.anchor.region
        gap = self.content.side_offset
        if self.parent_popup is None and self.owner.orientation == "horizontal":
            x = anchor.x if self.content.align == "start" else anchor.right - width
            y = anchor.bottom + gap
            if y + height > self.screen.size.height and anchor.y >= height:
                y = anchor.y - height - gap
        else:
            # Beside the trigger or parent item, with the first row level with it.
            parent = self.parent_popup
            edge = parent.region if parent else anchor
            x = edge.right + gap
            if x + width > self.screen.size.width:
                x = edge.x - width - gap
            if parent:
                y = parent.content_region.y + self.parent_row.offset - int(parent.scroll_offset.y)
            else:
                y = anchor.y
            if parent is None and self.content.align == "end":
                y = anchor.bottom - height + self.gutter.bottom
            else:
                y -= self.gutter.top
        self.styles.offset = (
            max(0, min(x, self.screen.size.width - width)),
            max(0, min(y, self.screen.size.height - height)),
        )
        self.refresh_rows()
        self.focus()
        self.action_last() if self.last else self.action_first()
        self.watch(self.app, "theme", lambda _: self.call_after_refresh(self._restyle), init=False)

    def _restyle(self) -> None:
        self.refresh_rows()
        self.sync_colors()

    def on_mount(self) -> None:
        self.mount_menu()
        self.call_after_refresh(self.sync_colors)

    def on_focus(self) -> None:
        self.call_after_refresh(self.sync_colors)

    def on_blur(self) -> None:
        self.call_after_refresh(self.sync_colors)
        self.call_after_refresh(self.close_if_focus_left)

    def sync_colors(self) -> None:
        """Paint the scrollbar track and the half-cell edges to match what is around the popup.

        Textual composites a transparent scrollbar track onto the background behind the
        widget, which misses the focus tint, so the track is set to the popup's own rendered
        background. The edges are set from the widgets beneath the popup.
        """
        if not self.is_mounted:
            return
        background = self.background_colors[1]
        self.styles.scrollbar_background = background
        self.styles.scrollbar_background_hover = background
        self.styles.scrollbar_background_active = background
        self.styles.border_top = ("outer", background_beneath(self, self.region.y))
        self.styles.border_bottom = ("outer", background_beneath(self, self.region.bottom - 1))

    @on(OptionList.OptionSelected)
    async def choose(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        event.prevent_default()
        await self.owner.select(self, self.rows[event.option_index])

    async def action_step(self, direction: int) -> None:
        enabled = [
            i
            for i, row in enumerate(self.rows)
            if isinstance(row.item, MenuItem) and not row.item.disabled
        ]
        if not enabled:
            return
        current = enabled.index(self.highlighted) if self.highlighted in enabled else -1
        target = current + direction
        if self.owner.loop_focus:
            target %= len(enabled)
        else:
            target = max(0, min(target, len(enabled) - 1))
        self.highlighted = enabled[target]
        self.scroll_to_highlight()
        await self.owner.close_children(self)

    async def action_switch(self, direction: int) -> None:
        if direction > 0 and self.highlighted is not None and self.rows[self.highlighted].sub:
            await self.open_submenu()
        elif direction < 0 and self.parent_popup:
            parent = self.parent_popup
            await self.owner.close_children(parent)
            parent.focus()
        else:
            await self.owner.move_trigger(direction)

    async def open_submenu(self, focus: bool = True) -> None:
        if self.highlighted is None:
            return
        row = self.rows[self.highlighted]
        if not row.sub or row.item.disabled:
            return
        existing = next(
            (
                popup
                for popup in self.owner.popups
                if popup.parent_popup is self and popup.parent_row is row
            ),
            None,
        )
        if existing:
            if focus:
                existing.focus()
            return
        await self.owner.close_children(self)
        popup = MenuPopup(
            self.owner,
            self,
            self.menu_name,
            row.sub.content,
            parent=self,
            parent_row=row,
        )
        self.owner.popups.append(popup)
        await self.screen.mount(popup)
        if not focus:
            self.focus()

    async def action_close(self) -> None:
        if self.parent_popup:
            parent = self.parent_popup
            await self.owner.close_children(parent)
            parent.focus()
        else:
            await self.owner.close()

    async def action_leave(self, reverse: bool) -> None:
        screen = self.screen
        await self.owner.close()
        screen.focus_previous() if reverse else screen.focus_next()

    async def close_if_focus_left(self) -> None:
        await self.owner.dismiss_if_focus_left()

    def on_key(self, event: events.Key) -> None:
        if not self.rows or not event.is_printable or event.key == "space":
            return
        now = monotonic()
        character = event.character or ""
        self._typeahead = self._typeahead + character if now - self._typed_at < 0.7 else character
        self._typed_at = now
        query = self._typeahead.casefold()
        if len(set(query)) == 1:
            query = query[:1]
        start = (self.highlighted or 0) + 1
        for i in [*range(start, len(self.rows)), *range(start)]:
            item = self.rows[i].item
            if (
                isinstance(item, MenuItem)
                and not item.disabled
                and (item.text_value or item.label).casefold().startswith(query)
            ):
                self.highlighted = i
                self.scroll_to_highlight()
                self.call_later(self.owner.close_children, self)
                break
        event.stop()
        event.prevent_default()

    async def on_mouse_scroll_down(self) -> None:
        await self.owner.close_children(self)

    async def on_mouse_scroll_up(self) -> None:
        await self.owner.close_children(self)

    async def on_mouse_move(self, event: events.MouseMove) -> None:
        index = event.style.meta.get("option")
        if isinstance(index, int) and 0 <= index < len(self.rows):
            row = self.rows[index]
            if isinstance(row.item, MenuLabel) or row.item.disabled:
                return
            self.highlighted = index
            if row.sub and not row.item.disabled:
                await self.open_submenu(focus=False)
            else:
                await self.owner.close_children(self)

    def on_enter(self) -> None:
        self.focus()
