"""Select: pick one value from a list, following shadcn's Select.

It is a `DropdownMenu` whose content is one radio group, so it shares the Menubar's popup:
typeahead, Home and End, disabled items, groups with labels, and the same look.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.cells import cell_len
from textual import events, on
from textual.content import Content
from textual.message import Message

from q3tui.tui.ui.dropdown_menu import DropdownMenu, DropdownMenuTrigger
from q3tui.tui.ui.icons import icon
from q3tui.tui.ui.menu import MenuContent, MenuLabel, MenuRadioGroup, MenuRadioItem, MenuSeparator

__all__ = ["Select", "SelectGroup", "SelectItem", "SelectSeparator"]


@dataclass
class SelectItem:
    label: str
    value: str = ""
    disabled: bool = False


class SelectGroup:
    """A labeled run of items."""

    def __init__(self, label: str, *items: SelectItem) -> None:
        self.label = label
        self.items = items


class SelectSeparator:
    pass


class SelectTrigger(DropdownMenuTrigger):
    """The closed select: the chosen label (or the placeholder) with the chevron at the right."""

    DEFAULT_CSS = """
    SelectTrigger { width: 1fr; height: 3; padding: 0 1; background: $surface;
        color: $foreground; border-top: outer transparent; border-bottom: outer transparent; }
    SelectTrigger:hover, SelectTrigger:focus, SelectTrigger.open { background: $panel; }
    SelectTrigger.-placeholder { color: $text-muted; }
    """

    def set_label(self, label: str, *, show_key: bool = True) -> None:
        self.label_text = label
        width = self.content_size.width
        pad = max(1, width - cell_len(label) - 1) if width else 1
        self.update(Content.assemble(label, " " * pad, icon("chevron_down")))

    def on_resize(self, event: events.Resize) -> None:
        self.set_label(self.label_text)
        if isinstance(self._root, Select):
            self._root.fit_popup(event.size.width)


class Select(DropdownMenu):
    """`Select(SelectItem("Apple", "apple"), SelectGroup("Veg", ...), value="apple")`.

    Opens with Enter, Space, or Down, like a dropdown. Choosing an item closes the menu, shows its
    label in the trigger, and posts `Select.Changed`.
    """

    DEFAULT_CSS = "Select { width: 1fr; height: 3; }"

    class Changed(Message):
        def __init__(self, select: Select, value: str | None, label: str | None) -> None:
            super().__init__()
            self.select = select
            self.value = value
            self.label = label

        @property
        def control(self) -> Select:
            return self.select

    def __init__(
        self,
        *entries: SelectItem | SelectGroup | SelectSeparator,
        value: str | None = None,
        placeholder: str = "Select an option",
        width: int | str | None = None,
        disabled: bool = False,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        self.placeholder = placeholder
        self._labels: dict[str, str] = {}
        children: list[object] = []
        for entry in entries:
            if isinstance(entry, SelectSeparator):
                children.append(MenuSeparator())
            elif isinstance(entry, SelectGroup):
                if children:
                    children.append(MenuSeparator())
                children.append(MenuLabel(entry.label))
                children += [self._radio(item) for item in entry.items]
            else:
                children.append(self._radio(entry))
        self._group = MenuRadioGroup(*children, value=value or "")
        self._content = MenuContent(self._group)
        super().__init__(
            SelectTrigger(placeholder, id=f"{id}-trigger" if id else None, chevron=False),
            self._content,
            value="select",
            disabled=disabled,
            id=id,
            classes=classes,
        )
        if width is not None:
            self.styles.width = width

    def _radio(self, item: SelectItem) -> MenuRadioItem:
        value = item.value or item.label
        self._labels[value] = item.label
        return MenuRadioItem(item.label, value, disabled=item.disabled, close_on_select=True)

    @property
    def value(self) -> str | None:
        return self._group.value or None

    def on_mount(self) -> None:
        self._show()

    def _show(self) -> None:
        label = self._labels.get(self.value or "")
        self.trigger.set_class(label is None, "-placeholder")
        self.trigger.set_label(label if label is not None else self.placeholder)

    def set_value(self, value: str | None, *, notify: bool = True) -> None:
        if (value or "") != self._group.value and value not in (None, *self._labels):
            raise ValueError(f"Unknown select value: {value!r}")
        changed = (value or "") != self._group.value
        self._group.value = value or ""
        self.refresh_content()
        self._show()
        if changed and notify:
            self.post_message(self.Changed(self, value, self._labels.get(value or "")))

    def fit_popup(self, width: int) -> None:
        """Keep the popup as wide as the trigger, whichever way it is opened."""
        self._content.width = max(6, width)

    @on(DropdownMenu.Selected)
    def _chosen(self, event: DropdownMenu.Selected) -> None:
        event.stop()
        self._show()
        self.post_message(self.Changed(self, self.value, self._labels.get(self.value or "")))
