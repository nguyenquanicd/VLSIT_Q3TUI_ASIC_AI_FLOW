"""Checkbox, Switch, and RadioGroup, following shadcn and made key-first.

All of them are `Action`s: Space or Enter flips or selects the focused one, a click does too, and
an optional `key` does it from anywhere on the screen, shown after the label as key icons.
"""

from __future__ import annotations

from typing import Literal

from textual.actions import SkipAction
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message

from q3tui.tui.ui.action import Action
from q3tui.tui.ui.icons import IconName

__all__ = ["Checkbox", "RadioGroup", "RadioGroupItem", "Switch"]

CheckState = bool | Literal["indeterminate"]


class Checkbox(Action):
    """A box that is checked, unchecked, or indeterminate. Activating an indeterminate box
    checks it."""

    DEFAULT_CSS = """
    Checkbox { width: auto; height: 1; padding: 0 1; color: $foreground; }
    Checkbox:hover, Checkbox:focus { background: $panel; }
    Checkbox:disabled { opacity: 50%; }
    """

    class Changed(Message):
        def __init__(self, checkbox: Checkbox, checked: CheckState) -> None:
            super().__init__()
            self.checkbox = checkbox
            self.checked = checked
            self.value = checkbox.value

        @property
        def control(self) -> Checkbox:
            return self.checkbox

    def __init__(
        self,
        label: str,
        *,
        value: str = "",
        checked: CheckState = False,
        key: str | None = None,
        disabled: bool = False,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(label, key=key, disabled=disabled, id=id, classes=classes)
        self.value = value or label
        self.checked = checked

    def glyph_name(self) -> IconName:
        if self.checked == "indeterminate":
            return "checkbox_mixed"
        return "checkbox_on" if self.checked else "checkbox_off"

    def set_checked(self, checked: CheckState, *, notify: bool = True) -> None:
        if checked == self.checked:
            return
        self.checked = checked
        self.refresh_label()
        if notify:
            self.post_message(self.Changed(self, checked))

    def activate(self) -> None:
        self.set_checked(self.checked is not True)


class Switch(Action):
    """An on/off switch. The label is muted while it is off."""

    DEFAULT_CSS = """
    Switch { width: auto; height: 1; padding: 0 1; color: $text-muted; }
    Switch.-on { color: $foreground; }
    Switch:hover, Switch:focus { background: $panel; }
    Switch:disabled { opacity: 50%; }
    """

    class Changed(Message):
        def __init__(self, switch: Switch, on: bool) -> None:
            super().__init__()
            self.switch = switch
            self.on = on
            self.value = switch.value

        @property
        def control(self) -> Switch:
            return self.switch

    def __init__(
        self,
        label: str,
        *,
        value: str = "",
        on: bool = False,
        key: str | None = None,
        disabled: bool = False,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(label, key=key, disabled=disabled, id=id, classes=classes)
        self.value = value or label
        self.on = on
        self.set_class(on, "-on")

    def glyph_name(self) -> IconName:
        return "switch_on" if self.on else "switch_off"

    def set_on(self, on: bool, *, notify: bool = True) -> None:
        if on == self.on:
            return
        self.on = on
        self.set_class(on, "-on")
        self.refresh_label()
        if notify:
            self.post_message(self.Changed(self, on))

    def activate(self) -> None:
        self.set_on(not self.on)


class RadioGroupItem(Action):
    """One choice. Created with the group's other items; the group owns which is selected."""

    DEFAULT_CSS = """
    RadioGroupItem { width: auto; height: 1; padding: 0 1; color: $foreground; }
    RadioGroupItem:hover, RadioGroupItem:focus { background: $panel; }
    RadioGroupItem:disabled { opacity: 50%; }
    """

    def __init__(
        self,
        label: str,
        value: str = "",
        *,
        key: str | None = None,
        disabled: bool = False,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(label, key=key, disabled=disabled, id=id, classes=classes)
        self.value = value or label
        self.selected = False

    def glyph_name(self) -> IconName:
        return "radio_on" if self.selected else "radio_off"

    def activate(self) -> None:
        group = self.parent
        if isinstance(group, RadioGroup):
            group.select(self)


class RadioGroup(Vertical):
    """A single choice. Tab enters the group once, on the selected item; the arrow keys move
    the choice (and focus) to the previous or next enabled item, wrapping around."""

    DEFAULT_CSS = "RadioGroup { width: auto; height: auto; }"
    BINDINGS = [
        Binding("up,left", "step(-1)", show=False),
        Binding("down,right", "step(1)", show=False),
    ]

    class Changed(Message):
        def __init__(self, group: RadioGroup, value: str | None) -> None:
            super().__init__()
            self.group = group
            self.value = value

        @property
        def control(self) -> RadioGroup:
            return self.group

    def __init__(
        self,
        *items: RadioGroupItem,
        value: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(*items, id=id, classes=classes)
        self._initial = value

    @property
    def items(self) -> list[RadioGroupItem]:
        return list(self.query(RadioGroupItem))

    @property
    def value(self) -> str | None:
        return next((item.value for item in self.items if item.selected), None)

    def on_mount(self) -> None:
        for item in self.items:
            item.selected = item.value == self._initial
            item.refresh_label()
        self._roving()

    def _roving(self) -> None:
        enabled = [item for item in self.items if not item.disabled]
        active = next((i for i in enabled if i.selected), enabled[0] if enabled else None)
        for item in self.items:
            item.can_focus = item is active

    def select(self, item: RadioGroupItem, *, focus: bool = False) -> None:
        changed = not item.selected
        for other in self.items:
            other.selected = other is item
            other.refresh_label()
        self._roving()
        if focus:
            item.focus()
        if changed:
            self.post_message(self.Changed(self, item.value))

    def action_step(self, direction: int) -> None:
        enabled = [item for item in self.items if not item.disabled]
        focused = self.screen.focused
        if focused not in enabled:
            raise SkipAction()
        self.select(enabled[(enabled.index(focused) + direction) % len(enabled)], focus=True)
