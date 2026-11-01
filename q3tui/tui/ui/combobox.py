"""Combobox: an input that filters a list and fills itself from it, following shadcn's Combobox.

Focus stays in the input the whole time: Down and Up move through the list, Enter chooses, Escape
closes it, and typing filters it.
"""

from __future__ import annotations

from dataclasses import dataclass

from textual import on
from textual.binding import Binding
from textual.message import Message
from textual.widgets import Input as TextualInput
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from q3tui.tui.ui.input import Input
from q3tui.tui.ui.menu import background_beneath
from q3tui.tui.ui.search import fuzzy_score

__all__ = ["Combobox", "ComboboxItem"]


@dataclass
class ComboboxItem:
    label: str
    value: str = ""
    disabled: bool = False


class _Popup(OptionList, can_focus=False):
    """The list under the input. It never takes focus, so typing keeps going to the input."""

    DEFAULT_CSS = """
    _Popup { overlay: screen; position: absolute; constrain: inside inside; height: auto;
        max-height: 10; padding: 0; border: none; background: $surface; color: $foreground;
        border-top: outer $background; border-bottom: outer $background; }
    _Popup > .option-list--option { padding: 0 1; }
    _Popup > .option-list--option-highlighted { background: $primary-muted; color: $foreground; }
    """

    def __init__(self, owner: Combobox) -> None:
        super().__init__(markup=False)
        self.owner = owner

    async def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        # The popup lives on the Screen, so its messages do not pass through the Combobox.
        event.stop()
        await self.owner.choose_row(event.option_index)


class Combobox(Input):
    """`Combobox(ComboboxItem("Apple"), "Banana", value="Apple")`. Choosing posts
    `Combobox.Chosen(combobox, value, label)`."""

    BINDINGS = [
        Binding("down", "move(1)", show=False),
        Binding("up", "move(-1)", show=False),
        Binding("escape", "close", show=False),
    ]

    class Chosen(Message):
        def __init__(self, combobox: Combobox, value: str, label: str) -> None:
            super().__init__()
            self.combobox = combobox
            self.value = value
            self.label = label

        @property
        def control(self) -> Combobox:
            return self.combobox

    def __init__(
        self,
        *items: ComboboxItem | str,
        value: str | None = None,
        placeholder: str = "Search…",
        empty_text: str = "No results.",
        disabled: bool = False,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        self.items = [ComboboxItem(i) if isinstance(i, str) else i for i in items]
        self.empty_text = empty_text
        self.chosen: ComboboxItem | None = None
        self._popup: _Popup | None = None
        self._silent = False
        super().__init__(placeholder=placeholder, disabled=disabled, id=id, classes=classes)
        self._initial = value

    @property
    def choice(self) -> str | None:
        """The value of the chosen item, or `None`. (`value` is the text in the input.)"""
        return (self.chosen.value or self.chosen.label) if self.chosen else None

    def on_mount(self) -> None:
        if self._initial is not None:
            self.set_value(self._initial, notify=False)

    def set_value(self, value: str | None, *, notify: bool = True) -> None:
        item = next((i for i in self.items if (i.value or i.label) == value), None)
        if value is not None and item is None:
            raise ValueError(f"Unknown combobox value: {value!r}")
        self.chosen = item
        self._silent = True
        self.value = item.label if item else ""
        self._silent = False
        if item and notify:
            self.post_message(self.Chosen(self, item.value or item.label, item.label))

    # -- popup --------------------------------------------------------------------------------
    def _matches(self) -> list[ComboboxItem]:
        query = "" if self.chosen and self.value == self.chosen.label else self.value
        ranked = []
        for position, item in enumerate(self.items):
            score = fuzzy_score(query, item.label)
            if score is not None:
                ranked.append((score, position, item))
        ranked.sort(key=lambda entry: entry[:2])
        return [item for _, _, item in ranked]

    def _fill(self) -> None:
        if self._popup is None:
            return
        matches = self._matches()
        self._popup.clear_options()
        if matches:
            self._popup.add_options(
                Option(i.label, id=i.value or i.label, disabled=i.disabled) for i in matches
            )
            first = next((n for n, i in enumerate(matches) if not i.disabled), None)
            self._popup.highlighted = first
        else:
            self._popup.add_option(Option(self.empty_text, disabled=True))
        self.call_after_refresh(self._place)

    def _place(self) -> None:
        popup = self._popup
        if popup is None or not popup.is_mounted:
            return
        popup.styles.width = self.region.width
        popup.styles.offset = (self.region.x, self.region.bottom)
        popup.styles.border_top = ("outer", background_beneath(popup, popup.region.y))
        popup.styles.border_bottom = ("outer", background_beneath(popup, popup.region.bottom - 1))

    async def open_popup(self) -> None:
        if self._popup is not None:
            return
        self._popup = _Popup(self)
        await self.screen.mount(self._popup)
        self._fill()

    async def close_popup(self) -> None:
        popup, self._popup = self._popup, None
        if popup is not None and popup.is_mounted:
            await popup.remove()

    @property
    def is_open(self) -> bool:
        return self._popup is not None

    async def action_move(self, direction: int) -> None:
        if self._popup is None:
            await self.open_popup()
            return
        self._popup.action_cursor_down() if direction > 0 else self._popup.action_cursor_up()

    async def action_close(self) -> None:
        await self.close_popup()

    async def choose(self, item: ComboboxItem) -> None:
        self.set_value(item.value or item.label)
        await self.close_popup()

    # -- events -------------------------------------------------------------------------------
    @on(TextualInput.Changed)
    async def _typed(self, event: TextualInput.Changed) -> None:
        if self._silent or (self.chosen and event.value == self.chosen.label):
            return  # Set by us, not typed: the message arrives after `_silent` is reset.
        self.chosen = None
        await self.open_popup()
        self._fill()

    @on(TextualInput.Submitted)
    async def _submitted(self, event: TextualInput.Submitted) -> None:
        if self._popup is None or self._popup.highlighted is None:
            return
        event.stop()
        await self.choose_row(self._popup.highlighted)

    async def choose_row(self, index: int) -> None:
        matches = self._matches()
        if 0 <= index < len(matches) and not matches[index].disabled:
            await self.choose(matches[index])

    def on_blur(self) -> None:
        self.call_after_refresh(self.close_popup)

    async def on_unmount(self) -> None:
        await self.close_popup()
